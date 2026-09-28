from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api import admin, auth, catalog, finance, io
from .config import config
from .db import verify_database
from .errors import (
    http_error,
    integrity_error,
    operational_error,
    stale_data_error,
    validation_error,
)


app = FastAPI(title="Локальный планировщик бюджета", version=__version__)
trusted_hosts = {
    "127.0.0.1",
    "localhost",
    "testserver",
    *(host.strip() for host in os.getenv("TRUSTED_HOSTS", "").split(",") if host.strip()),
}
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=sorted(trusted_hosts),
)


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:128]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.add_exception_handler(HTTPException, http_error)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(IntegrityError, integrity_error)
app.add_exception_handler(OperationalError, operational_error)
app.add_exception_handler(StaleDataError, stale_data_error)

api = APIRouter(prefix="/api/v1")


@api.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@api.get("/health/ready")
def ready() -> dict:
    verify_database()
    return {"status": "ok"}


api.include_router(auth.router)
api.include_router(admin.router)
api.include_router(catalog.router)
api.include_router(finance.router)
api.include_router(io.router)
app.include_router(api)


if config.static_dir and config.static_dir.is_dir():
    assets = config.static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={
                    "code": "not_found",
                    "message": "API route not found",
                    "field_errors": [],
                    "request_id": str(uuid.uuid4()),
                },
            )
        target = config.static_dir / path
        if target.is_file() and config.static_dir in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(config.static_dir / "index.html")
