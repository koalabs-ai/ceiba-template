.PHONY: install dev test health smoke verify register clean help

PYTHON ?= python3
VENV   ?= .venv
PORT   ?= 8200
NAME   = $(shell python3 -c "import json; print(json.load(open('ceiba.json'))['name'])")

help:
	@echo "make install   — venv + deps"
	@echo "make dev       — run dev server on port $(PORT)"
	@echo "make test      — run smoke tests against running server"
	@echo "make health    — curl /health"
	@echo "make smoke     — full L1 smoke trio"
	@echo "make verify    — validate ceiba.json against schema"
	@echo "make register  — append entry to ceiba.to ceibas.json"
	@echo "make clean     — remove venv + sqlite db"

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q -U pip
	$(VENV)/bin/pip install -q -r requirements.txt
	mkdir -p data
	$(VENV)/bin/python -c "import sqlite3; c=sqlite3.connect('data/db.sqlite'); c.executescript(open('sql/001_init.sql').read()); c.commit(); print('schema applied')"

dev:
	$(VENV)/bin/uvicorn api.main:app --host 0.0.0.0 --port $(PORT) --reload

health:
	@curl -s http://localhost:$(PORT)/health | python3 -m json.tool

smoke:
	@echo "→ /health"           && curl -sf http://localhost:$(PORT)/health | python3 -m json.tool
	@echo "→ /.well-known/ceiba.json" && curl -sf http://localhost:$(PORT)/.well-known/ceiba.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('  name=', d['name'], 'proto=', d['protocol_version'], 'level=', d.get('compliance_level'))"
	@echo "→ /v1/stats"         && curl -sf http://localhost:$(PORT)/v1/stats | python3 -m json.tool
	@echo "→ /llms.txt"         && curl -sf http://localhost:$(PORT)/llms.txt | head -3
	@echo "→ /admin"            && curl -sf http://localhost:$(PORT)/admin | grep -q "koa-patterns-runtime" && echo "  runtime tag present"

verify:
	@$(PYTHON) -c "import json, urllib.request, jsonschema; \
		req=urllib.request.Request('https://ceiba.to/ceiba.schema.json', headers={'User-Agent': 'koa-gen-ceiba/0.4'}); \
		schema=json.loads(urllib.request.urlopen(req).read()); \
		manifest=json.loads(open('ceiba.json').read()); \
		v=jsonschema.Draft202012Validator(schema); \
		errs=sorted(v.iter_errors(manifest), key=lambda e: e.path); \
		print('VALID' if not errs else f'{len(errs)} ERROR(S):'); \
		[print(f'  - {\"/\".join(str(p) for p in e.absolute_path) or \"(root)\"}: {e.message[:120]}') for e in errs[:10]]"

test: smoke

clean:
	rm -rf $(VENV) data/db.sqlite
