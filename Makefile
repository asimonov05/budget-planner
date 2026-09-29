UV ?= uv
PYTHON ?= backend/.venv/bin/python
SMOKE_PROJECT ?= budget-planner-smoke
SMOKE_PORT ?= 18080
SMOKE_ENV = BIND_HOST=127.0.0.1 APP_PORT=$(SMOKE_PORT) TRUSTED_HOSTS=127.0.0.1,localhost SESSION_COOKIE_SECURE=0 APP_IMAGE_TAG=smoke

.PHONY: sync test test-backend test-frontend lint lint-backend lint-frontend build build-frontend compose-config test-e2e smoke acceptance

sync:
	$(UV) sync --locked --project backend

test: test-backend test-frontend

test-backend:
	$(PYTHON) -m pytest backend/tests

test-frontend:
	npm --prefix frontend test

lint: lint-backend lint-frontend

lint-backend:
	$(PYTHON) -m ruff check backend/app backend/tests backend/alembic backend/scripts

lint-frontend:
	npm --prefix frontend run lint

build: build-frontend compose-config

build-frontend:
	npm --prefix frontend run build

compose-config:
	docker compose config --quiet

test-e2e:
	npm --prefix e2e test

smoke:
	@set -eu; \
		trap '$(SMOKE_ENV) docker compose -p $(SMOKE_PROJECT) down' EXIT; \
		$(SMOKE_ENV) docker compose -p $(SMOKE_PROJECT) up -d --build --wait; \
		curl --fail --show-error http://127.0.0.1:$(SMOKE_PORT)/api/v1/health/ready

acceptance: lint test build
	@set -eu; \
		trap '$(SMOKE_ENV) docker compose -p $(SMOKE_PROJECT) down' EXIT; \
		$(SMOKE_ENV) docker compose -p $(SMOKE_PROJECT) up -d --build --wait; \
		curl --fail --show-error http://127.0.0.1:$(SMOKE_PORT)/api/v1/health/ready; \
		BASE_URL=http://127.0.0.1:$(SMOKE_PORT) npm --prefix e2e test
