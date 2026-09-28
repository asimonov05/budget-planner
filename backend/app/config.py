from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    database_path: Path
    backup_dir: Path
    static_dir: Path | None
    session_days: int = 30
    cookie_secure: bool = False
    require_safe_sqlite: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        static = os.getenv("STATIC_DIR")
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH", "./budget.sqlite3")),
            backup_dir=Path(os.getenv("BACKUP_DIR", "./backups")),
            static_dir=Path(static) if static else None,
            session_days=int(os.getenv("SESSION_DAYS", "30")),
            cookie_secure=os.getenv("SESSION_COOKIE_SECURE", os.getenv("COOKIE_SECURE", "0"))
            == "1",
            require_safe_sqlite=os.getenv("REQUIRE_SAFE_SQLITE", "0") == "1",
        )


config = Config.from_env()
