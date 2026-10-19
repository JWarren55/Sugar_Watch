"""Display conversions; retain existing database units (cm, lb, inches, miles)."""

from fastapi import HTTPException

import models

FACTORS = {"height": 1.0, "weight": 0.45359237, "waist": 2.54, "distance": 1.609344}


def preferred_units(db, user_id):
    profile = (
        db.query(models.HealthProfile)
        .filter(
            models.HealthProfile.user_id == user_id,
            models.HealthProfile.active.is_(True),
        )
        .first()
    )
    return profile.preferred_units if profile else "imperial"


def check_units(value):
    if value not in ("imperial", "metric"):
        raise HTTPException(400, "Choose Imperial or Metric.")
    return value


def to_display(value, field, units):
    if value is None:
        return None
    if field == "height":
        return value if units == "metric" else value / 2.54
    return value * FACTORS[field] if units == "metric" else value


def to_storage(value, field, units):
    if value is None:
        return None
    if field == "height":
        return value if units == "metric" else value * 2.54
    return value / FACTORS[field] if units == "metric" else value
