"""SQLAlchemy implementation of the owner-scoped reset transaction."""

from __future__ import annotations

import json

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from ..models import AuditLog, SessionToken, TENANT_MODELS


def deletion_order() -> list[type]:
    """Return children before parents for FK-safe owner-only deletion."""
    models = {model.__tablename__: model for model in TENANT_MODELS}
    dependencies = {
        table: {
            fk.column.table.name
            for column in model.__table__.columns
            for fk in column.foreign_keys
            if fk.column.table.name in models and fk.column.table.name != table
        }
        for table, model in models.items()
    }
    result: list[type] = []
    while dependencies:
        referenced = set().union(*dependencies.values())
        leaves = sorted(set(dependencies) - referenced)
        if not leaves:
            raise RuntimeError("Cycle in tenant foreign keys")
        for table in leaves:
            result.append(models[table])
            dependencies.pop(table)
    return result


class SqlAlchemyResetBudget:
    def __init__(self, db: Session):
        self.db = db

    def clear_budget(self, owner_id: int) -> dict[str, int]:
        counts: dict[str, int] = {}
        for model in deletion_order():
            result = self.db.execute(delete(model).where(model.user_id == owner_id))
            counts[model.__tablename__] = result.rowcount
        return counts

    def record_reset(self, owner_id: int, deleted: dict[str, int]) -> None:
        self.db.add(AuditLog(
            user_id=owner_id,
            entity_type="budget",
            entity_id=str(owner_id),
            action="reset",
            before_json=None,
            after_json=json.dumps({"deleted": deleted}, sort_keys=True),
        ))

    def revoke_other_sessions(self, owner_id: int, current_session_id: int) -> None:
        self.db.execute(
            update(SessionToken)
            .where(SessionToken.user_id == owner_id, SessionToken.id != current_session_id)
            .values(revoked=True)
        )

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
