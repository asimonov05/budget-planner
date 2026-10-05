from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from .db import Base


MONEY_TYPE = BigInteger().with_variant(Integer, "sqlite")


def transfer_target_default(context) -> int:
    return context.get_current_parameters().get("amount_minor") or 0


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


def tenant_default(context) -> int:
    user_id = context.connection.info.get("tenant_user_id")
    if isinstance(user_id, int) and user_id > 0:
        return user_id
    if context.dialect.name == "sqlite":
        return 1  # Legacy unit-test fixture; PostgreSQL always requires verified scope.
    raise RuntimeError("Tenant context is required for financial inserts")


class TenantMixin:
    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey("users.id"), nullable=False, index=True, default=tenant_default)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
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


class ReleaseNote(Base):
    __tablename__ = "release_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_version: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(String(300), default="", server_default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="ck_release_notes_status"),
        UniqueConstraint("release_version", name="uq_release_notes_release_version"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    release_note_id: Mapped[int | None] = mapped_column(
        ForeignKey("release_notes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("kind IN ('message', 'release')", name="ck_notifications_kind"),
    )


class AppSettings(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    currency_display_mode: Mapped[str] = mapped_column(
        String(16), default="separate", server_default="separate"
    )
    display_rates_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    accounting_start_date: Mapped[date] = mapped_column(Date, default=date.today)
    salary_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_app_settings_user_id"),
        CheckConstraint(
            "currency_display_mode IN ('separate', 'converted')",
            name="ck_app_settings_currency_display_mode",
        ),
    )


class Account(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(24), default="bank")
    currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")
    initial_balance_minor: Mapped[int] = mapped_column(MONEY_TYPE, default=0)
    initial_balance_date: Mapped[date] = mapped_column(Date)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Category(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="expense")
    color: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_estimate: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_categories_user_name"),)


class Tag(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(16))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_name"),)


class Goal(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    target_amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    target_date: Mapped[date | None] = mapped_column(Date)
    initial_reserved_minor: Mapped[int] = mapped_column(MONEY_TYPE, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="active")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("target_amount_minor >= 0"),
        CheckConstraint("initial_reserved_minor >= 0"),
    )


class Transaction(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    merchant_currency: Mapped[str | None] = mapped_column(String(3))
    merchant_amount_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    merchant_exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    date: Mapped[date] = mapped_column(Date, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), index=True)
    loan_id: Mapped[int | None] = mapped_column(ForeignKey("loans.id"), index=True)
    principal_component_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    interest_component_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    prepayment_strategy: Mapped[str | None] = mapped_column(String(24))
    loan_balance_applied: Mapped[bool | None] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(String(300), default="")
    comment: Mapped[str | None] = mapped_column(Text)
    external_source: Mapped[str | None] = mapped_column(String(80))
    external_id: Mapped[str | None] = mapped_column(String(160))
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    tags: Mapped[list[Tag]] = relationship(
        secondary="transaction_tags",
        primaryjoin="and_(Transaction.id == TransactionTag.transaction_id, Transaction.user_id == TransactionTag.user_id)",
        secondaryjoin="and_(Tag.id == TransactionTag.tag_id, Tag.user_id == TransactionTag.user_id)",
        lazy="selectin",
    )
    __table_args__ = (
        CheckConstraint(
            "(type = 'adjustment' AND amount_minor <> 0) "
            "OR (type <> 'adjustment' AND amount_minor > 0)"
        ),
        CheckConstraint(
            "merchant_exchange_rate IS NULL OR merchant_exchange_rate > 0",
            name="ck_transactions_merchant_rate_positive",
        ),
        UniqueConstraint(
            "user_id", "external_source", "account_id", "external_id", name="uq_transaction_external"
        ),
    )


class TransactionTag(Base, TenantMixin):
    __tablename__ = "transaction_tags"
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class Transfer(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    to_amount_minor: Mapped[int] = mapped_column(MONEY_TYPE, default=transfer_target_default)
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(24, 12), default=Decimal(1), server_default="1"
    )
    date: Mapped[date] = mapped_column(Date, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("amount_minor > 0"),
        CheckConstraint("to_amount_minor > 0", name="ck_transfers_to_amount_positive"),
        CheckConstraint("exchange_rate > 0", name="ck_transfers_rate_positive"),
        CheckConstraint("from_account_id <> to_account_id"),
    )


class PlanItem(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "plan_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", server_default="RUB")
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
    tags: Mapped[list[Tag]] = relationship(
        secondary="plan_item_tags",
        primaryjoin="and_(PlanItem.id == PlanItemTag.plan_item_id, PlanItem.user_id == PlanItemTag.user_id)",
        secondaryjoin="and_(Tag.id == PlanItemTag.tag_id, Tag.user_id == PlanItemTag.user_id)",
        lazy="selectin",
    )
    __table_args__ = (CheckConstraint("amount_minor >= 0"),)


class PlanItemTag(Base, TenantMixin):
    __tablename__ = "plan_item_tags"
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class PlanOverride(Base, TenantMixin):
    __tablename__ = "plan_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_items.id", ondelete="CASCADE"), index=True
    )
    month: Mapped[str] = mapped_column(String(7))
    amount_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    moved_date: Mapped[date | None] = mapped_column(Date)
    __table_args__ = (
        UniqueConstraint("user_id", "plan_item_id", "month", name="uq_plan_overrides_user_plan_month"),
    )


class PlanMatch(Base, TenantMixin):
    __tablename__ = "plan_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_item_id: Mapped[int] = mapped_column(
        ForeignKey("plan_items.id", ondelete="CASCADE"), index=True
    )
    occurrence_month: Mapped[str] = mapped_column(String(7), index=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE")
    )
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("user_id", "transaction_id", name="uq_plan_matches_user_transaction"),
    )


class SalaryRule(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "salary_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    gross_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    advance_share_bps: Mapped[int] = mapped_column(Integer, default=4_000)
    advance_day: Mapped[int] = mapped_column(Integer, default=25)
    salary_day: Mapped[int] = mapped_column(Integer, default=10)
    start_month: Mapped[str] = mapped_column(String(7))
    end_month: Mapped[str | None] = mapped_column(String(7))
    initial_tax_base_minor: Mapped[int] = mapped_column(MONEY_TYPE, default=0)
    initial_tax_year: Mapped[int | None] = mapped_column(Integer)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("gross_minor > 0"),
        CheckConstraint("advance_share_bps > 0 AND advance_share_bps < 10000"),
        CheckConstraint("advance_day BETWEEN 16 AND 31"),
        CheckConstraint("salary_day BETWEEN 1 AND 15"),
        CheckConstraint("initial_tax_base_minor >= 0"),
    )


class SalaryMatch(Base, TenantMixin):
    __tablename__ = "salary_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    salary_rule_id: Mapped[int] = mapped_column(
        ForeignKey("salary_rules.id", ondelete="CASCADE"), index=True
    )
    earning_month: Mapped[str] = mapped_column(String(7))
    component: Mapped[str] = mapped_column(String(16))
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    __table_args__ = (
        CheckConstraint("amount_minor > 0"),
        UniqueConstraint("user_id", "transaction_id", name="uq_salary_matches_user_transaction"),
    )


class BudgetLimit(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "budget_limits"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    start_month: Mapped[str] = mapped_column(String(7))
    end_month: Mapped[str | None] = mapped_column(String(7))
    __table_args__ = (CheckConstraint("amount_minor >= 0"),)


class BudgetLimitOverride(Base, TenantMixin):
    __tablename__ = "budget_limit_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_limit_id: Mapped[int] = mapped_column(ForeignKey("budget_limits.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    __table_args__ = (
        UniqueConstraint("user_id", "budget_limit_id", "month", name="uq_budget_limit_overrides_user_limit_month"),
    )


class GoalReserveMovement(Base, TenantMixin):
    __tablename__ = "goal_reserve_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    date: Mapped[date] = mapped_column(Date, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        CheckConstraint("amount_minor > 0"),
        UniqueConstraint("user_id", "transaction_id", name="uq_goal_movements_user_transaction"),
    )


class Loan(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "loans"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    creditor: Mapped[str | None] = mapped_column(String(160))
    principal_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    principal_as_of: Mapped[date | None] = mapped_column(Date)
    annual_rate_bps: Mapped[int | None] = mapped_column(Integer)
    interest_method: Mapped[str] = mapped_column(
        String(16), default="simple", server_default="simple"
    )
    schedule_mode: Mapped[str] = mapped_column(
        String(16), default="manual", server_default="manual"
    )
    first_payment_date: Mapped[date | None] = mapped_column(Date)
    annuity_payment_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class LoanScheduleItem(Base, TenantMixin, TimestampVersionMixin):
    __tablename__ = "loan_schedule_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount_minor: Mapped[int] = mapped_column(MONEY_TYPE)
    principal_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    interest_minor: Mapped[int | None] = mapped_column(MONEY_TYPE)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    paid_minor: Mapped[int] = mapped_column(MONEY_TYPE, default=0)
    __table_args__ = (CheckConstraint("amount_minor > 0"), CheckConstraint("paid_minor >= 0"))


class BudgetMonth(Base, TenantMixin):
    __tablename__ = "budget_months"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, default=tenant_default)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)


class ImportBatch(Base, TenantMixin):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    import_type: Mapped[str] = mapped_column(String(40), default="transactions")
    settings_json: Mapped[str] = mapped_column(Text)
    rows_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="previewed")
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_import_batches_user_fingerprint"),)


class IdempotencyRecord(Base, TenantMixin):
    __tablename__ = "idempotency_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_records_user_key"),)


class AuditLog(Base, TenantMixin):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


TENANT_MODELS = (
    Notification, AppSettings, Account, Category, Tag, Goal, Transaction, TransactionTag,
    Transfer, PlanItem, PlanItemTag, PlanOverride, PlanMatch, SalaryRule,
    SalaryMatch, BudgetLimit, BudgetLimitOverride, GoalReserveMovement, Loan,
    LoanScheduleItem, BudgetMonth, ImportBatch, IdempotencyRecord, AuditLog,
)
TENANT_TABLES = {model.__table__.name for model in TENANT_MODELS}
for model in TENANT_MODELS:
    table = model.__table__
    if "id" in table.c:
        table.append_constraint(
            UniqueConstraint("user_id", "id", name=f"uq_{table.name}_user_id_id")
        )
    for column in list(table.c):
        if column.name == "user_id":
            continue
        for foreign_key in list(column.foreign_keys):
            parent = foreign_key.column.table
            if parent.name in TENANT_TABLES and foreign_key.column.name != "user_id":
                table.append_constraint(ForeignKeyConstraint(
                    ["user_id", column.name],
                    [f"{parent.name}.user_id", f"{parent.name}.{foreign_key.column.name}"],
                    name=f"fk_{table.name}_{column.name}_tenant",
                    ondelete=foreign_key.ondelete,
                ))
