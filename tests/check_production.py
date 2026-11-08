"""Exercise a real production app configuration against a disposable database."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

with tempfile.TemporaryDirectory() as directory:
    os.environ.update(
        APP_ENV="production",
        ALLOWED_HOSTS="app.example.test",
        ALLOWED_EMAILS="owner@example.test",
        DATABASE_URL="sqlite:///" + str(Path(directory) / "production-check.sqlite"),
        SECRET_KEY="isolated-production-secret-" + "x" * 40,
        GOOGLE_CLIENT_ID="test-client",
        GOOGLE_CLIENT_SECRET="test-secret",
    )
    from fastapi.responses import RedirectResponse
    from fastapi.testclient import TestClient

    from app.db.session import engine
    from app.routes import auth
    from main import app

    with TestClient(app, base_url="https://app.example.test") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path, follow_redirects=False).status_code == 404
        assert client.get("/", headers={"host": "attacker.example"}).status_code == 400
        redirect = AsyncMock(
            return_value=RedirectResponse("https://accounts.google.com/")
        )
        with patch.object(auth.oauth.google, "authorize_redirect", redirect):
            assert client.get("/login", follow_redirects=False).status_code == 307
        assert (
            str(redirect.call_args.args[1])
            == "https://app.example.test/auth/google/callback"
        )
    engine.dispose()
print(
    "PASS: production startup, secure cookies, allowed hosts, private caching, disabled docs, HTTPS Google callback"
)
