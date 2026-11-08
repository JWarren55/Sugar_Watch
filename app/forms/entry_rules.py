"""Shared editable fields, validation, and owned-record lookup."""

from typing import Literal

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import Field, ValidationError, create_model
from sqlalchemy import Float, Integer, String

from app.db import models
from app.services.nutrition import FOOD_UNITS, NUTRIENT_UNITS, normalized_unit

SECTIONS = {
    "glucose": (models.GlucoseReading, "Glucose reading", "/glucose"),
    "exercise": (models.ExerciseEntry, "Exercise entry", "/exercise"),
    "medication": (models.MedicationEntry, "Medication entry", "/medication"),
    "mood": (models.MoodEntry, "Mood entry", "/mood"),
    "health": (models.HealthHistory, "Health measurement", "/health"),
    "food": (models.FoodEntry, "Food entry", "/food"),
    "food-item": (models.FoodItem, "Saved food", "/food"),
}
CHOICES = {
    "exercise_type": ("Cardio", "Weights", "Task"),
    "intensity": ("Low", "Medium", "High"),
    "feeling": ("Great", "Good", "Okay", "Low", "Stressed"),
    "hunger": ("Not hungry", "Slightly hungry", "Hungry", "Very hungry"),
    "head": ("None", "Mild", "Moderate", "Severe"),
}
EDIT_FIELDS = {
    "glucose": ("glucose", "timestamp"),
    "exercise": (
        "timestamp",
        "length_minutes",
        "exercise_type",
        "intensity",
        "average_heart_rate",
        "peak_heart_rate",
        "distance",
    ),
    "medication": ("timestamp", "medication_name", "dose", "unit"),
    "mood": ("timestamp", "feeling", "hunger", "head"),
    "health": ("timestamp", "weight", "waist"),
    "food": ("food_item_id", "timestamp", "amount", "unit"),
    "food-item": (
        "name",
        "brand",
        "serving_size",
        "serving_unit",
        *NUTRIENT_UNITS,
        "barcode",
    ),
}
CONVERTED = {"health": ("weight", "waist"), "exercise": ("distance",)}
LABELS = {
    "head": "Head / headache",
    "length_minutes": "Duration (minutes)",
    "average_heart_rate": "Average heart rate (bpm)",
    "peak_heart_rate": "Peak heart rate (bpm)",
    "food_item_id": "Food",
    "glucose": "Glucose (mg/dL)",
}


def config(section):
    if section not in SECTIONS:
        raise HTTPException(404, "Section not found.")
    return SECTIONS[section]


def owned(db, section, entry_id, user_id, active=True):
    # Load only owned records in the requested active or deleted state.
    model, _, _ = config(section)
    entry = (
        db.query(model)
        .filter(
            model.id == entry_id, model.user_id == user_id, model.active.is_(active)
        )
        .first()
    )
    if entry is None:
        raise HTTPException(404, "Entry not found.")
    return entry


def fields_for(section):
    # Build edit fields and validation rules from the section's model.
    model, _, _ = config(section)
    fields = {}
    # Only these explicit fields may be submitted; new model columns stay private.
    for name in EDIT_FIELDS[section]:
        column = model.__table__.columns[name]
        optional = column.nullable
        typ = column.type.python_type
        constraints = {}
        if isinstance(column.type, (Float, Integer)):
            constraints["ge"] = 0
            if name in (
                "dose",
                "weight",
                "waist",
                "length_minutes",
                "amount",
                "serving_size",
                "average_heart_rate",
                "peak_heart_rate",
                "food_item_id",
            ):
                constraints = {"gt": 0}
            if name == "glucose":
                constraints = {"ge": 20, "le": 600}
            if isinstance(column.type, Float):
                constraints["allow_inf_nan"] = False
        if isinstance(column.type, String):
            constraints["max_length"] = column.type.length
            if not optional:
                constraints["min_length"] = 1
        if name in CHOICES:
            typ = Literal[CHOICES[name]]
        if name in ("unit", "serving_unit") and section in ("food", "food-item"):
            typ = Literal[FOOD_UNITS]
        fields[name] = (
            typ | None if optional else typ,
            Field(default=None if optional else ..., **constraints),
        )
    return fields


SCHEMAS = {
    key: create_model(key.replace("-", "_") + "Edit", **fields_for(key))
    for key in SECTIONS
}


def validate_values(section, values):
    values = dict(values)
    for key in ("unit", "serving_unit"):
        if section in ("food", "food-item") and values.get(key):
            values[key] = normalized_unit(values[key])
    # Check field values and required combinations before saving.
    try:
        data = SCHEMAS[section].model_validate(values).model_dump()
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    if section == "medication" and data["dose"] is not None and not data["unit"]:
        raise HTTPException(400, "Enter a unit for the dose.")
    if section == "health" and data["weight"] is None and data["waist"] is None:
        raise HTTPException(400, "Enter weight and/or waist measurement.")
    if section == "mood" and not any(
        data.get(k) for k in ("feeling", "hunger", "head")
    ):
        raise HTTPException(400, "Enter at least one mood measurement.")
    if section == "food-item" and (
        (data["serving_size"] is None) != (data["serving_unit"] is None)
    ):
        raise HTTPException(400, "Enter both a serving size and unit.")
    return data


def read_form_values(section, form):
    # Read only allowlisted fields and treat blank optional values as missing.
    return {
        name: (value.strip() or None if isinstance(value, str) else value)
        for name in EDIT_FIELDS[section]
        if (value := form.get(name)) is not None
    }
