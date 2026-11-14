"""
Your Ceiba — ceiba protocol 0.5 reference implementation.

One `entities` table (a `type` column, never a table per type) and parametrized
SQL only: no table or column name ever comes from a request.

  Public pages   GET /  /{plural}  /{type}/{slug}  /about  /admin
  Protocol (L1)  GET /health  /.well-known/ceiba.json  /ceiba.json  /llms.txt  /v1/stats
  Read API       GET /v1/entities?type=   /v1/entities/{id}
                 GET /v1/{plural}         /v1/{plural}/{id}     (URL-compatible aliases)
  Write API      POST /v1/entities   PATCH|DELETE /v1/entities/{id}
                 Authorization: Bearer $CEIBA_OPERATOR_TOKEN
                 token unset -> 403 "writes disabled"; every write lands in edit_history.

Claims and OTP login are NOT implemented, so the manifest does not advertise them.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# The single protocol version of this template: the manifest and llms.txt both use it.
PROTOCOL_VERSION = "0.5"

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("CEIBA_DB") or ROOT / "data" / "db.sqlite")
MANIFEST_PATH = ROOT / "ceiba.json"
SCHEMA_PATH = ROOT / "sql" / "001_init.sql"
STATIC_DIR = ROOT / "static"
TEMPLATES_DIR = ROOT / "templates"

PAGE_SIZE = 24
FEATURED_COUNT = 8
MAX_BODY_BYTES = 64 * 1024
MAX_DATA_BYTES = 16 * 1024
SCHEMA_ORG_TYPE = "Thing"  # e.g. "Person", "LocalBusiness", "Organization"

TYPE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
STATUSES = ("unclaimed", "pending", "verified", "claimed")
SOURCES = ("manual", "api_sync", "scrape", "import", "community", "claim")
# Columns a write may touch. These are code constants: input only ever selects among them.
EDITABLE_FIELDS = ("slug", "name", "description", "description_long", "image_url", "city",
                   "tags", "data", "source", "source_url", "status")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(s: str) -> str:
    """name -> URL-friendly slug. Strips accents, lowercase, kebab-case."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-_\s]+", "-", s).strip("-")


def default_plural(t: str) -> str:
    if re.search(r"[^aeiou]y$", t):
        return t[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", t):
        return t + "es"
    return t + "s"


def load_manifest(public: bool = True) -> dict[str, Any]:
    with open(MANIFEST_PATH) as f:
        m = json.load(f)
    m["protocol_version"] = PROTOCOL_VERSION
    if public:
        m.pop("deploy", None)
    return m


def load_types() -> tuple[dict[str, str], dict[str, str]]:
    """Entity-type allowlist from ceiba.json -> ({type: plural}, {plural: type})."""
    m = load_manifest(public=False)
    overrides = (m.get("_koa_gen") or {}).get("plurals") or {}
    plurals: dict[str, str] = {}
    for t in m.get("identity", {}).get("entity_types", []) or []:
        if isinstance(t, str) and TYPE_RE.fullmatch(t):
            p = overrides.get(t)
            plurals[t] = p if isinstance(p, str) and TYPE_RE.fullmatch(p) else default_plural(t)
    if not plurals:
        plurals = {"entity": "entities"}
    return plurals, {p: t for t, p in plurals.items()}


PLURAL_OF, TYPE_OF_PLURAL = load_types()
DEFAULT_TYPE = next(iter(PLURAL_OF))


def type_display(t: str) -> str:
    return PLURAL_OF[t].replace("_", " ").title()


app = FastAPI(
    title="Your Ceiba",
    description="A ceiba node — edit this description before going live.",
    version="0.2.0",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_schema_ready: set[str] = set()


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(DB_PATH) not in _schema_ready:  # idempotent: CREATE IF NOT EXISTS only
        conn.executescript(SCHEMA_PATH.read_text())
        _schema_ready.add(str(DB_PATH))
    return conn


def base_ctx(request: Request) -> dict[str, Any]:
    """Common Jinja context for every page."""
    return {
        "request": request,
        "ceiba_name": "your-ceiba",
        "display_name": "Your Ceiba",
        "description": "A ceiba node — edit this description before going live.",
        "domain": "your-ceiba.example",
        "protocol_version": PROTOCOL_VERSION,
        "types": [{"type": t, "plural": p, "display": type_display(t)} for t, p in PLURAL_OF.items()],
        "schema_org_type": SCHEMA_ORG_TYPE,
        "ga_ids": "",
    }


def row_out(row: sqlite3.Row | dict) -> dict[str, Any]:
    """Decode the JSON columns (tags, data) of an entities row."""
    d = dict(row)
    for k in ("tags", "data"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                d[k] = None
    return d


def history_for(db: sqlite3.Connection, entity_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM edit_history WHERE entity_id = ? ORDER BY id DESC LIMIT 50", (entity_id,)
    ).fetchall()
    out = []
    for h in rows:
        d = dict(h)
        try:
            d["field_changes"] = json.loads(d["field_changes"])
        except (TypeError, json.JSONDecodeError):
            pass
        out.append(d)
    return out


# ────────────────────────────────────────────────────────────
# Protocol endpoints (Level 1)
# ────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ceiba": "your-ceiba", "version": app.version, "protocol_version": PROTOCOL_VERSION, "ts": now_iso()}


@app.get("/.well-known/ceiba.json")
def well_known() -> JSONResponse:
    return JSONResponse(load_manifest(public=True))


@app.get("/ceiba.json")
def ceiba_json_alias() -> JSONResponse:
    return JSONResponse(load_manifest(public=True))


@app.get("/v1/llms.txt", response_class=PlainTextResponse)
@app.get("/llms.txt", response_class=PlainTextResponse)
def llms_txt() -> str:
    m = load_manifest()
    lines = [
        f"# {m['displayName']}",
        f"> {m['description']}",
        "",
        "## API",
        f"Base URL: {m['api']['base_url']}",
        f"Docs: {m['url']}docs",
        "Read: GET /v1/entities?type=<type>&search=&limit=&offset= , GET /v1/entities/{id}",
        "Write: POST /v1/entities, PATCH|DELETE /v1/entities/{id} (operator bearer token; disabled unless configured)",
        "",
        "## Public pages",
    ]
    for t, p in PLURAL_OF.items():
        lines.append(f"- {m['url']}{p} (list) and {m['url']}{t}/{{slug}} (detail)")
    lines += [
        "",
        "## Entity Types",
        ", ".join(m["identity"]["entity_types"]),
        "",
        "## Protocol",
        f"ceiba protocol {PROTOCOL_VERSION}. See https://ceiba.to for the spec.",
        "",
    ]
    return "\n".join(lines)


@app.get("/v1/stats")
def stats() -> dict[str, Any]:
    db = get_db()
    counts = {r["type"]: r["c"] for r in db.execute("SELECT type, COUNT(*) AS c FROM entities GROUP BY type")}
    breakdown = {PLURAL_OF[t]: counts.get(t, 0) for t in PLURAL_OF}
    return {
        "service": "your-ceiba",
        "entities": sum(breakdown.values()),
        "members": 0,
        "events": 0,
        "breakdown": breakdown,
    }


# ────────────────────────────────────────────────────────────
# Read API
# ────────────────────────────────────────────────────────────


def _unknown_type() -> HTTPException:
    return HTTPException(404, "Unknown entity type")


def _list(type_: str | None, limit: int, offset: int, search: str | None) -> list[dict[str, Any]]:
    if type_ is not None and type_ not in PLURAL_OF:
        raise _unknown_type()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where, params = [], []
    if type_ is not None:
        where.append("type = ?")
        params.append(type_)
    if search:
        where.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    sql = "SELECT * FROM entities"
    if where:
        sql += " WHERE " + " AND ".join(where)  # fixed fragments only, values are bound
    sql += " ORDER BY created_at DESC, id LIMIT ? OFFSET ?"
    rows = get_db().execute(sql, params + [limit, offset]).fetchall()
    return [row_out(r) for r in rows]


def _get(entity_id: str, type_: str | None = None) -> dict[str, Any]:
    db = get_db()
    row = db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not row or (type_ is not None and row["type"] != type_):
        raise HTTPException(404, "not found")
    return {**row_out(row), "edit_history": history_for(db, entity_id)}


@app.get("/v1/entities")
def list_entities(type: str | None = None, limit: int = 50, offset: int = 0, search: str | None = None):
    return _list(type, limit, offset, search)


@app.get("/v1/entities/{entity_id}")
def get_entity(entity_id: str):
    return _get(entity_id)


@app.get("/v1/{plural}")
def list_by_plural(plural: str, limit: int = 50, offset: int = 0, search: str | None = None):
    if plural not in TYPE_OF_PLURAL:
        raise _unknown_type()
    return _list(TYPE_OF_PLURAL[plural], limit, offset, search)


@app.get("/v1/{plural}/{entity_id}")
def get_by_plural(plural: str, entity_id: str):
    if plural not in TYPE_OF_PLURAL:
        raise _unknown_type()
    return _get(entity_id, TYPE_OF_PLURAL[plural])


# ────────────────────────────────────────────────────────────
# Write API (operator token)
# ────────────────────────────────────────────────────────────


def require_operator(authorization: str | None = Header(default=None)) -> str:
    token = os.environ.get("CEIBA_OPERATOR_TOKEN", "")
    if not token:
        raise HTTPException(403, "writes disabled")
    scheme, _, cred = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(cred.strip().encode(), token.encode()):
        raise HTTPException(401, "invalid or missing operator token", headers={"WWW-Authenticate": "Bearer"})
    return "operator"


@app.middleware("http")
async def limit_body(request: Request, call_next):
    """Refuse oversized write bodies before they are read (Content-Length is required on writes)."""
    if request.method in ("POST", "PATCH", "PUT"):
        raw = request.headers.get("content-length")
        if raw is None or not raw.isdigit():
            return JSONResponse({"detail": "Content-Length required"}, status_code=411)
        if int(raw) > MAX_BODY_BYTES:
            return JSONResponse({"detail": f"body larger than {MAX_BODY_BYTES} bytes"}, status_code=413)
    return await call_next(request)


class _EntityFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str | None = Field(default=None, max_length=500)
    description_long: str | None = Field(default=None, max_length=20000)
    image_url: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=120)
    tags: list[Annotated[str, StringConstraints(max_length=60)]] | None = Field(default=None, max_length=50)
    data: dict[str, Any] | None = None
    source: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    status: str | None = None
    reason: str | None = Field(default=None, max_length=300)  # recorded in edit_history, not stored on the entity

    @field_validator("data")
    @classmethod
    def _data_size(cls, v):
        if v is not None and len(json.dumps(v)) > MAX_DATA_BYTES:
            raise ValueError(f"data larger than {MAX_DATA_BYTES} bytes")
        return v

    @field_validator("source")
    @classmethod
    def _source_ok(cls, v):
        if v is not None and v not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}")
        return v

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v):
        if v is not None and v not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        return v

    @field_validator("slug", check_fields=False)
    @classmethod
    def _slug_ok(cls, v):
        if v is not None and not SLUG_RE.fullmatch(v):
            raise ValueError("slug must be kebab-case: [a-z0-9-], 1-80 chars")
        return v


class EntityCreate(_EntityFields):
    type: str
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = None

    @field_validator("type")
    @classmethod
    def _type_ok(cls, v):
        if v not in PLURAL_OF:
            raise ValueError(f"type must be one of {list(PLURAL_OF)}")
        return v


class EntityPatch(_EntityFields):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = None


def _json_col(field: str, value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if field in ("tags", "data") and value is not None else value


def _record(db: sqlite3.Connection, entity_type: str, entity_id: str, changes: dict, reason: str | None, who: str) -> None:
    db.execute(
        "INSERT INTO edit_history (entity_type, entity_id, field_changes, reason, edited_by, edited_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, json.dumps(changes, ensure_ascii=False), reason, who, now_iso()),
    )


@app.post("/v1/entities", status_code=201)
def create_entity(body: EntityCreate, who: str = Depends(require_operator)):
    slug = body.slug or slugify(body.name)
    if not SLUG_RE.fullmatch(slug):
        raise HTTPException(422, "could not derive a valid slug from name; pass slug")
    entity_id = "ent_" + uuid.uuid4().hex[:12]
    db = get_db()
    now = now_iso()
    values = {f: _json_col(f, getattr(body, f)) for f in EDITABLE_FIELDS if f not in ("slug", "name", "source", "status")}
    try:
        with db:
            db.execute(
                "INSERT INTO entities (id, type, slug, name, description, description_long, image_url, city, "
                "tags, data, source, source_url, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entity_id, body.type, slug, body.name, values["description"], values["description_long"],
                 values["image_url"], values["city"], values["tags"], values["data"],
                 body.source or "manual", values["source_url"], body.status or "unclaimed", now, now),
            )
            created = {"_created": [None, {"type": body.type, "slug": slug, "name": body.name}]}
            _record(db, body.type, entity_id, created, body.reason, who)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "slug already exists for this type")
    return _get(entity_id)


@app.patch("/v1/entities/{entity_id}")
def patch_entity(entity_id: str, body: EntityPatch, who: str = Depends(require_operator)):
    db = get_db()
    row = db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "not found")
    current = row_out(row)
    changes: dict[str, list[Any]] = {}
    sets, params = [], []
    for field in EDITABLE_FIELDS:
        if field not in body.model_fields_set:
            continue
        new = getattr(body, field)
        if new is None and field in ("name", "slug"):
            raise HTTPException(422, f"{field} cannot be null")
        if new == current.get(field):
            continue
        changes[field] = [current.get(field), new]
        assert field in EDITABLE_FIELDS  # defensive: column names only ever come from the constant
        sets.append(f"{field} = ?")
        params.append(_json_col(field, new))
    if not changes:
        raise HTTPException(422, "no changes")
    try:
        with db:
            db.execute(
                "UPDATE entities SET " + ", ".join(sets) + ", updated_at = ? WHERE id = ?",
                params + [now_iso(), entity_id],
            )
            _record(db, row["type"], entity_id, changes, body.reason, who)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "slug already exists for this type")
    return _get(entity_id)


@app.delete("/v1/entities/{entity_id}")
def delete_entity(entity_id: str, reason: str | None = None, who: str = Depends(require_operator)):
    db = get_db()
    row = db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "not found")
    snapshot = row_out(row)
    with db:
        db.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        _record(db, row["type"], entity_id, {"_deleted": [snapshot, None]}, (reason or "")[:300] or None, who)
    return {"deleted": entity_id}


# ────────────────────────────────────────────────────────────
# Public SSR pages
# ────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"]
    featured = [dict(r) for r in db.execute(
        "SELECT * FROM entities WHERE image_url IS NOT NULL AND image_url != '' ORDER BY RANDOM() LIMIT ?",
        (FEATURED_COUNT,),
    )]
    cities = db.execute("SELECT COUNT(DISTINCT city) AS c FROM entities WHERE city IS NOT NULL").fetchone()["c"]
    return templates.TemplateResponse(
        request, "home.html",
        {**base_ctx(request), "stats": {"entities": total, "cities": cities, "members": 0},
         "featured": featured, "primary": DEFAULT_TYPE, "primary_plural": PLURAL_OF[DEFAULT_TYPE],
         "primary_display": type_display(DEFAULT_TYPE)},
    )


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {**base_ctx(request)})


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(request, "admin.html", {
        **base_ctx(request),
        "writes_enabled": bool(os.environ.get("CEIBA_OPERATOR_TOKEN")),
    })


@app.get("/{plural}", response_class=HTMLResponse)
def list_page(request: Request, plural: str, q: str | None = None, city: str | None = None, page: int = 1):
    if plural not in TYPE_OF_PLURAL:
        raise HTTPException(404, "not found")
    type_ = TYPE_OF_PLURAL[plural]
    page = max(1, page)
    where, params = ["type = ?"], [type_]
    if q:
        where.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if city:
        where.append("city = ?")
        params.append(city)
    where_sql = "WHERE " + " AND ".join(where)  # fixed fragments only, values are bound
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM entities " + where_sql, params).fetchone()["c"]
    rows = db.execute(
        "SELECT * FROM entities " + where_sql + " ORDER BY name ASC LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
    ).fetchall()
    cities = [c["city"] for c in db.execute(
        "SELECT DISTINCT city FROM entities WHERE type = ? AND city IS NOT NULL AND city != '' ORDER BY city",
        (type_,),
    )]
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    base = {k: v for k, v in {"q": q, "city": city}.items() if v}
    return templates.TemplateResponse(
        request, "list.html",
        {**base_ctx(request), "entity_type": type_, "plural": plural, "plural_display": type_display(type_),
         "entities": [dict(r) for r in rows], "total": total, "search": q or "", "cities": cities,
         "selected_city": city or "",
         "pagination": {"page": page, "total_pages": total_pages,
                        "query_prev": urlencode({**base, "page": page - 1}),
                        "query_next": urlencode({**base, "page": page + 1})}},
    )


@app.get("/{type}/{slug}", response_class=HTMLResponse)
def detail_page(request: Request, type: str, slug: str):
    if type not in PLURAL_OF:
        raise HTTPException(404, "not found")
    db = get_db()
    row = db.execute("SELECT * FROM entities WHERE type = ? AND slug = ?", (type, slug)).fetchone()
    if not row:
        raise HTTPException(404, "not found")
    entity = row_out(row)
    return templates.TemplateResponse(
        request, "detail.html",
        {**base_ctx(request), "entity": entity, "entity_type": type, "plural": PLURAL_OF[type],
         "plural_display": type_display(type), "edit_history": history_for(db, entity["id"])},
    )


# Entry point: `uvicorn api.main:app --host 0.0.0.0 --port 8200`
