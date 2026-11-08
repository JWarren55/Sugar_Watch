"""Add database uniqueness guards without discarding conflicting records."""

import json
from datetime import datetime, timezone

from sqlalchemy import Column, Computed, Integer, String, inspect, text
from sqlalchemy.schema import CreateColumn

GUARDS = "20261031_integrity_import"


def apply_integrity_migration(engine, journal):
    with engine.connect() as db:
        locked = False
        try:
            if db.dialect.name == "mysql":
                locked = (
                    db.scalar(text("SELECT GET_LOCK('sugar_watch_integrity', 30)")) == 1
                )
                db.commit()
                if not locked:
                    raise RuntimeError("Could not acquire integrity migration lock.")
            # Check every conflict before doing any DDL. Never select a winner silently.
            checks = (
                ("health_profile", "user_id", "WHERE active = 1"),
                ("favorite_foods", "user_id, food_item_id", ""),
                (
                    "glucose_readings",
                    "user_id, import_key",
                    "WHERE import_key IS NOT NULL",
                ),
            )
            for table, columns, where in checks:
                if table == "glucose_readings" and "import_key" not in {
                    c["name"] for c in inspect(db).get_columns(table)
                }:
                    continue
                conflict = db.execute(
                    text(
                        f"SELECT COUNT(*) FROM (SELECT {columns} FROM {table} {where} "
                        f"GROUP BY {columns} HAVING COUNT(*) > 1) AS conflicts"
                    )
                ).scalar_one()
                if conflict:
                    raise RuntimeError(
                        f"Integrity migration blocked: {table} has {conflict} duplicate groups. "
                        "Review and resolve them before upgrading; no records were removed."
                    )
            additions = (
                (
                    "health_profile",
                    Column(
                        "active_profile_user_id",
                        Integer,
                        Computed("CASE WHEN active = 1 THEN user_id ELSE NULL END"),
                    ),
                ),
                ("glucose_readings", Column("import_key", String(64), nullable=True)),
            )
            for table, column in additions:
                if column.name not in {
                    c["name"] for c in inspect(db).get_columns(table)
                }:
                    definition = str(CreateColumn(column).compile(dialect=db.dialect))
                    db.execute(text(f"ALTER TABLE {table} ADD COLUMN {definition}"))
                    db.commit()
            indexes = (
                (
                    "health_profile",
                    "uq_active_health_profile",
                    "active_profile_user_id",
                ),
                ("favorite_foods", "uq_user_favorite", "user_id, food_item_id"),
                ("glucose_readings", "uq_user_glucose_import", "user_id, import_key"),
            )
            for table, name, columns in indexes:
                if name not in {i["name"] for i in inspect(db).get_indexes(table)}:
                    db.execute(
                        text(f"CREATE UNIQUE INDEX {name} ON {table} ({columns})")
                    )
                    db.commit()
            if not db.scalar(
                journal.select()
                .with_only_columns(journal.c.name)
                .where(journal.c.name == GUARDS)
            ):
                db.execute(
                    journal.insert().values(
                        name=GUARDS,
                        applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        details=json.dumps({"guards": [i[1] for i in indexes]}),
                    )
                )
            db.commit()
        finally:
            if locked:
                db.execute(text("SELECT RELEASE_LOCK('sugar_watch_integrity')"))
