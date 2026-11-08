"""Add delivery receipts and checkpoints without changing saved health records."""

import json
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.db import models

NAME = "20261104_apple_shortcuts_sync"


def apply_shortcut_migration(engine, journal):
    with engine.connect() as db:
        locked = False
        try:
            if db.dialect.name == "mysql":
                locked = (
                    db.scalar(text("SELECT GET_LOCK('sugar_watch_shortcuts', 30)")) == 1
                )
                db.commit()
                if not locked:
                    raise RuntimeError(
                        "Could not acquire the Shortcuts migration lock."
                    )
            for model in (
                models.HealthShortcutProgress,
                models.HealthShortcutBatch,
                models.HealthNativeImport,
            ):
                model.__table__.create(db, checkfirst=True)
                db.commit()
            if not db.scalar(select(journal.c.name).where(journal.c.name == NAME)):
                db.execute(
                    journal.insert().values(
                        name=NAME,
                        applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        details=json.dumps(
                            {
                                "tables": [
                                    "health_shortcut_progress",
                                    "health_shortcut_batches",
                                    "health_native_imports",
                                ],
                                "existing_records": "unchanged",
                            }
                        ),
                    )
                )
            db.commit()
        finally:
            if locked:
                db.execute(text("SELECT RELEASE_LOCK('sugar_watch_shortcuts')"))
