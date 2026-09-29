from starlette.requests import Request

from app.admin_panel import _same_origin


def admin_request(**headers: str) -> Request:
    raw_headers = [(b"host", b"localhost:8082")]
    raw_headers.extend((name.replace("_", "-").encode(), value.encode()) for name, value in headers.items())
    return Request({
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "server": ("localhost", 8082),
        "path": "/admin/login",
        "query_string": b"",
        "headers": raw_headers,
    })


def test_admin_login_accepts_same_origin_browser_without_origin_header():
    assert _same_origin(admin_request(sec_fetch_site="same-origin"))
    assert _same_origin(admin_request(referer="http://localhost:8082/admin/login"))
    assert _same_origin(admin_request(origin="http://localhost:8082"))


def test_admin_login_rejects_cross_site_or_unidentified_requests():
    assert not _same_origin(admin_request())
    assert not _same_origin(admin_request(origin="https://attacker.example"))
    assert not _same_origin(admin_request(sec_fetch_site="cross-site", origin="http://localhost:8082"))
    assert not _same_origin(admin_request(origin="https://attacker.example", referer="http://localhost:8082/admin/login"))
