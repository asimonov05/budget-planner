from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampVersionMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    version: Mapped[int] = mapped_column(Integer, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict:
        # Make the version check part of UPDATE/DELETE itself.  Comparing the
        # version in an endpoint before commit is not enough: two sessions can
        # both pass that comparison and otherwise overwrite each other.
        return {"version_id_col": cls.version, "version_id_generator": False}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionToken(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSettings(Base, TimestampVersionMixin):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    accounting_start_date: Mapped[date] = mapped_column(Date, default=date.today)


class Account(Base, TimestampVersionMixin):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(24), default="bank")
    initial_balance_minor: Mapped[int] = mapped_column(Integer, default=0)
    initial_balance_date: Mapped[date] = mapped_column(Date)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Category(Base, TimestampVersionMixin):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="expense")
    color: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_estimate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class Tag(Base, TimestampVersionMixin):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    color: Mapped[str | None] = mapped_column(String(16))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Goal(Base, TimestampVersionMixin):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    target_amount_minor: Mapped[int] = mapped_column(Integer)
    target_date: Mapped[date | None] = mapped_column(Date)
    initial_reserved_minor: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="active")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("target_amount_minor >= 0"),
        CheckConstraint("initial_reserved_minor >= 0"),
    )


class Transaction(Base, TimestampVersionMixin):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), index=True)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), index=True)
    principal_component_minor: Mapped[int | None] = mapped_column(Integer)
    interest_component_minor: Mapped[int | None] = mapped_column(Integer)
    prepayment_strategy: Mapped[str | None] = mapped_column(String(24))
    loan_balance_applied: Mapped[bool | None] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(String(300), default="")
    comment: Mapped[str | None] = mapped_column(Text)
    external_source: Mapped[str | None] = mapped_column(String(80))
    external_id: Mapped[str | None] = mapped_column(String(160))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    tags: Mapped[list[Tag]] = relationship(secondary="transaction_tags", lazy="selectin")
    __table_args__ = (
        CheckConstraint(
            "(type = 'adjustment' AND amount_minor <> 0) "
            "OR (type <> 'adjustment' AND amount_minor > 0)"
        ),
        UniqueConstraint(
            "external_source", "account_id", "external_id", name="uq_transaction_external"
        ),
    )


class TransactionTag(Base):
    __tablename__ = "transaction_tags"
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class Transfer(Base, TimestampVersionMixin):
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("amount_minor > 0"),
        CheckConstraint("from_account_id <> to_account_id"),
    )


class PlanItem(Base, TimestampVersionMixin):
    __tablename__ = "plan_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(Integer)
    date: Mapped[date | None] = mapped_column(Date, index=True)
    month: Mapped[str | None] = mapped_column(String(7), index=True)
    recurrence: Mapped[str] = mapped_column(String(16), default="none")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    certainty: Mapped[str] = mapped_column(String(16), default="confirmed")
    status: Mapped[str] = mapped_column(String(16), default="planned")
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"))
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), index=True)
    funding_source: Mapped[str] = mapped_column(String(16), default="free")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[Tag]] = relationship(secondary="plan_item_tags", lazy="selectin")
    __table_args__ = (CheckConstraint("amount_minor >= 0"),)


class PlanItemTag(Base):
    __tablename__ = "plan_item_tags"
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class PlanOverride(Base):
    __tablename__ = "plan_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_items.id", ondelete="CASCADE"), index=True
    )
    month: Mapped[str] = mapped_column(String(7))
    amount_minor: Mapped[int | None] = mapped_column(Integer)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    moved_date: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (UniqueConstraint("plan_item_id", "month"),)


class PlanMatch(Base):
    __tablename__ = "plan_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_items.id", ondelete="CASCADE"), index=True
    )
    occurrence_month: Mapped[str] = mapped_column(String(7), index=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), unique=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class BudgetLimit(Base, TimestampVersionMixin):
    __tablename__ = "budget_limits"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    start_month: Mapped[str] = mapped_column(String(7))
    end_month: Mapped[str | None] = mapped_column(String(7))
    __table_args__ = (CheckConstraint("amount_minor >= 0"),)


class BudgetLimitOverride(Base):
    __tablename__ = "budget_limit_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_limit_id: Mapped[int] = mapped_column(ForeignKey("budget_limits.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))
    amount_minor: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("budget_limit_id", "month"),)


class GoalReserveMovement(Base):
    __tablename__ = "goal_reserve_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), unique=True)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("amount_minor > 0"),)


class Loan(Base, TimestampVersionMixin):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    creditor: Mapped[str | None] = mapped_column(String(160))
    principal_minor: Mapped[int | None] = mapped_column(Integer)
    principal_as_of: Mapped[date | None] = mapped_column(Date)
    annual_rate_bps: Mapped[int | None] = mapped_column(Integer)
    interest_method: Mapped[str] = mapped_column(
        String(16), default="simple", server_default="simple"
    )
    schedule_mode: Mapped[str] = mapped_column(
        String(16), default="manual", server_default="manual"
    )
    first_payment_date: Mapped[date | None] = mapped_column(Date)
    annuity_payment_minor: Mapped[int | None] = mapped_column(Integer)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class LoanScheduleItem(Base, TimestampVersionMixin):
    __tablename__ = "loan_schedule_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    principal_minor: Mapped[int | None] = mapped_column(Integer)
    interest_minor: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    paid_minor: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (CheckConstraint("amount_minor > 0"), CheckConstraint("paid_minor >= 0"))


class BudgetMonth(Base):
    __tablename__ = "budget_months"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    import_type: Mapped[str] = mapped_column(String(40), default="transactions")
    settings_json: Mapped[str] = mapped_column(Text)
    rows_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="previewed")
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(160), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
