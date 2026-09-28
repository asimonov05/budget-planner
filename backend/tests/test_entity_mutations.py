from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.models import (
    Account,
    AuditLog,
    BudgetLimit,
    Category,
    Goal,
    GoalReserveMovement,
    Loan,
    LoanScheduleItem,
    PlanItem,
    PlanItemTag,
    Tag,
    Transaction,
    TransactionTag,
    Transfer,
)


def assert_conflict(response, message_fragment: str) -> None:
    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["code"] == "http_error"
    assert message_fragment.lower() in payload["message"].lower()


def test_unused_catalog_entities_can_be_versioned_hard_deleted_and_are_audited(client, auth, db):
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Временный",
            "type": "bank",
            "initial_balance_minor": 0,
            "initial_balance_date": "2026-04-01",
        },
        headers=auth,
    ).json()
    category = client.post(
        "/api/v1/categories",
        json={"name": "Временная", "kind": "expense"},
        headers=auth,
    ).json()
    tag = client.post("/api/v1/tags", json={"name": "временный"}, headers=auth).json()

    stale = client.delete(
        f"/api/v1/accounts/{account['id']}",
        params={"version": account["version"] + 1},
        headers=auth,
    )
    assert_conflict(stale, "version conflict")

    for resource, item in (("accounts", account), ("categories", category), ("tags", tag)):
        response = client.delete(
            f"/api/v1/{resource}/{item['id']}",
            params={"version": item["version"]},
            headers=auth,
        )
        assert response.status_code == 204 and response.content == b""

    db.expire_all()
    assert db.get(Account, account["id"]) is None
    assert db.get(Category, category["id"]) is None
    assert db.get(Tag, tag["id"]) is None
    assert (
        db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "delete"))
        == 3
    )


def test_catalog_entities_with_every_supported_reference_must_be_archived(client, auth, db):
    accounts = [
        Account(
            name=f"Счёт {index}",
            initial_balance_minor=0,
            initial_balance_date=date(2026, 1, 1),
        )
        for index in range(4)
    ]
    categories = [Category(name=f"Категория {index}") for index in range(3)]
    transaction_tag = Tag(name="в факте")
    plan_tag = Tag(name="в плане")
    db.add_all([*accounts, *categories, transaction_tag, plan_tag])
    db.flush()
    transaction = Transaction(
        type="expense",
        amount_minor=100,
        date=date(2026, 2, 1),
        account_id=accounts[0].id,
        category_id=categories[0].id,
    )
    transfer = Transfer(
        from_account_id=accounts[1].id,
        to_account_id=accounts[0].id,
        amount_minor=100,
        date=date(2026, 2, 1),
    )
    plan = PlanItem(
        kind="expense",
        title="План",
        amount_minor=100,
        date=date(2026, 3, 1),
        account_id=accounts[2].id,
        category_id=categories[1].id,
    )
    loan = Loan(name="Кредит", account_id=accounts[3].id)
    limit = BudgetLimit(
        category_id=categories[2].id,
        amount_minor=100,
        start_month="2026-01",
    )
    db.add_all([transaction, transfer, plan, loan, limit])
    db.flush()
    db.add_all(
        [
            TransactionTag(transaction_id=transaction.id, tag_id=transaction_tag.id),
            PlanItemTag(plan_item_id=plan.id, tag_id=plan_tag.id),
        ]
    )
    db.commit()

    for value in accounts:
        response = client.delete(
            f"/api/v1/accounts/{value.id}",
            params={"version": value.version},
            headers=auth,
        )
        assert_conflict(response, "archive")
    for value in categories:
        response = client.delete(
            f"/api/v1/categories/{value.id}",
            params={"version": value.version},
            headers=auth,
        )
        assert_conflict(response, "archive")
    for value in (transaction_tag, plan_tag):
        response = client.delete(
            f"/api/v1/tags/{value.id}",
            params={"version": value.version},
            headers=auth,
        )
        assert_conflict(response, "archive")


def test_transaction_and_transfer_edits_and_deletes_respect_history_and_closed_months(
    client, auth, account, db
):
    target = Account(
        name="Накопительный",
        initial_balance_minor=0,
        initial_balance_date=date(2026, 1, 1),
    )
    db.add(target)
    db.commit()

    transaction = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 500,
            "date": "2026-03-01",
            "account_id": account.id,
        },
        headers=auth,
    ).json()
    deleted = client.delete(
        f"/api/v1/transactions/{transaction['id']}",
        params={"version": transaction["version"]},
        headers=auth,
    )
    assert deleted.status_code == 204

    transfer = client.post(
        "/api/v1/transfers",
        json={
            "from_account_id": account.id,
            "to_account_id": target.id,
            "amount_minor": 1_000,
            "date": "2026-03-02",
        },
        headers=auth,
    ).json()
    invalid = client.patch(
        f"/api/v1/transfers/{transfer['id']}",
        json={"version": transfer["version"], "to_account_id": account.id},
        headers=auth,
    )
    assert invalid.status_code == 422
    changed = client.patch(
        f"/api/v1/transfers/{transfer['id']}",
        json={
            "version": transfer["version"],
            "amount_minor": 1_500,
            "date": "2026-04-02",
            "comment": "Перенос",
        },
        headers=auth,
    )
    assert changed.status_code == 200, changed.text
    transfer = changed.json()
    assert (transfer["amount_minor"], transfer["version"]) == (1_500, 2)

    assert client.post("/api/v1/months/2026-04/close", headers=auth).status_code == 200
    blocked_patch = client.patch(
        f"/api/v1/transfers/{transfer['id']}",
        json={"version": transfer["version"], "comment": "Нельзя"},
        headers=auth,
    )
    blocked_delete = client.delete(
        f"/api/v1/transfers/{transfer['id']}",
        params={"version": transfer["version"]},
        headers=auth,
    )
    assert_conflict(blocked_patch, "month is closed")
    assert_conflict(blocked_delete, "month is closed")

    assert client.post("/api/v1/months/2026-04/reopen", headers=auth).status_code == 200
    assert (
        client.delete(
            f"/api/v1/transfers/{transfer['id']}",
            params={"version": transfer["version"]},
            headers=auth,
        ).status_code
        == 204
    )


def test_transaction_delete_rejects_plan_goal_and_loan_links(client, auth, account, db):
    plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "План",
            "amount_minor": 500,
            "date": "2026-03-01",
        },
        headers=auth,
    ).json()
    transaction = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 500,
            "date": "2026-03-01",
            "account_id": account.id,
        },
        headers=auth,
    ).json()
    matched = client.post(
        f"/api/v1/plan-items/{plan['id']}/matches",
        json={
            "transaction_id": transaction["id"],
            "occurrence_month": "2026-03",
            "amount_minor": 500,
        },
        headers=auth,
    )
    assert matched.status_code == 201, matched.text
    assert_conflict(
        client.delete(
            f"/api/v1/transactions/{transaction['id']}",
            params={"version": transaction["version"]},
            headers=auth,
        ),
        "matched",
    )

    goal = client.post(
        "/api/v1/goals",
        json={"name": "Цель", "target_amount_minor": 10_000},
        headers=auth,
    ).json()
    movement = client.post(
        f"/api/v1/goals/{goal['id']}/allocations",
        json={
            "kind": "expense",
            "amount_minor": 100,
            "date": "2026-03-02",
            "account_id": account.id,
            "allow_allocate_shortfall": True,
        },
        headers=auth,
    )
    assert movement.status_code == 201, movement.text
    goal_transaction = db.get(Transaction, movement.json()["transaction_id"])
    assert_conflict(
        client.delete(
            f"/api/v1/transactions/{goal_transaction.id}",
            params={"version": goal_transaction.version},
            headers=auth,
        ),
        "goal-linked",
    )

    loan = client.post(
        "/api/v1/loans",
        json={"name": "Кредит", "account_id": account.id},
        headers=auth,
    ).json()
    schedule = client.post(
        f"/api/v1/loans/{loan['id']}/schedule",
        json={"due_date": "2026-03-03", "amount_minor": 500},
        headers=auth,
    ).json()
    payment = client.post(
        f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}/payments",
        json={"amount_minor": 100, "date": "2026-03-03"},
        headers=auth,
    )
    assert payment.status_code == 201, payment.text
    loan_transaction = db.get(Transaction, payment.json()["transaction_id"])
    assert_conflict(
        client.delete(
            f"/api/v1/transactions/{loan_transaction.id}",
            params={"version": loan_transaction.version},
            headers=auth,
        ),
        "loan payment",
    )


def test_plan_and_goal_safe_delete_semantics(client, auth, account, db):
    disposable_plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Удалить",
            "amount_minor": 100,
            "date": "2026-05-01",
        },
        headers=auth,
    ).json()
    assert (
        client.delete(
            f"/api/v1/plan-items/{disposable_plan['id']}",
            params={"version": disposable_plan["version"]},
            headers=auth,
        ).status_code
        == 204
    )

    closed_plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Закрытый месяц",
            "amount_minor": 100,
            "date": "2026-05-02",
        },
        headers=auth,
    ).json()
    assert client.post("/api/v1/months/2026-05/close", headers=auth).status_code == 200
    assert_conflict(
        client.delete(
            f"/api/v1/plan-items/{closed_plan['id']}",
            params={"version": closed_plan["version"]},
            headers=auth,
        ),
        "closed month",
    )

    empty_goal = client.post(
        "/api/v1/goals",
        json={"name": "Пустая", "target_amount_minor": 1_000},
        headers=auth,
    ).json()
    assert (
        client.delete(
            f"/api/v1/goals/{empty_goal['id']}",
            params={"version": empty_goal["version"]},
            headers=auth,
        ).status_code
        == 204
    )

    reserved_goal = client.post(
        "/api/v1/goals",
        json={
            "name": "С резервом",
            "target_amount_minor": 2_000,
            "initial_reserved_minor": 1_000,
        },
        headers=auth,
    ).json()
    assert_conflict(
        client.delete(
            f"/api/v1/goals/{reserved_goal['id']}",
            params={"version": reserved_goal["version"]},
            headers=auth,
        ),
        "archive",
    )

    linked_goal = Goal(name="Связанная", target_amount_minor=1_000)
    db.add(linked_goal)
    db.flush()
    db.add(
        GoalReserveMovement(
            goal_id=linked_goal.id,
            kind="allocation",
            amount_minor=100,
            date=date(2026, 6, 1),
        )
    )
    db.commit()
    assert_conflict(
        client.delete(
            f"/api/v1/goals/{linked_goal.id}",
            params={"version": linked_goal.version},
            headers=auth,
        ),
        "archive",
    )


def test_plan_patch_preserves_matched_and_closed_history(client, auth, account):
    matched_plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Сверенный план",
            "amount_minor": 1_000,
            "date": "2026-07-10",
            "account_id": account.id,
        },
        headers=auth,
    ).json()
    transaction = client.post(
        "/api/v1/transactions",
        json={
            "type": "expense",
            "amount_minor": 600,
            "date": "2026-07-10",
            "account_id": account.id,
            "description": "Факт",
        },
        headers=auth,
    ).json()
    assert (
        client.post(
            f"/api/v1/plan-items/{matched_plan['id']}/matches",
            json={
                "transaction_id": transaction["id"],
                "occurrence_month": "2026-07",
                "amount_minor": 600,
            },
            headers=auth,
        ).status_code
        == 201
    )
    assert_conflict(
        client.patch(
            f"/api/v1/plan-items/{matched_plan['id']}",
            json={"amount_minor": 500, "version": matched_plan["version"]},
            headers=auth,
        ),
        "matched transactions",
    )
    metadata_update = client.patch(
        f"/api/v1/plan-items/{matched_plan['id']}",
        json={
            "title": "Сверенный план — уточнение",
            "comment": "История не меняется",
            "version": matched_plan["version"],
        },
        headers=auth,
    )
    assert metadata_update.status_code == 200, metadata_update.text
    cancel = client.patch(
        f"/api/v1/plan-items/{matched_plan['id']}",
        json={"status": "cancelled", "version": metadata_update.json()["version"]},
        headers=auth,
    )
    assert cancel.status_code == 200, cancel.text

    closed_plan = client.post(
        "/api/v1/plan-items",
        json={
            "kind": "expense",
            "title": "Исторический план",
            "amount_minor": 2_000,
            "date": "2026-08-10",
            "account_id": account.id,
        },
        headers=auth,
    ).json()
    assert client.post("/api/v1/months/2026-08/close", headers=auth).status_code == 200
    assert_conflict(
        client.patch(
            f"/api/v1/plan-items/{closed_plan['id']}",
            json={"amount_minor": 2_500, "version": closed_plan["version"]},
            headers=auth,
        ),
        "closed month",
    )
    rename = client.patch(
        f"/api/v1/plan-items/{closed_plan['id']}",
        json={"title": "Исторический план — уточнение", "version": closed_plan["version"]},
        headers=auth,
    )
    assert rename.status_code == 200, rename.text


def test_loan_and_schedule_patch_archive_and_safe_delete_lifecycle(client, auth, account, db):
    loan = client.post(
        "/api/v1/loans",
        json={"name": "Кредит", "account_id": account.id},
        headers=auth,
    ).json()
    changed = client.patch(
        f"/api/v1/loans/{loan['id']}",
        json={
            "version": loan["version"],
            "name": "Ипотека",
            "creditor": "Банк",
            "principal_minor": 1_000_000,
            "principal_as_of": "2026-07-01",
            "start_date": "2026-01-01",
            "end_date": "2027-01-01",
        },
        headers=auth,
    )
    assert changed.status_code == 200, changed.text
    loan = changed.json()
    assert loan["name"] == "Ипотека" and loan["version"] == 2

    schedule = client.post(
        f"/api/v1/loans/{loan['id']}/schedule",
        json={
            "due_date": "2026-07-05",
            "amount_minor": 10_000,
            "principal_minor": 8_000,
            "interest_minor": 2_000,
        },
        headers=auth,
    ).json()
    assert_conflict(
        client.patch(
            f"/api/v1/loans/{loan['id']}",
            json={"version": loan["version"], "archived": True},
            headers=auth,
        ),
        "remaining scheduled",
    )

    changed_schedule = client.patch(
        f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
        json={
            "version": schedule["version"],
            "amount_minor": 12_000,
            "principal_minor": 9_000,
            "interest_minor": 3_000,
            "status": "cancelled",
        },
        headers=auth,
    )
    assert changed_schedule.status_code == 200, changed_schedule.text
    schedule = changed_schedule.json()
    assert schedule["status"] == "cancelled" and schedule["version"] == 2
    assert_conflict(
        client.delete(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
            params={"version": schedule["version"]},
            headers=auth,
        ),
        "planned",
    )

    restored_schedule = client.patch(
        f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
        json={"version": schedule["version"], "status": "planned"},
        headers=auth,
    ).json()
    assert (
        client.delete(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
            params={"version": restored_schedule["version"]},
            headers=auth,
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/loans/{loan['id']}",
            params={"version": loan["version"]},
            headers=auth,
        ).status_code
        == 204
    )
    db.expire_all()
    assert db.get(Loan, loan["id"]) is None
    assert db.get(LoanScheduleItem, schedule["id"]) is None


def test_paid_schedule_is_immutable_but_completed_loan_can_be_archived(client, auth, account):
    loan = client.post(
        "/api/v1/loans",
        json={"name": "Закрываемый", "account_id": account.id},
        headers=auth,
    ).json()
    schedule = client.post(
        f"/api/v1/loans/{loan['id']}/schedule",
        json={"due_date": "2026-08-05", "amount_minor": 10_000},
        headers=auth,
    ).json()
    paid = client.post(
        f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}/payments",
        json={"amount_minor": 10_000, "date": "2026-08-05", "completed": True},
        headers=auth,
    )
    assert paid.status_code == 201, paid.text
    paid_schedule = paid.json()["schedule_item"]

    assert_conflict(
        client.patch(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
            json={"version": paid_schedule["version"], "amount_minor": 11_000},
            headers=auth,
        ),
        "payment history",
    )
    assert_conflict(
        client.delete(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
            params={"version": paid_schedule["version"]},
            headers=auth,
        ),
        "unpaid planned",
    )
    archived = client.patch(
        f"/api/v1/loans/{loan['id']}",
        json={"version": loan["version"], "archived": True},
        headers=auth,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived"] is True


def test_archived_loan_rejects_every_schedule_mutation(client, auth, account):
    loan = client.post(
        "/api/v1/loans",
        json={"name": "Архивный кредит", "account_id": account.id},
        headers=auth,
    ).json()
    schedule = client.post(
        f"/api/v1/loans/{loan['id']}/schedule",
        json={"due_date": "2026-09-05", "amount_minor": 10_000},
        headers=auth,
    ).json()
    schedule = client.patch(
        f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
        json={"version": schedule["version"], "status": "cancelled"},
        headers=auth,
    ).json()
    archived = client.patch(
        f"/api/v1/loans/{loan['id']}",
        json={"version": loan["version"], "archived": True},
        headers=auth,
    )
    assert archived.status_code == 200, archived.text

    attempts = (
        client.post(
            f"/api/v1/loans/{loan['id']}/schedule",
            json={"due_date": "2026-10-05", "amount_minor": 10_000},
            headers=auth,
        ),
        client.patch(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
            json={"version": schedule["version"], "status": "planned"},
            headers=auth,
        ),
        client.delete(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}",
            params={"version": schedule["version"]},
            headers=auth,
        ),
        client.post(
            f"/api/v1/loans/{loan['id']}/schedule/{schedule['id']}/payments",
            json={"amount_minor": 1_000, "date": "2026-09-05"},
            headers=auth,
        ),
    )
    for response in attempts:
        assert_conflict(response, "restore it")
