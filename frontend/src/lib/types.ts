export type ID = string | number

export interface User { id?: ID; username: string; display_name?: string; debug_admin_enabled?: boolean }
export interface Account { id: ID; name: string; type?: string; balance_minor?: number; current_balance_minor?: number; initial_balance_minor?: number; initial_balance_date?: string; archived?: boolean; version?: number }
export interface Category { id: ID; name: string; color?: string; kind?: 'income' | 'expense'; type?: 'income' | 'expense'; archived?: boolean; version?: number }
export interface Tag { id: ID; name: string; color?: string; archived?: boolean; version?: number }
export interface Income {
  id: ID; name: string; amount_minor: number; date?: string; month?: string; account_id?: ID;
  category_id?: ID; tags?: Tag[]; recurring?: boolean; certainty?: 'confirmed' | 'possible'; comment?: string
}
export interface Payment {
  id: ID; name: string; amount_minor: number; due_date?: string; month?: string; account_id?: ID;
  category_id?: ID; mandatory?: boolean; recurring?: string; status?: string; comment?: string
}
export interface Transaction {
  id: ID; date: string; description?: string; amount_minor: number; type: string; account_id?: ID;
  account_name?: string; category_name?: string; tags?: Tag[]; comment?: string; external_source?: string;
  loan_id?: ID | null; principal_component_minor?: number | null; interest_component_minor?: number | null;
  prepayment_strategy?: 'reduce_term' | 'reduce_payment' | null;
  loan_balance_applied?: boolean | null;
  matched_plan_item_id?: ID | null; matched_occurrence_month?: string | null;
  matched_amount_minor?: number | null; match_completed?: boolean | null; category_id?: ID | null; version?: number
}
export interface Transfer {
  id: ID; from_account_id: ID; to_account_id: ID; amount_minor: number; date: string; comment?: string; version?: number
}
export interface Loan {
  id: ID; name: string; creditor?: string; principal_minor?: number; principal_as_of?: string; account_id?: ID;
  start_date?: string; end_date?: string; comment?: string; archived?: boolean; version?: number;
  annual_rate_bps?: number | null; interest_method?: 'simple' | 'compound'; schedule_mode?: 'manual' | 'auto';
  first_payment_date?: string | null; annuity_payment_minor?: number | null;
  projected_interest_minor?: number; projected_payoff_date?: string | null; schedule_remaining_minor?: number;
  paid_total_minor?: number; paid_principal_minor?: number; paid_interest_minor?: number; paid_unclassified_minor?: number;
  remaining_payments_minor?: number; next_payment_date?: string; next_payment_minor?: number; status?: string
}
export interface LoanScheduleItem {
  id: ID; loan_id: ID; due_date: string; amount_minor: number; principal_minor?: number | null;
  interest_minor?: number | null; status: string; paid_minor: number; remaining_minor?: number;
  overdue?: boolean; version?: number
}
export interface Goal { id: ID; name: string; target_amount_minor?: number; target_minor?: number; initial_reserved_minor?: number; reserved_minor: number; remaining_need_minor?: number; target_date?: string; deadline?: string; priority?: number; color?: string; status?: string; recommended_contribution_minor?: number }

export interface Dashboard {
  month: string; currency?: string; total_balance_minor: number; reserved_minor: number; free_minor: number;
  forecast_end_minor: number; planned_income_minor: number; actual_income_minor: number;
  planned_expense_minor: number; actual_expense_minor: number; planned_goal_contribution_minor?: number;
  accounts: Account[]; upcoming_payments: Payment[]; warnings: Array<string | { message: string }>; is_daily_forecast_complete?: boolean
}
export interface PlanRow { id: ID; label: string; kind: string; values: Record<string, number>; editable?: boolean }
export interface PlanResponse { start_month: string; months: string[]; rows: PlanRow[]; totals?: Record<string, { income_minor?: number; expense_minor?: number; end_balance_minor?: number }> }
export interface AnalyticsPoint { month: string; income_minor: number; expense_minor: number; planned_income_minor?: number; planned_expense_minor?: number; balance_minor?: number; reserved_minor?: number }
export interface Analytics { timeline: AnalyticsPoint[]; categories: Array<{ name: string; amount_minor: number; color?: string }> }
export interface ListResponse<T> { items: T[]; total?: number; page?: number; pages?: number }
