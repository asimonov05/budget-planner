from __future__ import annotations

import platform
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import __version__
from ..config import config
from ..db import Base, engine, get_db
from ..models import User
from ..security import require_csrf_unlocked, require_user


router = APIRouter(prefix="/admin/debug", tags=["admin"])
HIDDEN_COLUMN_PARTS = (
    "password",
    "token",
    "secret",
    "credential",
    "hash",
    "key",
    "fingerprint",
)
TABLE_NAMES = {
    "accounts": "Счета",
    "audit_logs": "Журнал изменений",
    "app_settings": "Настройки приложения",
    "budget_limit_overrides": "Переопределения лимитов",
    "budget_limits": "Лимиты бюджета",
    "budget_months": "Бюджетные месяцы",
    "categories": "Категории",
    "goal_reserve_movements": "Движения резервов целей",
    "goals": "Цели",
    "import_batches": "Пакеты импорта",
    "idempotency_records": "Ключи идемпотентности",
    "loan_schedule_items": "График платежей кредитов",
    "loans": "Кредиты",
    "plan_item_tags": "Теги планов",
    "plan_items": "Пункты плана",
    "plan_matches": "Связи плана с операциями",
    "plan_overrides": "Изменения плана",
    "sessions": "Сессии",
    "tags": "Теги",
    "transaction_tags": "Теги операций",
    "transactions": "Операции",
    "transfers": "Переводы",
    "users": "Пользователи",
}


def require_debug_admin_enabled() -> None:
    if not config.debug_admin_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def require_debug_admin(
    _enabled: None = Depends(require_debug_admin_enabled),
    user: User = Depends(require_user),
) -> User:
    return user


def is_hidden_column(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in HIDDEN_COLUMN_PARTS)


def serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


def file_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"exists": False, "size_bytes": 0}
    return {
        "exists": path.is_file(),
        "size_bytes": stat.st_size if path.is_file() else 0,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


@router.get("/overview")
def debug_overview(
    _user: User = Depends(require_debug_admin), db: Session = Depends(get_db)
) -> dict[str, Any]:
    connection = db.connection()
    journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
    foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
    synchronous = connection.execute(text("PRAGMA synchronous")).scalar_one()
    try:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    except SQLAlchemyError:
        revision = None

    database_files = {
        "main": file_info(config.database_path),
        "wal": file_info(Path(f"{config.database_path}-wal")),
        "shm": file_info(Path(f"{config.database_path}-shm")),
    }
    backup_files = []
    if config.backup_dir.is_dir():
        backup_files = [
            path
            for path in config.backup_dir.iterdir()
            if path.is_file() and path.suffix == ".sqlite3"
        ]
    backup_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    latest_backup = backup_files[0] if backup_files else None

    return {
        "application": {
            "version": __version__,
            "python_version": platform.python_version(),
            "sqlite_version": sqlite3.sqlite_version,
            "debug_admin_enabled": config.debug_admin_enabled,
        },
        "database": {
            "file_name": config.database_path.name,
            "files": database_files,
            "journal_mode": str(journal_mode),
            "foreign_keys": bool(foreign_keys),
            "synchronous": int(synchronous),
            "schema_revision": revision,
            "safe_sqlite_required": config.require_safe_sqlite,
        },
        "backups": {
            "count": len(backup_files),
            "total_size_bytes": sum(path.stat().st_size for path in backup_files),
            "latest": (
                {
                    "name": latest_backup.name,
                    "size_bytes": latest_backup.stat().st_size,
                    "modified_at": datetime.fromtimestamp(
                        latest_backup.stat().st_mtime, timezone.utc
                    ).isoformat(),
                }
                if latest_backup
                else None
            ),
        },
    }


@router.get("/tables")
def debug_tables(
    _user: User = Depends(require_debug_admin), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    result = []
    for name, table in sorted(Base.metadata.tables.items()):
        count = db.scalar(select(func.count()).select_from(table)) or 0
        result.append(
            {
                "name": name,
                "label": TABLE_NAMES.get(name, name.replace("_", " ").title()),
                "row_count": count,
            }
        )
    return result


@router.get("/tables/{table_name}/rows")
def debug_table_rows(
    table_name: str,
    offset: int = 0,
    limit: int = 50,
    _user: User = Depends(require_debug_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be non-negative")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise HTTPException(status_code=404, detail="Unknown table")

    columns = [column for column in table.columns if not is_hidden_column(column.name)]
    primary_keys = [column for column in table.primary_key.columns]
    statement = select(*columns)
    if primary_keys:
        statement = statement.order_by(*(column.desc() for column in primary_keys))
    rows = db.execute(statement.limit(limit).offset(offset)).mappings().all()
    total = db.scalar(select(func.count()).select_from(table)) or 0

    return {
        "name": table_name,
        "label": TABLE_NAMES.get(table_name, table_name.replace("_", " ").title()),
        "offset": offset,
        "limit": limit,
        "total": total,
        "columns": [
            {
                "name": column.name,
                "type": str(column.type),
                "primary_key": column.primary_key,
            }
            for column in columns
        ],
        "rows": [
            {column.name: serialize_value(row[column.name]) for column in columns}
            for row in rows
        ],
    }


@router.post("/database-check")
def debug_database_check(
    _user: User = Depends(require_debug_admin),
    _csrf_user: User = Depends(require_csrf_unlocked),
) -> dict[str, Any]:
    with engine.connect() as connection:
        integrity_rows = connection.exec_driver_sql("PRAGMA integrity_check").fetchmany(21)
        foreign_key_rows = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchmany(51)
    integrity_truncated = len(integrity_rows) > 20
    foreign_keys_truncated = len(foreign_key_rows) > 50
    integrity = [row[0] for row in integrity_rows[:20]]
    foreign_key_violations = [
        {"table": row[0], "rowid": row[1], "parent": row[2], "fkid": row[3]}
        for row in foreign_key_rows[:50]
    ]
    return {
        "integrity_check": integrity,
        "integrity_truncated": integrity_truncated,
        "foreign_key_violations": foreign_key_violations,
        "foreign_keys_truncated": foreign_keys_truncated,
        "ok": integrity == ["ok"] and not foreign_key_violations,
    }
