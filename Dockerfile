# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22.19.0-alpine3.22
ARG PYTHON_IMAGE=python:3.13.15-alpine3.24

FROM ${NODE_IMAGE} AS frontend-build
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
WORKDIR /build
RUN apk add --no-cache build-base libffi-dev
COPY backend/requirements.lock ./requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip wheel --wheel-dir=/wheels --requirement requirements.lock

FROM ${PYTHON_IMAGE} AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DATABASE_PATH=/data/budget.sqlite3 \
    BACKUP_DIR=/backups \
    STATIC_DIR=/app/static \
    REQUIRE_SAFE_SQLITE=1

RUN apk add --no-cache libffi sqlite-libs \
    && addgroup -S -g "${APP_GID}" budget \
    && adduser -S -D -H -u "${APP_UID}" -G budget budget \
    && mkdir -p /app/static /data /backups \
    && chown -R budget:budget /app /data /backups

WORKDIR /app
COPY --from=backend-build /wheels /wheels
COPY backend/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels --requirement requirements.lock \
    && rm -rf /wheels \
    && python -c 'import sqlite3; assert sqlite3.sqlite_version_info >= (3, 51, 3), sqlite3.sqlite_version'

COPY --chown=budget:budget backend/ ./
COPY --from=frontend-build --chown=budget:budget /src/frontend/dist/ ./static/
COPY --chown=budget:budget docker/entrypoint.sh ./docker/entrypoint.sh

USER budget:budget
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "app.start"]
