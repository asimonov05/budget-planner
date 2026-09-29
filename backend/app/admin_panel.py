from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from sqlalchemy import Integer, String, select
from sqlalchemy.orm import Mapper
from sqladmin import Admin, ModelView
from sqladmin.audit import AuditEntry, DBAuditBackend
from sqladmin.authentication import AuthenticationBackend
from sqladmin.i18n import I18nConfig
from starlette.requests import Request
from starlette.responses import Response

from .config import config
from .db import Base, SessionLocal, engine
from .models import AuditLog, User
from .security import clear_login_rate, enforce_login_rate, verify_password


HIDDEN_COLUMN_PARTS = (
    "password",
    "token",
    "secret",
    "credential",
    "hash",
    "key",
    "fingerprint",
)
SYSTEM_COLUMN_NAMES = {"created_at", "updated_at", "version"}
LONG_LIST_COLUMNS = {
    "after_json",
    "before_json",
    "comment",
    "response_json",
    "rows_json",
    "settings_json",
}

MODEL_LABELS = {
    "accounts": ("Счёт", "Счета", "Финансы"),
    "app_settings": ("Настройка приложения", "Настройки приложения", "Система"),
    "audit_logs": ("Запись журнала", "Журнал изменений", "Система"),
    "budget_limit_overrides": ("Переопределение лимита", "Переопределения лимитов", "Планы"),
    "budget_limits": ("Лимит бюджета", "Лимиты бюджета", "Планы"),
    "budget_months": ("Бюджетный месяц", "Бюджетные месяцы", "Планы"),
    "categories": ("Категория", "Категории", "Справочники"),
    "goal_reserve_movements": ("Движение резерва", "Движения резервов", "Цели"),
    "goals": ("Цель", "Цели", "Цели"),
    "idempotency_records": ("Ключ идемпотентности", "Ключи идемпотентности", "Система"),
    "import_batches": ("Пакет импорта", "Пакеты импорта", "Обмен данными"),
    "loan_schedule_items": ("Платёж по кредиту", "График платежей", "Кредиты"),
    "loans": ("Кредит", "Кредиты", "Кредиты"),
    "plan_item_tags": ("Тег пункта плана", "Теги пунктов плана", "Планы"),
    "plan_items": ("Пункт плана", "Пункты плана", "Планы"),
    "plan_matches": ("Связь плана и операции", "Связи плана с операциями", "Планы"),
    "plan_overrides": ("Изменение плана", "Изменения плана", "Планы"),
    "sessions": ("Сессия", "Сессии", "Система"),
    "tags": ("Тег", "Теги", "Справочники"),
    "transaction_tags": ("Тег операции", "Теги операций", "Операции"),
    "transactions": ("Операция", "Операции", "Операции"),
    "transfers": ("Перевод", "Переводы", "Операции"),
    "users": ("Владелец", "Владельцы", "Система"),
}

COLUMN_LABELS = {
    "account_id": "Счёт",
    "action": "Действие",
    "amount_minor": "Сумма (коп.)",
    "archived": "В архиве",
    "category_id": "Категория",
    "certainty": "Уверенность",
    "created_at": "Создано",
    "date": "Дата",
    "description": "Описание",
    "entity_id": "ID объекта",
    "entity_type": "Тип объекта",
    "id": "ID",
    "kind": "Тип",
    "month": "Месяц",
    "name": "Название",
    "status": "Статус",
    "title": "Название",
    "type": "Тип",
    "updated_at": "Изменено",
    "username": "Логин",
    "version": "Версия",
}


def _safe_column(name: str) -> bool:
    lowered = name.lower()
    return not any(part in lowered for part in HIDDEN_COLUMN_PARTS)


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    origin_url = urlsplit(origin)
    request_url = urlsplit(str(request.url))
    return (
        origin_url.scheme == request_url.scheme
        and origin_url.netloc == request_url.netloc
    )


class OwnerAdminAuthentication(AuthenticationBackend):
    def __init__(self) -> None:
        super().__init__(
            secret_key=secrets.token_urlsafe(48),
            session_cookie="budget_admin_session",
            max_age=config.session_days * 86400,
            path="/admin",
            same_site="strict",
            https_only=config.cookie_secure,
        )

    async def login(self, request: Request) -> bool | Response:
        if not config.debug_admin_enabled:
            return Response(status_code=404)
        if not _same_origin(request):
            return Response(status_code=403)

        form = await request.form()
        username = str(form.get("username") or "").strip()
        password = str(form.get("password") or "")
        remote = request.client.host if request.client else "unknown"
        enforce_login_rate(remote)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username)) if username else None
            if not user or not verify_password(user.password_hash, password):
                return False
            user_id = user.id
            password_fingerprint = _password_fingerprint(user.password_hash)

        clear_login_rate(remote)
        request.session.clear()
        request.session["user_id"] = user_id
        request.session["password_fingerprint"] = password_fingerprint
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool | Response:
        if not config.debug_admin_enabled:
            return Response(status_code=404)

        user_id = request.session.get("user_id")
        password_fingerprint = request.session.get("password_fingerprint")
        if not isinstance(user_id, int) or not isinstance(password_fingerprint, str):
            return False
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(request):
            return Response(status_code=403)

        with SessionLocal() as db:
            user = db.get(User, user_id)
            return bool(
                user
                and hmac.compare_digest(
                    password_fingerprint, _password_fingerprint(user.password_hash)
                )
            )


class AdminAuditBackend(DBAuditBackend):
    def build_row(
        self, entry: AuditEntry, actor: Any, request: Request
    ) -> AuditLog:
        return AuditLog(
            entity_type=f"admin:{entry.identity}"[:80],
            entity_id=str(entry.pk or "")[:80],
            action=f"admin_{entry.action}"[:40],
            before_json=None,
            after_json=json.dumps(
                {"actor_id": actor, "changes": entry.changes},
                ensure_ascii=False,
                default=str,
                sort_keys=True,
            ),
        )


class DebugModelView(ModelView):
    page_size = 50
    page_size_options = [25, 50, 100]
    can_import = False

    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        await super().on_model_change(data, model, is_created, request)
        if not is_created and isinstance(getattr(model, "version", None), int):
            model.version += 1


def _admin_view(model: type, mapper: Mapper[Any]) -> type[ModelView]:
    table_name = model.__tablename__
    singular, plural, category = MODEL_LABELS.get(
        table_name,
        (model.__name__, f"{model.__name__}s", "Данные"),
    )
    visible = [
        getattr(model, prop.key)
        for prop in mapper.column_attrs
        if _safe_column(prop.key)
    ]
    primary_keys = [getattr(model, column.key) for column in mapper.primary_key]
    needs_manual_primary_key = len(mapper.primary_key) > 1 or any(
        not isinstance(column.type, Integer) or column.autoincrement is False
        for column in mapper.primary_key
    )
    form_columns = [
        column
        for column in visible
        if column.key not in SYSTEM_COLUMN_NAMES
        and (column not in primary_keys or needs_manual_primary_key)
    ]
    list_columns = [
        column
        for column in visible
        if column.key not in LONG_LIST_COLUMNS
    ][:8]
    for primary_key in reversed(primary_keys):
        if primary_key not in list_columns:
            list_columns.insert(0, primary_key)
    string_columns = [
        getattr(model, prop.key)
        for prop in mapper.column_attrs
        if _safe_column(prop.key)
        and prop.key not in LONG_LIST_COLUMNS
        and prop.columns
        and isinstance(prop.columns[0].type, String)
    ]
    required_hidden_fields = any(
        not column.nullable
        and column.default is None
        and column.server_default is None
        and not column.primary_key
        for column in mapper.columns
        if not _safe_column(column.key)
    )
    attrs: dict[str, Any] = {
        "__module__": __name__,
        "name": singular,
        "name_plural": plural,
        "category": category,
        "category_icon": "fa-solid fa-database",
        "icon": "fa-solid fa-table",
        "column_list": list_columns,
        "column_details_list": visible,
        "column_sortable_list": list_columns,
        "column_searchable_list": string_columns,
        "column_default_sort": (primary_keys[0], True) if primary_keys else [],
        "column_export_list": visible,
        "column_labels": {
            column: COLUMN_LABELS.get(column.key, column.key.replace("_", " "))
            for column in visible
        },
        "form_columns": form_columns,
        "form_include_pk": needs_manual_primary_key,
        "can_create": not required_hidden_fields,
    }
    if model in {User, AuditLog}:
        attrs.update(can_create=False, can_edit=False, can_delete=False)
    return type(ModelView)(f"{model.__name__}Admin", (DebugModelView,), attrs, model=model)


def install_debug_admin(app: FastAPI) -> None:
    admin = Admin(
        app=app,
        engine=engine,
        base_url="/admin",
        title="Контур · админка",
        authentication_backend=OwnerAdminAuthentication(),
        authorization_backend=None,
        audit_backend=AdminAuditBackend(SessionLocal),
        i18n_config=I18nConfig(default_locale="ru"),
    )
    for mapper in sorted(Base.registry.mappers, key=lambda item: item.local_table.name):
        admin.add_view(_admin_view(mapper.class_, mapper))
