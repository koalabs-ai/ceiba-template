"""Hermetic tests: read API, write API (operator token), allowlist, manifest honesty."""
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "test-operator-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def load(monkeypatch, tmp_path, token=TOKEN):
    monkeypatch.setenv("CEIBA_DB", str(tmp_path / "t.sqlite"))
    if token:
        monkeypatch.setenv("CEIBA_OPERATOR_TOKEN", token)
    else:
        monkeypatch.delenv("CEIBA_OPERATOR_TOKEN", raising=False)
    name = f"ceiba_main_{abs(hash(str(tmp_path)))}"
    spec = importlib.util.spec_from_file_location(name, ROOT / "api" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # pydantic resolves postponed annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(monkeypatch, tmp_path):
    return TestClient(load(monkeypatch, tmp_path).app)


def make(client, **kw):
    return client.post("/v1/entities", json={"type": "entity", "name": "Casa Azul", **kw}, headers=AUTH)


def test_write_read_patch_delete_roundtrip(client):
    j = make(client, description="old").json()
    assert j["slug"] == "casa-azul" and client.get(f"/v1/entities/{j['id']}").json()["name"] == "Casa Azul"
    assert [e["id"] for e in client.get("/v1/entities?type=entity").json()] == [j["id"]]
    assert [e["id"] for e in client.get("/v1/entities").json()] == [j["id"]]  # plural of "entity" is "entities"
    r = client.patch(f"/v1/entities/{j['id']}", json={"description": "new"}, headers=AUTH).json()
    assert r["edit_history"][0]["field_changes"] == {"description": ["old", "new"]}
    assert r["edit_history"][0]["edited_by"] == "operator"
    assert client.delete(f"/v1/entities/{j['id']}", headers=AUTH).json() == {"deleted": j["id"]}
    assert client.get(f"/v1/entities/{j['id']}").status_code == 404


def test_writes_disabled_without_token(monkeypatch, tmp_path):
    c = TestClient(load(monkeypatch, tmp_path, token=None).app)
    r = c.post("/v1/entities", json={"type": "entity", "name": "x"}, headers=AUTH)
    assert r.status_code == 403 and r.json()["detail"] == "writes disabled"


def test_bad_or_missing_token_is_401(client):
    body = {"type": "entity", "name": "x"}
    assert client.post("/v1/entities", json=body).status_code == 401
    assert client.post("/v1/entities", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_slug_unique_per_type_and_validation(client):
    assert make(client).status_code == 201
    assert make(client).status_code == 409
    for bad in ({"type": "spaceship", "name": "x"}, {"type": "entity", "name": "x", "status": "wizard"},
                {"type": "entity", "name": "x", "unknown": 1}, {"type": "entity", "name": "x" * 201}):
        assert client.post("/v1/entities", json=bad, headers=AUTH).status_code == 422


@pytest.mark.parametrize("path", ["/v1/nonexistents", "/v1/entities?type=nope", "/v1/edit_historys",
                                  "/v1/%22%20OR%201=1--", "/v1/sqlite_masters/abc"])
def test_unknown_type_is_404_without_sql_text(client, path):
    r = client.get(path)
    assert r.status_code == 404 and "sqlite" not in r.text.lower() and "no such table" not in r.text.lower()


def test_manifest_is_honest_and_versions_agree(client):
    m = client.get("/.well-known/ceiba.json").json()
    assert m["identity"]["claim_enabled"] is False
    assert m["identity"]["auth_methods"] == ["operator_token"]
    assert f"protocol {m['protocol_version']}" in client.get("/llms.txt").text
