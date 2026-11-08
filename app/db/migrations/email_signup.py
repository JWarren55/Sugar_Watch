"""Add public registration storage without changing existing account access."""

import json
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.db import models

NAME = "20261104_verified_email_signup"


def apply_signup_migration(engine, journal):
    with engine.connect() as db:
        locked = False
        try:
            if db.dialect.name == "mysql":
                locked = (
                    db.scalar(text("SELECT GET_LOCK('sugar_watch_email_storage', 30)"))
                    == 1
                )
                db.commit()
                if not locked:
                    raise RuntimeError("Could not acquire the email migration lock.")
            for model in (models.EmailApproval, models.EmailVerification):
                model.__table__.create(db, checkfirst=True)
                db.commit()
            if not db.scalar(select(journal.c.name).where(journal.c.name == NAME)):
                db.execute(
                    journal.insert().values(
                        name=NAME,
                        applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        details=json.dumps(
                            {
                                "tables": ["email_approvals", "email_verifications"],
                                "existing_access": "preserved",
                            }
                        ),
                    )
                )
            db.commit()
        finally:
            if locked:
                db.execute(text("SELECT RELEASE_LOCK('sugar_watch_email_storage')"))
