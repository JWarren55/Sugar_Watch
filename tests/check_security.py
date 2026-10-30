"""Check request security without weakening it in the application."""

import re
import runpy

from tests.support import TestClient, sign_in

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]

from entry_rules import EDIT_FIELDS, read_form_values
from settings import Settings


def get_token(client, path="/"):
    page = client.get(path)
    match = re.search(r'name="csrf-token" content="([^"]+)"', page.text)
    assert match, page.text
    return match.group(1)


with TestClient(app) as client:
    sign_in(client)
    token = get_token(client)
    assert 'name="current-user-id" content="1"' in client.get("/").text
    status = client.get("/session")
    assert status.status_code == 200 and status.json()["user_id"] == 1
    assert status.json()["csrf_token"] == token
    assert status.headers["cache-control"] == "no-store"
    with database.SessionLocal() as db:
        original = db.query(models.GlucoseReading).count()

    # request() deliberately bypasses the test client's automatic token submission.
    for headers, data in [
        ({}, {"glucose": 122}),
        ({"X-CSRF-Token": "wrong"}, {"glucose": 122}),
        ({}, {"glucose": 122, "csrf_token": "é" * len(token)}),
        (
            {"X-CSRF-Token": token, "Origin": "https://attacker.example"},
            {"glucose": 122},
        ),
    ]:
        response = client.request(
            "POST", "/glucose", data=data, headers=headers, follow_redirects=False
        )
        assert response.status_code == 403, response.text
    with database.SessionLocal() as db:
        assert db.query(models.GlucoseReading).count() == original

    response = client.request(
        "POST",
        "/glucose",
        data={
            "glucose": 122,
            "csrf_token": token,
            "user_id": 2,
            "active": False,
            "source": "forged",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    with database.SessionLocal() as db:
        row = (
            db.query(models.GlucoseReading)
            .order_by(models.GlucoseReading.id.desc())
            .first()
        )
        assert row.user_id == 1 and row.active and row.source == "manual"

    with TestClient(app) as other:
        sign_in(other)
        assert get_token(other) != token
        result = other.request(
            "POST", "/glucose", data={"glucose": 130}, headers={"X-CSRF-Token": token}
        )
        assert result.status_code == 403

    headers = client.get("/glucose").headers
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    with TestClient(app) as fresh_client:
        cookie = fresh_client.get("/").headers["set-cookie"].lower()
    assert (
        "httponly" in cookie and "samesite=lax" in cookie and "max-age=28800" in cookie
    )
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400

    result = client.request("POST", "/glucose", content=b"x" * (1024 * 1024 + 1))
    assert result.status_code == 413 and "too large" in result.text
    assert result.headers["cache-control"] == "no-store"

    # A GET can show a logout confirmation but must not change the login state.
    assert client.get("/logout").status_code == 200
    assert client.get("/medication").status_code == 200
    assert client.request("POST", "/logout", follow_redirects=False).status_code == 403
    assert client.get("/medication").status_code == 200
    assert client.post("/logout", follow_redirects=False).status_code == 303
    assert client.get("/medication", follow_redirects=False).status_code == 303
    assert (
        client.get("/session", headers={"Accept": "application/json"}).status_code
        == 401
    )

    # Account deactivation takes effect even when the old signed cookie is valid.
    sign_in(client)
    get_token(client)
    with database.SessionLocal() as db:
        user = db.get(models.User, 1)
        user.active = False
        db.commit()
    result = client.get("/glucose", follow_redirects=False)
    assert result.status_code == 303
    assert (
        client.post(
            "/glucose", data={"glucose": 123}, headers={"Accept": "application/json"}
        ).status_code
        == 401
    )
    with database.SessionLocal() as db:
        user = db.get(models.User, 1)
        user.active = True
        db.commit()

    # Removed accounts and invalid session ID types cannot reach protected pages.
    for invalid in (999999, "1", True):
        sign_in(client, invalid)
        assert client.get("/trash", follow_redirects=False).status_code == 303

# Only explicitly visible fields can ever be updated.
assert "user_id" not in EDIT_FIELDS["food-item"]
assert "source" not in EDIT_FIELDS["food-item"]
assert "nutrition_snapshot" not in EDIT_FIELDS["food"]
assert read_form_values(
    "food-item", {"name": "  Oats  ", "user_id": 2, "active": False}
) == {"name": "Oats"}

base = {"SECRET_KEY": "development-example", "DATABASE_URL": "sqlite://"}
for values in (
    {"DATABASE_URL": "sqlite://"},
    {"SECRET_KEY": "example"},
    dict(base, APP_ENV="production", ALLOWED_HOSTS="example.test"),
    dict(base, APP_ENV="production", SECRET_KEY="x" * 40),
):
    try:
        Settings.from_mapping(values)
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe settings were accepted")
production = Settings.from_mapping(
    dict(
        base,
        APP_ENV="production",
        SECRET_KEY="private-key-" + "x" * 40,
        ALLOWED_HOSTS="example.test",
        ALLOWED_EMAILS="owner@example.test",
    )
)
assert production.production and production.allowed_hosts == ("example.test",)
assert "private-key" not in repr(production) and "sqlite" not in repr(production)

print(
    "PASS: CSRF and origin checks; token isolation; active-account checks; safe logout; field allowlists; body limits; privacy headers; validated private settings."
)
