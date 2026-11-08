"""Authenticate only the health-import endpoint with a scoped revocable bearer."""

import hashlib

from fastapi import HTTPException

from app.core.email_access import email_allowed
from app.core.settings import settings
from app.db import models
from app.db.session import SessionLocal


def verify_health_import(request):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or not 40 <= len(header) <= 256:
        raise HTTPException(401, "A valid Apple Health import token is required.")
    digest = hashlib.sha256(header[7:].encode()).hexdigest()
    with SessionLocal() as db:
        token = (
            db.query(models.HealthImportToken)
            .filter_by(token_hash=digest, active=True)
            .first()
        )
        user = db.get(models.User, token.user_id) if token else None
        if (
            user is None
            or not user.active
            or not email_allowed(db, user.email, settings)
        ):
            raise HTTPException(401, "A valid Apple Health import token is required.")
        request.state.health_import = (user.id, token.id)
