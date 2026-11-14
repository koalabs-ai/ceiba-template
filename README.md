# ceiba-template

Starter template for a [ceiba.to](https://ceiba.to) v0.5 node. Click **Use this template** above to create your own.

A ceiba is a federated community node: a small FastAPI service that publishes a manifest at `/.well-known/ceiba.json` and exposes a read API over `/v1/entities` (plus `/v1/<plural>` aliases) and an operator write API. This template ships **Compliance Level 1** out of the box.

## 60-second quickstart

```bash
git clone https://github.com/your-username/your-ceiba && cd your-ceiba
make install     # venv + deps + SQLite schema + .env with a random CEIBA_OPERATOR_TOKEN
make dev         # uvicorn on :8200 (loads .env)
make smoke       # curl the L1 endpoints
```

Open `ceiba.json` and customize: `name`, `displayName`, `description`, `url`, `identity.entity_types`. Then validate:

```bash
make verify      # validates ceiba.json against schema/ceiba.schema.json (offline)
```

## One-click deploy

| Provider | One-click |
|---|---|
| **Fly.io** | `flyctl launch --copy-config --no-deploy && flyctl deploy` (uses `fly.toml`) |
| **Render** | Connect this repo to Render — `render.yaml` is detected automatically |
| **Vercel** | Python serverless requires swapping SQLite for Turso/D1; see [docs/deploy-vercel.md](./docs/deploy-vercel.md) |
| **Any VPS** | Use the `Dockerfile`, or `uvicorn api.main:app --host 0.0.0.0 --port 8200` behind your reverse proxy |

After deployment, your manifest should respond at `https://<your-domain>/.well-known/ceiba.json` with HTTP 200.

## What's inside

```
api/main.py                  FastAPI app (one entities table, read + operator write API)
sql/001_init.sql             SQLite schema: entities, claims, edit history, federation links, karma ledger
schema/                      Bundled ceiba.schema.json (offline validation)
tests/                       pytest: read/write/auth/allowlist/manifest
templates/                   Jinja2 templates (home, list, detail, admin, about)
static/                      Shared JS (cookie consent, koa-patterns-runtime) + CSS
ceiba.json                   Manifest served at /.well-known/ceiba.json
Makefile                     install / dev / smoke / verify / service / register
fly.toml                     Fly.io deployment config
Dockerfile                   Container build (any provider)
.github/workflows/           CI: validates ceiba.json on every PR
```

## The API

One `entities` table with a `type` column; every query is parametrized, so no table or column name ever comes from a request. Types are `identity.entity_types` in `ceiba.json`; an unknown type is `404 Unknown entity type`. Plurals default to `type + "s"` (`entity` becomes `entities`); override under `_koa_gen.plurals`.

| Read (public) | |
|---|---|
| `GET /v1/entities?type=&search=&limit=&offset=` | list |
| `GET /v1/entities/{id}` | one entity with its edit history |
| `GET /v1/<plural>` and `/v1/<plural>/{id}` | same data, URL-compatible aliases |
| `GET /health`, `/.well-known/ceiba.json`, `/llms.txt`, `/v1/stats` | protocol endpoints |

| Write (operator) | |
|---|---|
| `POST /v1/entities` | create (slug unique per type, 409 on clash) |
| `PATCH /v1/entities/{id}` | change fields |
| `DELETE /v1/entities/{id}` | remove |

Writes need `Authorization: Bearer $CEIBA_OPERATOR_TOKEN`. With the variable unset they answer `403 writes disabled`; a wrong token is `401`. Bodies must send `Content-Length` and stay under 64 KB. Every write appends to `edit_history` (`edited_by = operator`, field diff). `make install` writes a random token to `.env`; `make service` installs a systemd unit that loads it.

Claims and OTP login are not implemented, so the manifest says `claim_enabled: false` and `auth_methods: ["operator_token"]`. It declares only what exists.

## Bumping to Compliance L2 / L3

You start at **L1 — Registered**. To progress:

- **L2 (Verified)** — implement `/v1/entities/<id>/claim` + an `auth_methods` flow (WhatsApp OTP, email, OAuth). Surface profile statuses in your UI.
- **L3 (Validated)** — add an MCP server at `/mcp`, Schema.org / JSON-LD markup, cross-ceiba identity tokens, richer `/llms.txt`.

Reference L3 baseline to imitate: [lacartelera.app](https://lacartelera.app/.well-known/ceiba.json).

## Register on the network

```bash
make register    # prints the entry
```

That prints the entry that will appear in [`ceiba.to/ceibas.json`](https://ceiba.to/ceibas.json). Submit it to the public registry (Phase 3 will automate this — until then, email it to [hola@koalabs.ai](mailto:hola@koalabs.ai)).

## What is a ceiba?

Each community owns its own node:

- **The graph is free.** Public, open, API-first. Entities and relationships are CC BY 4.0 by default with auditable history.
- **The products are yours.** Dashboards, POS, booking engines, paid integrations — anything you build on top of the public graph is yours to monetize.
- **No token, no blockchain, no wallet required.** Optional payouts on validated edits flow over rails you choose: stablecoin, x402, fiat with invoice, lightning, MercadoPago, Stripe, Wise, and more.

See the [technical whitepaper](https://ceiba.to/whitepaper-tecnico.html) for the full v0.5 spec.

## Links

- 🌳 [ceiba.to](https://ceiba.to) — protocol home
- 📜 [JSON Schema (canonical)](https://ceiba.to/ceiba.schema.json)
- 📖 [Technical whitepaper](https://ceiba.to/whitepaper-tecnico.html)
- 🌐 [Live registry](https://ceiba.to/ceibas.json)
- 🤖 [For AI agents](https://ceiba.to/start-agent.html)
- ✉️ [hola@koalabs.ai](mailto:hola@koalabs.ai)

## License

The scaffold is licensed under the Apache License 2.0 (see `LICENSE`). The data your ceiba publishes is **CC BY 4.0 by default** (you can override per-ceiba in `ceiba.json`).
