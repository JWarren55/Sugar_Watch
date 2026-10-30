"""Convert Imperial storage units to and from the user's display preference."""

from fastapi import HTTPException

import models

UNIT_LABELS = {
    "imperial": {
        "height": "inches",
        "weight": "lb",
        "waist": "inches",
        "distance": "miles",
    },
    "metric": {"height": "cm", "weight": "kg", "waist": "cm", "distance": "km"},
}


def labels_for(units):
    return UNIT_LABELS[check_units(units)]


FACTORS = {"height": 2.54, "weight": 0.45359237, "waist": 2.54, "distance": 1.609344}


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
    return value * FACTORS[field] if units == "metric" else value


def to_storage(value, field, units):
    if value is None:
        return None
    return value / FACTORS[field] if units == "metric" else value
