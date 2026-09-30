"""HTTP boundary and DI provider for self-service registration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..application.register_user import (
    InvalidRegistration,
    OwnerSetupRequired,
    RegisterUserCommand,
    RegisterUserHandler,
    UsernameTaken,
)
from ..db import get_auth_db
from ..infrastructure.credentials import hash_password
from ..infrastructure.register_user import SqlAlchemyRegistration
from ..security import enforce_login_rate
from .auth_session import authenticated_response


router = APIRouter(prefix="/auth", tags=["auth"])


class RegistrationInput(BaseModel):
    username: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    password: str = Field(min_length=12, max_length=512)


def provide_registration_handler(db: Session = Depends(get_auth_db)) -> RegisterUserHandler:
    return RegisterUserHandler(SqlAlchemyRegistration(db), hash_password)


@router.post("/register", status_code=201)
def register(
    body: RegistrationInput,
    request: Request,
    response: Response,
    handler: RegisterUserHandler = Depends(provide_registration_handler),
) -> dict:
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and origin.rstrip("/") != str(request.base_url).rstrip("/")
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    remote = request.client.host if request.client else "unknown"
    enforce_login_rate(f"registration:{remote}")
    try:
        created = handler.execute(RegisterUserCommand(body.username, body.password))
    except InvalidRegistration as exc:
        raise HTTPException(status_code=422, detail="Проверьте логин и пароль") from exc
    except OwnerSetupRequired as exc:
        raise HTTPException(status_code=409, detail="Регистрация будет доступна после настройки владельца") from exc
    except UsernameTaken as exc:
        raise HTTPException(status_code=409, detail="Логин уже занят") from exc
    return authenticated_response(
        response,
        user_id=created.id,
        username=created.username,
        is_admin=False,
        session_token=created.session_token,
        csrf_token=created.csrf_token,
    )
