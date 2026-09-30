"""Move private budgets into one user-scoped PostgreSQL database."""

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "accounts", "app_settings", "audit_logs", "budget_months", "categories",
    "goals", "idempotency_records", "import_batches", "tags", "budget_limits",
    "loans", "salary_rules", "transfers", "budget_limit_overrides",
    "loan_schedule_items", "plan_items", "transactions", "goal_reserve_movements",
    "plan_item_tags", "plan_matches", "plan_overrides", "salary_matches",
    "transaction_tags",
)
ID_TABLES = tuple(
    table for table in TENANT_TABLES
    if table not in ("budget_months", "plan_item_tags", "transaction_tags")
)
TENANT_FOREIGN_KEYS = (
    ("budget_limits", "category_id", "categories", None),
    ("loans", "account_id", "accounts", None),
    ("salary_rules", "account_id", "accounts", None),
    ("salary_rules", "category_id", "categories", None),
    ("transfers", "from_account_id", "accounts", None),
    ("transfers", "to_account_id", "accounts", None),
    ("budget_limit_overrides", "budget_limit_id", "budget_limits", "CASCADE"),
    ("loan_schedule_items", "loan_id", "loans", "CASCADE"),
    ("plan_items", "goal_id", "goals", None),
    ("plan_items", "account_id", "accounts", None),
    ("plan_items", "loan_id", "loans", None),
    ("plan_items", "category_id", "categories", None),
    ("transactions", "category_id", "categories", None),
    ("transactions", "import_batch_id", "import_batches", None),
    ("transactions", "goal_id", "goals", None),
    ("transactions", "account_id", "accounts", None),
    ("transactions", "loan_id", "loans", None),
    ("goal_reserve_movements", "goal_id", "goals", None),
    ("goal_reserve_movements", "transaction_id", "transactions", None),
    ("plan_item_tags", "tag_id", "tags", None),
    ("plan_item_tags", "plan_item_id", "plan_items", "CASCADE"),
    ("plan_matches", "plan_item_id", "plan_items", "CASCADE"),
    ("plan_matches", "transaction_id", "transactions", "CASCADE"),
    ("plan_overrides", "plan_item_id", "plan_items", "CASCADE"),
    ("salary_matches", "transaction_id", "transactions", None),
    ("salary_matches", "salary_rule_id", "salary_rules", "CASCADE"),
    ("transaction_tags", "transaction_id", "transactions", "CASCADE"),
    ("transaction_tags", "tag_id", "tags", None),
)
OLD_UNIQUES = (
    ("categories", "categories_name_key"),
    ("tags", "tags_name_key"),
    ("idempotency_records", "idempotency_records_key_key"),
    ("import_batches", "import_batches_fingerprint_key"),
    ("transactions", "uq_transaction_external"),
    ("budget_limit_overrides", "budget_limit_overrides_budget_limit_id_month_key"),
    ("goal_reserve_movements", "goal_reserve_movements_transaction_id_key"),
    ("plan_matches", "plan_matches_transaction_id_key"),
    ("plan_overrides", "plan_overrides_plan_item_id_month_key"),
    ("salary_matches", "salary_matches_transaction_id_key"),
)
NEW_UNIQUES = (
    ("app_settings", "uq_app_settings_user_id", ("user_id",)),
    ("categories", "uq_categories_user_name", ("user_id", "name")),
    ("tags", "uq_tags_user_name", ("user_id", "name")),
    ("idempotency_records", "uq_idempotency_records_user_key", ("user_id", "key")),
    ("import_batches", "uq_import_batches_user_fingerprint", ("user_id", "fingerprint")),
    ("transactions", "uq_transaction_external", ("user_id", "external_source", "account_id", "external_id")),
    ("budget_limit_overrides", "uq_budget_limit_overrides_user_limit_month", ("user_id", "budget_limit_id", "month")),
    ("goal_reserve_movements", "uq_goal_movements_user_transaction", ("user_id", "transaction_id")),
    ("plan_matches", "uq_plan_matches_user_transaction", ("user_id", "transaction_id")),
    ("plan_overrides", "uq_plan_overrides_user_plan_month", ("user_id", "plan_item_id", "month")),
    ("salary_matches", "uq_salary_matches_user_transaction", ("user_id", "transaction_id")),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite remains only a temporary test fixture (TD-003).
    op.drop_index("ix_users_budget_database", table_name="users")
    op.drop_column("users", "budget_database")
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("user_id", sa.Integer(), nullable=True))
        op.execute(f"UPDATE {table} SET user_id = 1")
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(f"fk_{table}_user_id", table, "users", ["user_id"], ["id"])
        if table != "budget_months":
            op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    op.drop_constraint("budget_months_pkey", "budget_months", type_="primary")
    op.create_primary_key("budget_months_pkey", "budget_months", ["user_id", "month"])
    for table, constraint in OLD_UNIQUES:
        op.drop_constraint(constraint, table, type_="unique")
    for table, constraint, columns in NEW_UNIQUES:
        op.create_unique_constraint(constraint, table, list(columns))
    for table in ID_TABLES:
        op.create_unique_constraint(f"uq_{table}_user_id_id", table, ["user_id", "id"])
    for table, column, parent, ondelete in TENANT_FOREIGN_KEYS:
        op.create_foreign_key(
            f"fk_{table}_{column}_tenant", table, parent,
            ["user_id", column], ["user_id", "id"], ondelete=ondelete,
        )
    predicate = "user_id = NULLIF(current_setting('app.current_user_id', true), '')::integer"
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def downgrade() -> None:
    raise RuntimeError("Downgrading tenant isolation would expose or merge user data")
