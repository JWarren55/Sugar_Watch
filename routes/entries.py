"""Owned-record edit and soft-delete flows for each tracking section."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from pydantic import Field, ValidationError, create_model
from sqlalchemy import Float, Integer, String

import models
from database import SessionLocal
from routes.common import templates
from units import check_units, preferred_units, to_display, to_storage

router = APIRouter()
FOOD_UNITS = (
    "g",
    "kg",
    "oz",
    "lb",
    "mL",
    "L",
    "fl oz",
    "cup",
    "tbsp",
    "tsp",
    "piece",
    "slice",
    "packet",
    "serving",
)
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
EXCLUDE = {"id", "user_id", "active", "source", "created_at"}
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


def owned(db, section, entry_id, user_id):
    # Only load active records owned by the signed-in user.
    model, _, _ = config(section)
    entry = (
        db.query(model)
        .filter(model.id == entry_id, model.user_id == user_id, model.active.is_(True))
        .first()
    )
    if entry is None:
        raise HTTPException(404, "Entry not found.")
    return entry


def fields_for(section):
    # Build edit fields and validation rules from the section's model.
    model, _, _ = config(section)
    fields = {}
    for column in model.__table__.columns:
        name = column.name
        if name in EXCLUDE:
            continue
        optional = column.nullable and name != "food_item_id"
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


@router.get("/entries/{section}/{entry_id}/edit")
def edit_page(section: str, entry_id: int, request: Request):
    # Fill the edit form with the record's current values.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        _, title, back = config(section)
        units = preferred_units(db, user_id)
        values = {}
        fields = []
        for name in fields_for(section):
            value = getattr(entry, name)
            if name in CONVERTED.get(section, ()):
                value = to_display(value, name, units)
            if isinstance(value, datetime):
                value = value.isoformat(timespec="seconds")
            values[name] = "" if value is None else value
            column = entry.__table__.columns[name]
            kind = (
                "datetime-local"
                if column.type.python_type is datetime
                else ("number" if isinstance(column.type, (Float, Integer)) else "text")
            )
            choices = CHOICES.get(name)
            if name in ("unit", "serving_unit") and section in ("food", "food-item"):
                choices = FOOD_UNITS
            label = LABELS.get(name, name.replace("_", " ").capitalize())
            if name in CONVERTED.get(section, ()):
                label += (
                    " ("
                    + (
                        {"weight": "kg", "waist": "cm", "distance": "km"}
                        if units == "metric"
                        else {"weight": "lb", "waist": "inches", "distance": "miles"}
                    )[name]
                    + ")"
                )
            fields.append(
                {
                    "name": name,
                    "label": label,
                    "kind": kind,
                    "choices": choices,
                    "required": not column.nullable or name == "food_item_id",
                    "maxlength": column.type.length
                    if isinstance(column.type, String)
                    else None,
                }
            )
        foods = []
        if section == "food":
            foods = (
                db.query(models.FoodItem)
                .filter(models.FoodItem.user_id == user_id)
                .order_by(models.FoodItem.name)
                .all()
            )
            foods = [
                food for food in foods if food.active or food.id == entry.food_item_id
            ]
        return templates.TemplateResponse(
            request=request,
            name="edit_entry.html",
            context={
                "title": title,
                "back": back,
                "fields": fields,
                "values": values,
                "foods": foods,
                "measurement_units": units,
                "section": section,
                "entry_id": entry_id,
            },
        )


@router.post("/entries/{section}/{entry_id}/edit")
async def save_edit(section: str, entry_id: int, request: Request):
    # Validate ownership and input before updating the record.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    values = {
        name: (str(form[name]).strip() or None)
        for name in fields_for(section)
        if name in form
    }
    data = validate_values(section, values)
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        if section == "food":
            food = (
                db.query(models.FoodItem)
                .filter(
                    models.FoodItem.id == data["food_item_id"],
                    models.FoodItem.user_id == user_id,
                )
                .first()
            )
            if food is None or (not food.active and food.id != entry.food_item_id):
                raise HTTPException(400, "Choose one of your saved foods.")
        units = check_units(
            form.get("measurement_units") or preferred_units(db, user_id)
        )
        for name in CONVERTED.get(section, ()):
            data[name] = to_storage(data[name], name, units)
        for name, value in data.items():
            setattr(entry, name, value)
        db.commit()
    return RedirectResponse(config(section)[2], status_code=303)


@router.get("/entries/{section}/{entry_id}/delete")
def delete_page(section: str, entry_id: int, request: Request):
    # Show which entry will be removed before asking for confirmation.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        _, title, back = config(section)
        summary = (
            getattr(entry, "name", None)
            or getattr(entry, "medication_name", None)
            or str(getattr(entry, "timestamp", ""))
        )
        return templates.TemplateResponse(
            request=request,
            name="delete_entry.html",
            context={"title": title, "summary": summary, "back": back},
        )


@router.post("/entries/{section}/{entry_id}/delete")
def delete_entry(section: str, entry_id: int, request: Request):
    # Hide the entry by marking it inactive, preserving its database row.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        entry.active = False
        db.commit()
    return RedirectResponse(config(section)[2], status_code=303)
