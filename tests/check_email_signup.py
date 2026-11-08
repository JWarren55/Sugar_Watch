"""Verified-email enrollment, one-use links, delivery privacy, and access consistency."""

import hashlib
import re
import runpy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient as RawClient
from sqlalchemy import create_engine, inspect, select

from tests.support import TestClient

state = runpy.run_path("tests/check_sections.py")
app, models, database = state["app"], state["models"], state["database"]
from app.core import health_import_auth, security
from app.core.email_settings import EmailSettings, normalize_email
from app.core.settings import settings
from app.db.migrations import schema_migrations
from app.db.migrations.email_signup import NAME, apply_signup_migration
from app.routes import auth, common, signup
from app.services import email_delivery
from app.services.email_delivery import DeliveryError
from app.services.email_verification import reserve_verification

config = EmailSettings(
    enabled=True,
    public_base_url="https://sugar.example.test",
    smtp_host="smtp.example.test",
    smtp_user="sender@example.test",
    smtp_password="private-fixture-password",
    sender="sender@example.test",
)
strict = replace(settings, allowed_emails=("one@example.test",))
messages = []


def deliver(config, address, link):
    assert link.startswith("https://sugar.example.test/verify-email?token=")
    messages.append((address, link))


with TestClient(app) as client:
    assert "Registration is not available yet" in client.get("/join").text
    assert client.post("/join", data={"email": "new@example.test"}).status_code == 503
    with (
        patch.object(signup, "email_settings", config),
        patch.object(common, "email_settings", config),
        patch.object(signup, "send_verification", side_effect=deliver),
        patch.object(auth, "settings", strict),
        patch.object(security, "settings", strict),
        patch.object(health_import_auth, "settings", strict),
    ):
        assert "Verify your email to join" in client.get("/").text
        for address in (
            "bad",
            "bad\r\nBcc:someone@example.test",
            "a@invalid",
            "<script>@example.test",
        ):
            assert client.post("/join", data={"email": address}).status_code == 400
        assert (
            client.post("/join", data={"email": " New@Example.Test "}).status_code
            == 200
        )
        assert len(messages) == 1 and messages[0][0] == "new@example.test"
        link = messages[0][1]
        token = parse_qs(urlsplit(link).query)["token"][0]
        with database.SessionLocal() as db:
            row = (
                db.query(models.EmailVerification)
                .filter_by(email="new@example.test")
                .one()
            )
            assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
            assert token not in str(vars(row)) and "testclient" not in row.request_key
            assert db.get(models.EmailApproval, "new@example.test") is None
        # A scanner opening a GET does not approve or consume the key.
        page = client.get("/verify-email", params={"token": token})
        assert page.status_code == 200 and "Verify my email" in page.text
        assert page.headers["referrer-policy"] == "strict-origin"
        with database.SessionLocal() as db:
            assert db.get(models.EmailApproval, "new@example.test") is None
        assert (
            client.get("/verify-email?token=" + token + "tampered").status_code == 400
        )
        assert (
            client.post(
                "/verify-email", data={"token": token}, follow_redirects=False
            ).status_code
            == 303
        )
        assert "Your email is approved" in client.get("/join/verified").text
        assert client.post("/verify-email", data={"token": token}).status_code == 400
        # Approval is membership, not login or access to another person's records.
        assert client.get("/glucose", follow_redirects=False).status_code == 303
        with database.SessionLocal() as db:
            before = db.query(models.User).count()
        info = dict(
            sub="new-verified-subject",
            email="new@example.test",
            email_verified=True,
            name="Fixture member",
        )
        with patch.object(
            auth.oauth.google,
            "authorize_access_token",
            AsyncMock(return_value={"userinfo": info}),
        ):
            assert (
                client.get("/auth/google/callback", follow_redirects=False).headers[
                    "location"
                ]
                == "/"
            )
        assert client.get("/glucose").status_code == 200
        with database.SessionLocal() as db:
            assert db.query(models.User).count() == before + 1
            member = db.query(models.User).filter_by(email="new@example.test").one()
            member_id = member.id
        keypage = client.post("/integrations/apple-health/token")
        health_key = re.search(
            r'id="health-authorization"[^>]*value="Bearer ([^"]+)"', keypage.text
        ).group(1)
        with RawClient(app) as phone:
            phone.headers["authorization"] = "Bearer " + health_key
            assert (
                phone.post(
                    "/integrations/apple-health/shortcuts/plan",
                    json={"metric": "sleep", "on_wifi": True},
                ).status_code
                == 200
            )
            with database.SessionLocal() as db:
                db.get(
                    models.EmailApproval, "new@example.test"
                ).revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
            assert client.get("/glucose", follow_redirects=False).status_code == 303
            assert (
                phone.post(
                    "/integrations/apple-health/shortcuts/plan",
                    json={"metric": "sleep", "on_wifi": True},
                ).status_code
                == 401
            )
        # Immediate resends are suppressed without revealing registration status.
        assert (
            client.post("/join", data={"email": "new@example.test"}).status_code == 200
        )
        assert len(messages) == 1
        assert (
            client.post("/join", data={"email": "expired@example.test"}).status_code
            == 200
        )
        expired = parse_qs(urlsplit(messages[-1][1]).query)["token"][0]
        with database.SessionLocal() as db:
            db.query(models.EmailVerification).filter_by(
                email="expired@example.test"
            ).update(
                {
                    "expires_at": datetime.now(timezone.utc).replace(tzinfo=None)
                    - timedelta(seconds=1)
                }
            )
            db.commit()
        assert client.post("/verify-email", data={"token": expired}).status_code == 400
        with patch.object(
            signup, "send_verification", side_effect=DeliveryError("fixed error")
        ):
            error = client.post("/join", data={"email": "delivery@example.test"})
            assert error.status_code == 503 and config.smtp_password not in error.text
        with database.SessionLocal() as db:
            assert db.get(models.EmailApproval, "delivery@example.test") is None
        # Neither a forged success page nor unrelated query parameters approve an address.
        assert (
            client.get("/join/verified?email=intruder@example.test").status_code == 200
        )
        with database.SessionLocal() as db:
            assert db.get(models.EmailApproval, "intruder@example.test") is None

with RawClient(app) as raw:
    with patch.object(signup, "email_settings", config):
        assert (
            raw.post("/join", data={"email": "no-csrf@example.test"}).status_code == 403
        )
        assert raw.post("/verify-email", data={"token": token}).status_code == 403

# Persisted rate limits survive separate sessions; expiring a token does not reset limits.
address = "limited@example.test"
for i in range(3):
    assert reserve_verification(address, "fixture-ip")
    with database.SessionLocal() as db:
        db.query(models.EmailVerification).filter_by(email=address).update(
            {
                "created_at": datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(minutes=5)
            }
        )
        db.commit()
assert reserve_verification(address, "different-ip") is None

assert normalize_email("owner@example.test\r\nBcc:intruder@example.test") is None
assert config.smtp_password not in repr(config)
for fields in (
    {"SMTP_TLS_MODE": "none"},
    {"PUBLIC_BASE_URL": "http://sugar.example.test"},
    {"PUBLIC_BASE_URL": "https://evil.example.test"},
    {"SMTP_FROM": "bad\r\n@example.test"},
):
    mapping = dict(
        EMAIL_SIGNUP_ENABLED="true",
        PUBLIC_BASE_URL="https://sugar.example.test",
        SMTP_HOST="smtp.example.test",
        SMTP_PORT="587",
        SMTP_USER="sender",
        SMTP_PASSWORD="fixture",
        SMTP_FROM="sender@example.test",
        **{},
    )
    mapping.update(fields)
    try:
        EmailSettings.from_mapping(
            mapping, replace(settings, allowed_hosts=("sugar.example.test",))
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe mail configuration accepted")

with patch.object(email_delivery.smtplib, "SMTP") as smtp:
    connection = smtp.return_value
    email_delivery.send_verification(
        config,
        "recipient@example.test",
        "https://sugar.example.test/verify-email?token=fictional",
    )
    connection.starttls.assert_called_once()
    connection.login.assert_called_once_with(config.smtp_user, config.smtp_password)
    message = connection.send_message.call_args.args[0]
    assert (
        "30 minutes" in message.get_content() and "fictional" in message.get_content()
    )

engine = create_engine("sqlite://")
schema_migrations.create(engine)
apply_signup_migration(engine, schema_migrations)
apply_signup_migration(engine, schema_migrations)
assert {"email_approvals", "email_verifications"} <= set(
    inspect(engine).get_table_names()
)
with engine.connect() as db:
    assert db.execute(
        select(schema_migrations.c.name).where(schema_migrations.c.name == NAME)
    ).scalars().all() == [NAME]
print(
    "PASS: hash-only/expiring/single-use links, GET scanner safety, CSRF, canonical HTTPS links, rate limits, Google-only membership, immediate revocation, scoped health access, TLS mail, disabled defaults, and migration repeat safety."
)
