from __future__ import annotations

from datetime import date as DateType, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_SAFE_INTEGER = 9_007_199_254_740_991


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class VersionedUpdate(BaseModel):
    version: int = Field(ge=1)


class SettingsOut(ORMModel):
    id: int
    currency: str
    timezone: str
    accounting_start_date: DateType
    salary_enabled: bool
    version: int


class SettingsUpdate(VersionedUpdate):
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(None, min_length=1, max_length=64)
    accounting_start_date: DateType | None = None
    salary_enabled: bool | None = None


class PrivateUserCreate(BaseModel):
    username: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    password: str = Field(min_length=12, max_length=512)


class PrivateUserOut(ORMModel):
    id: int
    username: str
    is_admin: bool
    active: bool


class PrivateUserStatus(BaseModel):
    active: bool


class PrivateUserPassword(BaseModel):
    password: str = Field(min_length=12, max_length=512)


MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class SalaryRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    gross_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    advance_share_bps: int = Field(gt=0, lt=10_000)
    advance_day: int = Field(ge=16, le=31)
    salary_day: int = Field(ge=1, le=15)
    start_month: str = Field(pattern=MONTH_PATTERN)
    end_month: str | None = Field(None, pattern=MONTH_PATTERN)
    initial_tax_base_minor: int = Field(default=0, ge=0, le=MAX_SAFE_INTEGER)
    initial_tax_year: int | None = Field(None, ge=2025, le=2100)
    account_id: int | None = Field(None, ge=1)
    category_id: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def valid_period(self) -> "SalaryRuleCreate":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Employer name is required")
        if not 2025 <= int(self.start_month[:4]) <= 2100:
            raise ValueError("Salary start year must be between 2025 and 2100")
        if self.end_month and not 2025 <= int(self.end_month[:4]) <= 2100:
            raise ValueError("Salary end year must be between 2025 and 2100")
        if self.end_month and self.end_month < self.start_month:
            raise ValueError("End month precedes start month")
        if self.initial_tax_base_minor and self.initial_tax_year is None:
            raise ValueError("Initial tax year is required when tax base is set")
        if self.initial_tax_base_minor and self.initial_tax_year != int(self.start_month[:4]):
            raise ValueError("Initial tax year must equal salary start year")
        return self


class SalaryRuleUpdate(SalaryRuleCreate):
    version: int = Field(ge=1)
    archived: bool = False


class SalaryRuleOut(ORMModel):
    id: int
    name: str
    gross_minor: int
    advance_share_bps: int
    advance_day: int
    salary_day: int
    start_month: str
    end_month: str | None
    initial_tax_base_minor: int
    initial_tax_year: int | None
    account_id: int | None
    category_id: int | None
    archived: bool
    version: int


class SalaryMatchCreate(BaseModel):
    earning_month: str = Field(pattern=MONTH_PATTERN)
    component: Literal["advance", "salary"]
    transaction_id: int = Field(ge=1)
    amount_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)

    @model_validator(mode="after")
    def valid_year(self) -> "SalaryMatchCreate":
        if not 2025 <= int(self.earning_month[:4]) <= 2100:
            raise ValueError("Salary earning year must be between 2025 and 2100")
        return self


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["cash", "bank", "savings"] = "bank"
    initial_balance_minor: int = Field(ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)
    initial_balance_date: DateType


class AccountUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=120)
    type: Literal["cash", "bank", "savings"] | None = None
    archived: bool | None = None


class AccountOut(ORMModel):
    id: int
    name: str
    type: str
    initial_balance_minor: int
    initial_balance_date: DateType
    archived: bool
    version: int
    current_balance_minor: int | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["income", "expense"] = "expense"
    color: str | None = Field(None, max_length=16)
    sort_order: int = 0
    monthly_estimate: bool = False

    @model_validator(mode="after")
    def estimate_requires_expense(self) -> "CategoryCreate":
        if self.monthly_estimate and self.kind != "expense":
            raise ValueError("monthly estimate is available only for expense categories")
        return self


class CategoryUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=120)
    color: str | None = Field(None, max_length=16)
    sort_order: int | None = None
    archived: bool | None = None
    monthly_estimate: bool | None = None


class CategoryOut(ORMModel):
    id: int
    name: str
    kind: str
    color: str | None
    sort_order: int
    archived: bool
    monthly_estimate: bool
    version: int


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(None, max_length=16)


class TagUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=80)
    color: str | None = Field(None, max_length=16)
    archived: bool | None = None


class TagOut(ORMModel):
    id: int
    name: str
    color: str | None
    archived: bool
    version: int


class TransactionCreate(BaseModel):
    type: Literal["income", "expense", "refund", "adjustment"]
    amount_minor: int = Field(ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)
    date: DateType
    account_id: int
    category_id: int | None = None
    goal_id: int | None = None
    loan_id: int | None = Field(None, ge=1)
    prepayment_strategy: Literal["reduce_term", "reduce_payment"] | None = None
    description: str = Field(default="", max_length=300)
    comment: str | None = Field(None, max_length=4000)
    tag_ids: list[int] = Field(default_factory=list)
    external_source: str | None = Field(None, max_length=80)
    external_id: str | None = Field(None, max_length=160)

    @model_validator(mode="after")
    def adjustment_comment(self) -> "TransactionCreate":
        if self.type == "adjustment":
            if self.amount_minor == 0:
                raise ValueError("balance adjustment cannot be zero")
            if not (self.comment or "").strip():
                raise ValueError("comment is required for balance adjustment")
        elif self.amount_minor <= 0:
            raise ValueError("transaction amount must be positive")
        return self


class TransactionUpdate(VersionedUpdate):
    amount_minor: int | None = Field(None, ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)
    date: DateType | None = None
    category_id: int | None = None
    description: str | None = Field(None, max_length=300)
    comment: str | None = Field(None, max_length=4000)
    tag_ids: list[int] | None = None

    @model_validator(mode="after")
    def nonzero_amount(self) -> "TransactionUpdate":
        if self.amount_minor == 0:
            raise ValueError("transaction amount cannot be zero")
        return self


class TransactionOut(ORMModel):
    id: int
    type: str
    amount_minor: int
    date: DateType
    account_id: int
    category_id: int | None
    goal_id: int | None
    loan_id: int | None
    principal_component_minor: int | None
    interest_component_minor: int | None
    prepayment_strategy: str | None
    loan_balance_applied: bool | None
    description: str
    comment: str | None
    external_source: str | None
    external_id: str | None
    version: int
    tags: list[TagOut] = []
    matched_plan_item_id: int | None = None
    matched_occurrence_month: str | None = None
    matched_amount_minor: int | None = None
    match_completed: bool | None = None
    matched_salary_rule_id: int | None = None
    matched_salary_earning_month: str | None = None
    matched_salary_component: str | None = None


class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    date: DateType
    comment: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def distinct_accounts(self) -> "TransferCreate":
        if self.from_account_id == self.to_account_id:
            raise ValueError("transfer accounts must differ")
        return self


class TransferUpdate(VersionedUpdate):
    from_account_id: int | None = Field(None, ge=1)
    to_account_id: int | None = Field(None, ge=1)
    amount_minor: int | None = Field(None, gt=0, le=MAX_SAFE_INTEGER)
    date: DateType | None = None
    comment: str | None = Field(None, max_length=4000)


class TransferOut(ORMModel):
    id: int
    from_account_id: int
    to_account_id: int
    amount_minor: int
    date: DateType
    comment: str | None
    version: int


class PlanItemCreate(BaseModel):
    kind: Literal["income", "expense"]
    title: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    date: DateType | None = None
    month: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    recurrence: Literal["none", "monthly", "yearly"] = "none"
    start_date: DateType | None = None
    end_date: DateType | None = None
    certainty: Literal["confirmed", "possible"] = "confirmed"
    account_id: int | None = None
    category_id: int | None = None
    goal_id: int | None = None
    loan_id: int | None = Field(None, ge=1)
    funding_source: Literal["free", "goal"] = "free"
    required: bool = False
    comment: str | None = Field(None, max_length=4000)
    tag_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_schedule(self) -> "PlanItemCreate":
        if self.recurrence == "none" and not (self.date or self.month):
            raise ValueError("one-time plan item requires date or month")
        if self.recurrence != "none" and not (self.start_date or self.date):
            raise ValueError("recurring plan item requires start_date or date")
        if self.funding_source == "goal" and not self.goal_id:
            raise ValueError("goal funding requires goal_id")
        if self.loan_id and (self.kind != "expense" or self.goal_id):
            raise ValueError("loan payment must be an expense outside goals")
        return self


class PlanItemUpdate(VersionedUpdate):
    title: str | None = Field(None, min_length=1, max_length=200)
    amount_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    end_date: DateType | None = None
    certainty: Literal["confirmed", "possible"] | None = None
    status: Literal["planned", "fulfilled", "cancelled"] | None = None
    account_id: int | None = None
    category_id: int | None = None
    loan_id: int | None = Field(None, ge=1)
    comment: str | None = Field(None, max_length=4000)
    tag_ids: list[int] | None = None


class PlanItemOut(ORMModel):
    id: int
    kind: str
    title: str
    amount_minor: int
    date: DateType | None
    month: str | None
    recurrence: str
    start_date: DateType | None
    end_date: DateType | None
    certainty: str
    status: str
    account_id: int | None
    category_id: int | None
    goal_id: int | None
    loan_id: int | None
    funding_source: str
    required: bool
    comment: str | None
    version: int
    tags: list[TagOut] = []


class OverrideInput(BaseModel):
    amount_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    cancelled: bool = False
    moved_date: DateType | None = None
    version: int | None = Field(None, ge=1)


class MatchInput(BaseModel):
    transaction_id: int
    occurrence_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    amount_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    completed: bool = False


class BudgetLimitCreate(BaseModel):
    category_id: int
    amount_minor: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    start_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_month: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def validate_range(self) -> "BudgetLimitCreate":
        if self.end_month and self.end_month < self.start_month:
            raise ValueError("end_month cannot precede start_month")
        return self


class BudgetLimitOut(ORMModel):
    id: int
    category_id: int
    amount_minor: int
    start_month: str
    end_month: str | None
    version: int


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    target_amount_minor: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    target_date: DateType | None = None
    initial_reserved_minor: int = Field(default=0, ge=0, le=MAX_SAFE_INTEGER)
    priority: int = 0
    color: str | None = Field(None, max_length=16)


class GoalUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=160)
    target_amount_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    target_date: DateType | None = None
    priority: int | None = None
    color: str | None = Field(None, max_length=16)
    status: Literal["active", "completed", "archived"] | None = None
    archived: bool | None = None
    reserve_disposition: Literal["keep", "release"] | None = None
    reserve_date: DateType | None = None


class GoalOut(ORMModel):
    id: int
    name: str
    target_amount_minor: int
    target_date: DateType | None
    initial_reserved_minor: int
    priority: int
    color: str | None
    status: str
    archived: bool
    version: int
    reserved_minor: int | None = None
    remaining_need_minor: int | None = None
    recommended_contribution_minor: int | None = None
    recommendation_status: str | None = None


class GoalMovementCreate(BaseModel):
    kind: Literal["allocation", "release", "expense", "refund"]
    amount_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    date: DateType
    account_id: int | None = None
    category_id: int | None = None
    description: str = Field(default="", max_length=300)
    comment: str | None = Field(None, max_length=4000)
    allow_allocate_shortfall: bool = False


class GoalMovementOut(ORMModel):
    id: int
    goal_id: int
    kind: str
    amount_minor: int
    date: DateType
    transaction_id: int | None
    comment: str | None
    created_at: datetime


class LoanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    creditor: str | None = Field(None, max_length=160)
    principal_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    principal_as_of: DateType | None = None
    annual_rate_bps: int | None = Field(None, ge=0, le=100_000)
    interest_method: Literal["simple", "compound"] = "simple"
    schedule_mode: Literal["manual", "auto"] = "manual"
    first_payment_date: DateType | None = None
    account_id: int | None = None
    start_date: DateType | None = None
    end_date: DateType | None = None
    comment: str | None = Field(None, max_length=4000)


class LoanUpdate(VersionedUpdate):
    name: str | None = Field(None, min_length=1, max_length=160)
    creditor: str | None = Field(None, max_length=160)
    principal_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    principal_as_of: DateType | None = None
    annual_rate_bps: int | None = Field(None, ge=0, le=100_000)
    interest_method: Literal["simple", "compound"] | None = None
    schedule_mode: Literal["manual", "auto"] | None = None
    first_payment_date: DateType | None = None
    account_id: int | None = Field(None, ge=1)
    start_date: DateType | None = None
    end_date: DateType | None = None
    comment: str | None = Field(None, max_length=4000)
    archived: bool | None = None


class LoanOut(ORMModel):
    id: int
    name: str
    creditor: str | None
    principal_minor: int | None
    principal_as_of: DateType | None
    annual_rate_bps: int | None
    interest_method: str
    schedule_mode: str
    first_payment_date: DateType | None
    annuity_payment_minor: int | None
    account_id: int | None
    start_date: DateType | None
    end_date: DateType | None
    comment: str | None
    archived: bool
    version: int


class LoanScheduleCreate(BaseModel):
    due_date: DateType
    amount_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    principal_minor: int | None = Field(None, ge=0)
    interest_minor: int | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_breakdown(self) -> "LoanScheduleCreate":
        components = (self.principal_minor or 0) + (self.interest_minor or 0)
        if components > self.amount_minor:
            raise ValueError("principal and interest cannot exceed the payment amount")
        return self


class LoanScheduleUpdate(VersionedUpdate):
    due_date: DateType | None = None
    amount_minor: int | None = Field(None, gt=0, le=MAX_SAFE_INTEGER)
    principal_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    interest_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    status: Literal["planned", "cancelled"] | None = None


class LoanPaymentCreate(BaseModel):
    amount_minor: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    principal_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    interest_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    date: DateType
    account_id: int | None = None
    category_id: int | None = None
    completed: bool = False
    comment: str | None = Field(None, max_length=4000)

    @model_validator(mode="after")
    def validate_breakdown(self) -> "LoanPaymentCreate":
        if (self.principal_minor or 0) + (self.interest_minor or 0) > self.amount_minor:
            raise ValueError("principal and interest cannot exceed the actual payment")
        return self


class LoanTransactionLink(BaseModel):
    principal_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    interest_minor: int | None = Field(None, ge=0, le=MAX_SAFE_INTEGER)
    already_reflected_in_balance: bool = True
    prepayment_strategy: Literal["reduce_term", "reduce_payment"] | None = None


class LoanScheduleOut(ORMModel):
    id: int
    loan_id: int
    due_date: DateType
    amount_minor: int
    principal_minor: int | None
    interest_minor: int | None
    status: str
    paid_minor: int
    version: int


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class Paginated(BaseModel):
    items: list
    total: int
    limit: int
    offset: int
