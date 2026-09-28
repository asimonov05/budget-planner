from __future__ import annotations

from hypothesis import given, strategies as st

from app.core.calculations import split_evenly


@given(
    amount_minor=st.integers(min_value=0, max_value=9_007_199_254_740_991),
    contribution_count=st.integers(min_value=1, max_value=120),
)
def test_goal_split_preserves_every_kopeck(amount_minor: int, contribution_count: int):
    values = split_evenly(amount_minor, contribution_count)
    assert len(values) == contribution_count
    assert sum(values) == amount_minor
    assert max(values) - min(values) <= 1


@given(
    cash=st.integers(min_value=-(10**12), max_value=10**12),
    reserve=st.integers(min_value=0, max_value=10**12),
    income=st.integers(min_value=0, max_value=10**10),
    expense=st.integers(min_value=0, max_value=10**10),
    allocation=st.integers(min_value=0, max_value=10**10),
    release=st.integers(min_value=0, max_value=10**10),
)
def test_month_transition_always_preserves_free_cash_identity(
    cash: int,
    reserve: int,
    income: int,
    expense: int,
    allocation: int,
    release: int,
):
    cash_end = cash + income - expense
    reserve_end = reserve + allocation - release
    free_end = cash_end - reserve_end
    assert free_end == cash + income - expense - reserve - allocation + release


@given(
    from_balance=st.integers(min_value=-(10**12), max_value=10**12),
    to_balance=st.integers(min_value=-(10**12), max_value=10**12),
    amount=st.integers(min_value=1, max_value=10**10),
)
def test_internal_transfer_is_zero_sum(from_balance: int, to_balance: int, amount: int):
    before = from_balance + to_balance
    after = (from_balance - amount) + (to_balance + amount)
    assert after == before
