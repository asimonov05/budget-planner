# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22.19.0-alpine3.22
ARG PYTHON_IMAGE=python:3.13.15-alpine3.24
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.19

FROM ${UV_IMAGE} AS uv

FROM ${NODE_IMAGE} AS frontend-build
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=$VITE_BASE_PATH
ENV NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_FACTOR=2 \
    NPM_CONFIG_FETCH_RETRY_MINTIMEOUT=20000 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=300000
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm ci --prefer-offline --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS backend-build
COPY --from=uv /uv /uvx /bin/
RUN apk add --no-cache build-base libffi-dev
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    STATIC_DIR=/app/static \
    PATH=/app/.venv/bin:$PATH

RUN apk add --no-cache libffi \
    && addgroup -S -g "${APP_GID}" budget \
    && adduser -S -D -H -u "${APP_UID}" -G budget budget \
    && mkdir -p /app/static \
    && chown -R budget:budget /app

WORKDIR /app
COPY --from=backend-build --chown=budget:budget /app/.venv /app/.venv

COPY --chown=budget:budget backend/ ./
COPY --from=frontend-build --chown=budget:budget /src/frontend/dist/ ./static/
COPY --chown=budget:budget docker/entrypoint.sh ./docker/entrypoint.sh

USER budget:budget
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "app.start"]
