"""
Your Ceiba — ceiba.to v0.4 reference implementation (L1.5 directorio).

Implements compliance Level 1 (Registered) + minimal public directory UI:
  - Public:
      GET /                          → home (hero + featured grid)
      GET /entitys  → paginated list with filters (search + city)
      GET /entity/{slug} → detail page with Schema.org
      GET /about                     → simple about page
  - Protocol (L1):
      GET /health                    → operational status
      GET /ceiba.json + /.well-known/ceiba.json → manifest
      GET /v1/{type}s                → CRUD list
      GET /v1/{type}s/{id}           → CRUD detail with edit history
      GET /v1/stats                  → community stats
      GET /llms.txt                  → AI discoverability
  - Admin:
      GET /admin                     → KPI dashboard

To bump to Level 2: add claim flow + auth (see /v1/{type}s/{id}/claim).
To bump to Level 3: add MCP server + cross-ceiba identity tokens.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
MANIFEST_PATH = ROOT / "ceiba.json"
STATIC_DIR = ROOT / "static"
TEMPLATES_DIR = ROOT / "templates"

# Entity-type config (set at scaffold-init via entity)
ENTITY_TYPE = "entity"
ENTITY_TYPE_PLURAL = ENTITY_TYPE + "s"
ENTITY_TYPE_PLURAL_DISPLAY = "Entities"  # e.g., "Fotógrafos"
SCHEMA_ORG_TYPE = "Thing"  # e.g., "Person", "LocalBusiness", "Organization"

PAGE_SIZE = 24
FEATURED_COUNT = 8

app = FastAPI(
    title="Your Ceiba",
    description="A ceiba node — edit this description before going live.",
    version="0.1.0",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(s: str) -> str:
    """name → URL-friendly slug. Strips accents, lowercase, kebab-case."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    return re.sub(r"[-\s]+", "-", s)


def load_manifest(public: bool = True) -> dict[str, Any]:
    with open(MANIFEST_PATH) as f:
        m = json.load(f)
    if public:
        m.pop("deploy", None)
    return m


def base_ctx(request: Request) -> dict[str, Any]:
    """Common Jinja context for every page."""
    return {
        "request": request,
        "ceiba_name": "your-ceiba",
        "display_name": "Your Ceiba",
        "description": "A ceiba node — edit this description before going live.",
        "domain": "your-ceiba.example",
        "entity_type": ENTITY_TYPE,
        "entity_type_plural_display": ENTITY_TYPE_PLURAL_DISPLAY,
        "schema_org_type": SCHEMA_ORG_TYPE,
        "ga_ids": "",
    }


def parse_data(row: dict) -> dict:
    """Decode `data` JSON blob if present."""
    if row.get("data") and isinstance(row["data"], str):
        try:
            row["data"] = json.loads(row["data"])
        except json.JSONDecodeError:
            row["data"] = None
    return row


# ────────────────────────────────────────────────────────────
# Public SSR pages
# ────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    db = get_db()
    try:
        total = db.execute(f"SELECT COUNT(*) AS c FROM {ENTITY_TYPE_PLURAL}").fetchone()["c"]
        featured = db.execute(
            f"SELECT * FROM {ENTITY_TYPE_PLURAL} "
            f"WHERE image_url IS NOT NULL AND image_url != '' "
            f"ORDER BY RANDOM() LIMIT ?",
            (FEATURED_COUNT,),
        ).fetchall()
        featured = [dict(r) for r in featured]
        cities = db.execute(
            f"SELECT COUNT(DISTINCT city) AS c FROM {ENTITY_TYPE_PLURAL} WHERE city IS NOT NULL"
        ).fetchone()["c"]
    except sqlite3.OperationalError:
        total, featured, cities = 0, [], 0

    return templates.TemplateResponse(
        request,
        "home.html",
        {**base_ctx(request), "stats": {"entities": total, "cities": cities, "members": 0}, "featured": featured},
    )


@app.get(f"/{ENTITY_TYPE_PLURAL}", response_class=HTMLResponse)
def list_page(request: Request, q: str | None = None, city: str | None = None, page: int = 1):
    db = get_db()
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE

    where_clauses, params = [], []
    if q:
        where_clauses.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if city:
        where_clauses.append("city = ?")
        params.append(city)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        total = db.execute(f"SELECT COUNT(*) AS c FROM {ENTITY_TYPE_PLURAL} {where_sql}", params).fetchone()["c"]
        rows = db.execute(
            f"SELECT * FROM {ENTITY_TYPE_PLURAL} {where_sql} ORDER BY name ASC LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, offset],
        ).fetchall()
        cities_rows = db.execute(
            f"SELECT DISTINCT city FROM {ENTITY_TYPE_PLURAL} WHERE city IS NOT NULL AND city != '' ORDER BY city"
        ).fetchall()
    except sqlite3.OperationalError:
        total, rows, cities_rows = 0, [], []

    entities = [dict(r) for r in rows]
    cities_list = [c["city"] for c in cities_rows]

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    qparams_base = {"q": q, "city": city}
    qparams_base = {k: v for k, v in qparams_base.items() if v}

    pagination = {
        "page": page,
        "total_pages": total_pages,
        "query_prev": urlencode({**qparams_base, "page": page - 1}),
        "query_next": urlencode({**qparams_base, "page": page + 1}),
    }

    return templates.TemplateResponse(
        request,
        "list.html",
        {
            **base_ctx(request),
            "entities": entities,
            "total": total,
            "search": q or "",
            "cities": cities_list,
            "selected_city": city or "",
            "pagination": pagination,
        },
    )


@app.get(f"/{ENTITY_TYPE}/{{slug}}", response_class=HTMLResponse)
def detail_page(request: Request, slug: str):
    db = get_db()
    try:
        row = db.execute(f"SELECT * FROM {ENTITY_TYPE_PLURAL} WHERE slug = ?", (slug,)).fetchone()
    except sqlite3.OperationalError:
        raise HTTPException(404, "entity table missing")
    if not row:
        raise HTTPException(404, "not found")
    entity = parse_data(dict(row))
    history = db.execute(
        "SELECT * FROM edit_history WHERE entity_type=? AND entity_id=? ORDER BY edited_at DESC LIMIT 50",
        (ENTITY_TYPE, entity["id"]),
    ).fetchall()
    return templates.TemplateResponse(
        request,
        "detail.html",
        {**base_ctx(request), "entity": entity, "edit_history": [dict(h) for h in history]},
    )


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    return templates.TemplateResponse(
        request,
        "about.html" if (TEMPLATES_DIR / "about.html").exists() else "_base.html",
        {**base_ctx(request)},
    )


# ────────────────────────────────────────────────────────────
# Compliance Level 1 endpoints (per 99_docs/research/ceiba-protocol-spec.md §3)
# ────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ceiba": "your-ceiba", "version": app.version, "ts": now_iso()}


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
    return (
        f"# {m['displayName']}\n"
        f"> {m['description']}\n\n"
        f"## API\n"
        f"Base URL: {m['api']['base_url']}\n"
        f"Docs: {m['url']}docs\n\n"
        f"## Public pages\n"
        f"- {m['url']}{ENTITY_TYPE_PLURAL} (paginated list)\n"
        f"- {m['url']}{ENTITY_TYPE}/{{slug}} (entity detail)\n\n"
        f"## Entity Types\n"
        f"{', '.join(m['identity']['entity_types'])}\n\n"
        f"## Protocol\n"
        f"This is a ceiba.to community. See https://ceiba.to for the protocol spec.\n"
    )


@app.get("/v1/stats")
def stats() -> dict[str, Any]:
    db = get_db()
    try:
        total = db.execute(f"SELECT COUNT(*) AS c FROM {ENTITY_TYPE_PLURAL}").fetchone()["c"]
    except sqlite3.OperationalError:
        total = 0
    return {
        "service": "your-ceiba",
        "entities": total,
        "members": 0,
        "events": 0,
        "breakdown": {ENTITY_TYPE_PLURAL: total},
    }


# ────────────────────────────────────────────────────────────
# Entity CRUD standard (§9)
# ────────────────────────────────────────────────────────────


@app.get("/v1/{type}s")
def list_entities(type: str, limit: int = 50, offset: int = 0, search: str | None = None):
    db = get_db()
    try:
        if search:
            rows = db.execute(
                f"SELECT * FROM {type}s WHERE name LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f"%{search}%", limit, offset),
            ).fetchall()
        else:
            rows = db.execute(
                f"SELECT * FROM {type}s ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(404, f"Unknown entity type: {type} ({e})")
    return [parse_data(dict(r)) for r in rows]


@app.get("/v1/{type}s/{entity_id}")
def get_entity(type: str, entity_id: str):
    db = get_db()
    try:
        row = db.execute(f"SELECT * FROM {type}s WHERE id = ?", (entity_id,)).fetchone()
    except sqlite3.OperationalError as e:
        raise HTTPException(404, f"Unknown entity type: {type} ({e})")
    if not row:
        raise HTTPException(404, "not found")
    history = db.execute(
        "SELECT * FROM edit_history WHERE entity_type=? AND entity_id=? ORDER BY edited_at DESC LIMIT 50",
        (type, entity_id),
    ).fetchall()
    return {**parse_data(dict(row)), "edit_history": [dict(h) for h in history]}


# ────────────────────────────────────────────────────────────
# Admin UI (KPI dashboard with koa-patterns-runtime)
# ────────────────────────────────────────────────────────────


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(request, "admin.html", base_ctx(request))


# Entry point: `uvicorn api.main:app --host 0.0.0.0 --port 8200 --reload`
