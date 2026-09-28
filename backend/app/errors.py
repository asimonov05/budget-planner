from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError


def payload(request: Request, code: str, message: str, field_errors: list | None = None) -> dict:
    return {
        "code": code,
        "message": message,
        "field_errors": field_errors or [],
        "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
    }


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=payload(request, "http_error", str(exc.detail))
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        {"field": ".".join(map(str, err["loc"])), "message": err["msg"]} for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422, content=payload(request, "validation_error", "Validation failed", fields)
    )


async def integrity_error(request: Request, _exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=payload(request, "integrity_conflict", "Record conflicts with existing data"),
    )


async def operational_error(request: Request, exc: OperationalError) -> JSONResponse:
    message = (
        "Database is temporarily busy"
        if "locked" in str(exc).lower()
        else "Database operation failed"
    )
    return JSONResponse(status_code=503, content=payload(request, "database_unavailable", message))


async def stale_data_error(request: Request, _exc: StaleDataError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=payload(
            request,
            "version_conflict",
            "Version conflict; reload the entity and retry",
        ),
    )
