#!/bin/sh
set -eu

python -c 'import sqlite3; required=(3, 51, 3); actual=sqlite3.sqlite_version_info; assert actual >= required, f"SQLite {sqlite3.sqlite_version} is unsafe; need >= 3.51.3"'

if [ ! -d "${DATABASE_PATH%/*}" ] || [ ! -w "${DATABASE_PATH%/*}" ]; then
    echo "Database directory is not writable: ${DATABASE_PATH%/*}" >&2
    exit 1
fi

if [ ! -d "${BACKUP_DIR}" ] || [ ! -w "${BACKUP_DIR}" ]; then
    echo "Backup directory is not writable: ${BACKUP_DIR}" >&2
    exit 1
fi

exec "$@"
