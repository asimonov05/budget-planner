"""Administrator-only API for the superapp's table browser."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import admin_data
from ..models import User
from ..security import require_csrf_unlocked
from .users import require_admin


router = APIRouter(prefix="/superapp/admin/tables", tags=["superapp-admin"], dependencies=[Depends(require_admin)])


class Values(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict = Field(max_length=100)


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class Changes(Values, Revision):
    pass


class Reveal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(min_length=1, max_length=80, pattern=r"^[a-z_][a-z0-9_]*$")


def parse_key(key: str) -> dict:
    try:
        result = json.loads(key)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise HTTPException(422, "Неверный ключ записи") from None


@router.get("")
def table_catalog() -> dict:
    return {"tables": [admin_data.describe_table(t) for t in admin_data.tables().values()]}


@router.get("/{table_name}")
def table_rows(
    table_name: str, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    search: str = Query("", max_length=100), sort: str = Query("", max_length=80),
    direction: Literal["asc", "desc"] = "asc",
) -> dict:
    return admin_data.list_records(admin_data.get_table(table_name), limit, offset, search.strip(), sort, direction)


@router.get("/{table_name}/record")
def table_record(table_name: str, key: str = Query(max_length=2048)) -> dict:
    table = admin_data.get_table(table_name)
    return admin_data.serialize(table, admin_data.read_record(table, parse_key(key)))


@router.post("/{table_name}/record/reveal", dependencies=[Depends(require_csrf_unlocked)])
def reveal_record(
    table_name: str, body: Reveal, key: str = Query(max_length=2048), actor: User = Depends(require_admin),
) -> dict:
    return admin_data.reveal_record(admin_data.get_table(table_name), parse_key(key), body.column, actor.id)


@router.post("/{table_name}", status_code=201, dependencies=[Depends(require_csrf_unlocked)])
def create_record(table_name: str, body: Values, actor: User = Depends(require_admin)) -> dict:
    return admin_data.create_record(admin_data.get_table(table_name), body.values, actor.id)


@router.patch("/{table_name}/record", dependencies=[Depends(require_csrf_unlocked)])
def update_record(
    table_name: str, body: Changes, key: str = Query(max_length=2048), actor: User = Depends(require_admin),
) -> dict:
    return admin_data.mutate_record(admin_data.get_table(table_name), parse_key(key), body.values, body.revision, actor.id)


@router.delete("/{table_name}/record", status_code=204, dependencies=[Depends(require_csrf_unlocked)])
def delete_record(
    table_name: str, body: Revision, key: str = Query(max_length=2048), actor: User = Depends(require_admin),
) -> Response:
    admin_data.mutate_record(admin_data.get_table(table_name), parse_key(key), None, body.revision, actor.id)
    return Response(status_code=204)
