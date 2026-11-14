.PHONY: install dev run test health smoke verify service register clean help

PYTHON ?= python3
VENV   ?= .venv
PORT   ?= 8200
NAME    = $(shell $(PYTHON) -c "import json; print(json.load(open('ceiba.json'))['name'])")
DISPLAY = $(shell $(PYTHON) -c "import json; print(json.load(open('ceiba.json'))['displayName'])")
VPY     = $(VENV)/bin/python

help:
	@echo "make install   - venv + deps + schema + .env (operator token)"
	@echo "make dev       - dev server on port $(PORT) (auto-reload)"
	@echo "make service   - render deploy/service.tmpl and enable it (systemd; user unit, system unit as root)"
	@echo "make smoke     - L1 smoke against the running server"
	@echo "make verify    - validate ceiba.json against the bundled ceiba.schema.json (offline)"
	@echo "make register  - print the registry entry to submit to ceiba.to"
	@echo "make clean     - remove venv + sqlite db"

install:
	$(PYTHON) -m venv $(VENV)
	$(VPY) -m pip install -q -U pip
	$(VPY) -m pip install -q -r requirements.txt
	mkdir -p data
	$(VPY) -c "import sqlite3; c=sqlite3.connect('data/db.sqlite'); c.executescript(open('sql/001_init.sql').read()); c.commit(); print('schema applied')"
	@test -f .env || { umask 077; echo "CEIBA_OPERATOR_TOKEN=$$($(VPY) -c 'import secrets; print(secrets.token_urlsafe(32))')" > .env; echo ".env created with a fresh CEIBA_OPERATOR_TOKEN (writes enabled; delete the line to disable)"; }

dev:
	set -a; [ -f .env ] && . ./.env; set +a; $(VENV)/bin/uvicorn api.main:app --host 0.0.0.0 --port $(PORT) --reload

health:
	@curl -s http://localhost:$(PORT)/health | $(PYTHON) -m json.tool

smoke:
	@echo "-> /health"           && curl -sf http://localhost:$(PORT)/health | $(PYTHON) -m json.tool
	@echo "-> /.well-known/ceiba.json" && curl -sf http://localhost:$(PORT)/.well-known/ceiba.json | $(PYTHON) -c "import sys,json; d=json.load(sys.stdin); print('  name=', d['name'], 'proto=', d['protocol_version'], 'level=', d.get('compliance_level'))"
	@echo "-> /v1/stats"         && curl -sf http://localhost:$(PORT)/v1/stats | $(PYTHON) -m json.tool
	@echo "-> /llms.txt"         && curl -sf http://localhost:$(PORT)/llms.txt | head -3
	@echo "-> /admin"            && curl -sf http://localhost:$(PORT)/admin | grep -q "koa-patterns-runtime" && echo "  runtime tag present"

test: smoke

verify:
	@$(VPY) -c "import json, jsonschema; \
		schema=json.load(open('schema/ceiba.schema.json')); \
		manifest=json.load(open('ceiba.json')); \
		errs=sorted(jsonschema.Draft202012Validator(schema).iter_errors(manifest), key=lambda e: list(e.absolute_path)); \
		print('VALID' if not errs else f'{len(errs)} ERROR(S):'); \
		[print('  - ' + '/'.join(str(p) for p in e.absolute_path) + ': ' + e.message[:120]) for e in errs[:10]]; \
		raise SystemExit(1 if errs else 0)"

service:
	@mkdir -p deploy/out
	@sed -e 's|[{][{]NAME[}][}]|$(NAME)|g' -e 's|[{][{]DISPLAY_NAME[}][}]|$(DISPLAY)|g' -e 's|[{][{]PORT[}][}]|$(PORT)|g' -e 's|[{][{]DIR[}][}]|$(CURDIR)|g' \
		-e 's|[{][{]WANTED_BY[}][}]|$(if $(filter 0,$(shell id -u)),multi-user.target,default.target)|g' deploy/service.tmpl > deploy/out/$(NAME).service
	@if [ "$$(id -u)" = "0" ]; then \
		install -m 644 deploy/out/$(NAME).service /etc/systemd/system/$(NAME).service && \
		systemctl daemon-reload && systemctl enable --now $(NAME) && echo "system unit $(NAME) enabled and started"; \
	else \
		mkdir -p $$HOME/.config/systemd/user && install -m 644 deploy/out/$(NAME).service $$HOME/.config/systemd/user/$(NAME).service && \
		systemctl --user daemon-reload && systemctl --user enable --now $(NAME) && echo "user unit $(NAME) enabled and started (loginctl enable-linger $$USER to survive logout)"; \
	fi

register:
	@$(VPY) -c "import json; m=json.load(open('ceiba.json')); print(json.dumps({'id': m['name'], 'name': m['displayName'], 'url': m['url'], 'protocol_version': m['protocol_version'], 'status': 'seed'}, indent=2))"
	@echo "Submit this entry to the ceiba.to registry (see https://ceiba.to/start-developer.html)."

clean:
	rm -rf $(VENV) data/db.sqlite deploy/out
