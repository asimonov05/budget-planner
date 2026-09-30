from __future__ import annotations

import os
import uvicorn

from .db import verify_database
from .migrations import verify_schema_current


def main() -> None:
    verify_schema_current()
    verify_database()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        proxy_headers=True,
        # Never trust Forwarded/X-Forwarded-* from arbitrary LAN clients.
        # Operators can add only the addresses of their actual reverse proxies.
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
