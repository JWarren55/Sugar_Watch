"""Shared account-owned persistence for individual Apple Health records."""

from app.db import models

KINDS = {
    "sleep": models.SleepInterval,
    "metric": models.HealthMetricSample,
    "workout": models.HealthWorkout,
}


def save_records(db, user_id, rows):
    counts = dict(sleep=0, metric=0, workout=0, updated=0, skipped=0)
    # Collapse repeated deliveries inside one chunk using the same source identity.
    unique = {(kind, values["import_key"]): values for kind, values in rows}
    existing = {}
    for kind, model in KINDS.items():
        keys = [key for k, key in unique if k == kind]
        for offset in range(0, len(keys), 500):
            for record in db.query(model).filter(
                model.user_id == user_id,
                model.import_key.in_(keys[offset : offset + 500]),
            ):
                existing[(kind, record.import_key)] = record
    for (kind, key), values in unique.items():
        record = existing.get((kind, key))
        if record is None:
            db.add(KINDS[kind](user_id=user_id, active=True, **values))
            counts[kind] += 1
        elif not record.active:
            counts["skipped"] += 1
        elif any(getattr(record, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(record, name, value)
            counts["updated"] += 1
        else:
            counts["skipped"] += 1
    db.flush()
    return counts
