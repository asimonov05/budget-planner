from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    database_path: Path
    static_dir: Path | None
    database_url: str | None = None
    database_password_file: Path | None = None
    runtime_password_file: Path | None = None
    debug_database_url: str | None = None
    debug_database_password_file: Path | None = None
    session_days: int = 30
    cookie_secure: bool = False
    require_safe_sqlite: bool = False
    debug_admin_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        static = os.getenv("STATIC_DIR")
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH", "./budget.sqlite3")),
            static_dir=Path(static) if static else None,
            database_url=os.getenv("DATABASE_URL"),
            database_password_file=(
                Path(os.environ["DATABASE_PASSWORD_FILE"])
                if os.getenv("DATABASE_PASSWORD_FILE")
                else None
            ),
            runtime_password_file=(
                Path(os.environ["RUNTIME_PASSWORD_FILE"])
                if os.getenv("RUNTIME_PASSWORD_FILE") else None
            ),
            debug_database_url=os.getenv("DEBUG_DATABASE_URL"),
            debug_database_password_file=(
                Path(os.environ["DEBUG_DATABASE_PASSWORD_FILE"])
                if os.getenv("DEBUG_DATABASE_PASSWORD_FILE") else None
            ),
            session_days=int(os.getenv("SESSION_DAYS", "30")),
            cookie_secure=os.getenv("SESSION_COOKIE_SECURE", os.getenv("COOKIE_SECURE", "0"))
            == "1",
            require_safe_sqlite=os.getenv("REQUIRE_SAFE_SQLITE", "0") == "1",
            debug_admin_enabled=os.getenv("DEBUG_ADMIN_ENABLED", "0") == "1",
        )


config = Config.from_env()
