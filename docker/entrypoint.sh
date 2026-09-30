#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ] || [ ! -r "${DATABASE_PASSWORD_FILE:-/missing-secret}" ]; then
    echo "PostgreSQL URL and readable password secret are required" >&2
    exit 1
fi

exec "$@"
