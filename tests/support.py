"""Test client that submits valid CSRF tokens unless a test bypasses post()."""

import re

from fastapi.testclient import TestClient as BaseTestClient


class TestClient(BaseTestClient):
    __test__ = False

    def post(self, url, **kwargs):
        # Fetch a real token instead of disabling CSRF in integration tests.
        page = self.get("/")
        match = re.search(r'name="csrf-token" content="([^"]+)"', page.text)
        if match:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("X-CSRF-Token", match.group(1))
            kwargs["headers"] = headers
        return super().post(url, **kwargs)


def sign_in(client, user_id=1):
    # Test cookies use the same host-only domain behavior as browser sessions.
    import base64
    import json

    from itsdangerous import TimestampSigner

    from app.core.settings import settings

    client.cookies.clear()
    payload = base64.b64encode(json.dumps({"user_id": user_id}).encode())
    host = client.base_url.host
    domain = host if "." in host or ":" in host else host + ".local"
    client.cookies.set(
        "session",
        TimestampSigner(settings.secret_key).sign(payload).decode(),
        domain=domain,
        path="/",
    )
