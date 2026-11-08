"""One-use verification tokens and persistent limits for public registration mail."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.settings import settings
from app.db import models
from app.db.session import SessionLocal

TTL = timedelta(minutes=30)


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def reserve_verification(email, remote_host):
    now = now_utc()
    ip_key = hmac.new(
        settings.secret_key.encode(), remote_host[:255].encode(), hashlib.sha256
    ).hexdigest()
    raw = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        locked = False
        try:
            if db.bind.dialect.name == "mysql":
                locked = (
                    db.scalar(text("SELECT GET_LOCK('sugar_watch_email_limits', 10)"))
                    == 1
                )
                if not locked:
                    return None
            # Count every reserved send so SMTP failures do not bypass the limits.
            recent = db.query(models.EmailVerification).filter(
                models.EmailVerification.created_at >= now - timedelta(days=1)
            )
            if recent.count() >= 200:
                return None
            if (
                recent.filter_by(request_key=ip_key)
                .filter(models.EmailVerification.created_at >= now - timedelta(hours=1))
                .count()
                >= 20
            ):
                return None
            for_email = recent.filter_by(email=email)
            if (
                for_email.filter(
                    models.EmailVerification.created_at >= now - timedelta(hours=1)
                ).count()
                >= 3
                or for_email.filter(
                    models.EmailVerification.created_at >= now - timedelta(seconds=60)
                ).count()
            ):
                return None
            # Newest link wins; do not retain reusable approval URLs.
            db.query(models.EmailVerification).filter_by(
                email=email, used_at=None
            ).update({"used_at": now})
            db.add(
                models.EmailVerification(
                    email=email,
                    token_hash=digest(raw),
                    created_at=now,
                    expires_at=now + TTL,
                    request_key=ip_key,
                )
            )
            db.query(models.EmailVerification).filter(
                models.EmailVerification.created_at < now - timedelta(days=7)
            ).delete()
            db.commit()
            return raw
        finally:
            if locked:
                db.execute(text("SELECT RELEASE_LOCK('sugar_watch_email_limits')"))


def lookup_token(db, token, *, lock=False):
    if not isinstance(token, str) or not 40 <= len(token) <= 100:
        return None
    query = db.query(models.EmailVerification).filter_by(
        token_hash=digest(token), used_at=None
    )
    if lock:
        query = query.with_for_update()
    row = query.first()
    return row if row and row.expires_at > now_utc() else None


def approve_token(token):
    with SessionLocal() as db:
        row = lookup_token(db, token, lock=True)
        if row is None:
            return False
        now = now_utc()
        approval = db.get(models.EmailApproval, row.email)
        if approval is None:
            db.add(
                models.EmailApproval(email=row.email, verified_at=now, approved_at=now)
            )
        elif approval.revoked_at:
            # A previous explicit revocation cannot be undone by public signup.
            return False
        else:
            approval.verified_at = approval.verified_at or now
            approval.approved_at = approval.approved_at or now
        row.used_at = now
        db.commit()
        return True
