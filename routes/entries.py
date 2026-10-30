"""Owned-record edit and soft-delete flows for each tracking section."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import Float, Integer, String

import models
from database import SessionLocal
from entry_rules import (
    CHOICES,
    CONVERTED,
    LABELS,
    config,
    fields_for,
    owned,
    read_form_values,
    validate_values,
)
from nutrition import (
    FOOD_UNITS,
    NUTRIENT_UNITS,
    from_food,
    manual_snapshot,
    normalize_serving,
    scale_snapshot,
)
from routes.common import templates
from time_utils import to_utc, utc_iso, utc_now
from units import check_units, labels_for, preferred_units, to_display, to_storage

router = APIRouter()


@router.get("/entries/{section}/{entry_id}/edit")
def edit_page(section: str, entry_id: int, request: Request):
    # Fill the edit form with the record's current values.
    user_id = request.state.user.id
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
                value = utc_iso(value)
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
            if section == "food-item" and name in NUTRIENT_UNITS:
                label += " (" + NUTRIENT_UNITS[name] + ")"
            if name in CONVERTED.get(section, ()):
                label += " (" + labels_for(units)[name] + ")"
            fields.append(
                {
                    "name": name,
                    "label": label,
                    "kind": kind,
                    "choices": choices,
                    "required": not column.nullable,
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
                "snapshot": getattr(entry, "nutrition_snapshot", None) or {},
                "nutrient_units": NUTRIENT_UNITS,
            },
        )


@router.post("/entries/{section}/{entry_id}/edit")
async def save_edit(section: str, entry_id: int, request: Request):
    # Validate ownership and input before updating the record.
    user_id = request.state.user.id
    form = await request.form()
    values = read_form_values(section, form)
    if values.get("timestamp"):
        values["timestamp"] = to_utc(
            values["timestamp"], form.get("client_timezone", "America/Chicago")
        )
    data = validate_values(section, values)
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        if section == "food":
            mode = form.get("nutrition_mode", "scale")
            if mode not in ("scale", "current", "manual"):
                raise HTTPException(400, "Choose how to update the nutrition.")
            original = entry.nutrition_snapshot or {}
            if mode == "current":
                food = (
                    db.query(models.FoodItem)
                    .filter(
                        models.FoodItem.id == data["food_item_id"],
                        models.FoodItem.user_id == user_id,
                        models.FoodItem.active.is_(True),
                    )
                    .first()
                )
                if food is None:
                    raise HTTPException(
                        400, "Choose an active saved food to recalculate nutrition."
                    )
                snapshot = from_food(food, data["amount"], data["unit"])
            else:
                if data["food_item_id"] != entry.food_item_id:
                    raise HTTPException(
                        400,
                        "Choose 'Use current saved food' when selecting a different food.",
                    )
                if not original:
                    raise HTTPException(
                        400, "Choose a saved food to create a nutrition snapshot."
                    )
                if mode == "manual":
                    snapshot = manual_snapshot(
                        original, data["amount"], data["unit"], form
                    )
                else:
                    snapshot = scale_snapshot(
                        original,
                        data["amount"],
                        data["unit"],
                        strict=bool(original.get("basis_amount")),
                    )
            data.update(
                amount=snapshot["amount"],
                unit=snapshot["unit"],
                nutrition_snapshot=snapshot,
            )
        if section == "food-item":
            data = normalize_serving(data)
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
    user_id = request.state.user.id
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        _, title, back = config(section)
        summary = (
            getattr(entry, "name", None)
            or getattr(entry, "medication_name", None)
            or (getattr(entry, "nutrition_snapshot", None) or {}).get("name")
            or config(section)[1]
        )
        return templates.TemplateResponse(
            request=request,
            name="delete_entry.html",
            context={
                "title": title,
                "summary": summary,
                "back": back,
                "timestamp": getattr(entry, "timestamp", None),
            },
        )


@router.post("/entries/{section}/{entry_id}/delete")
def delete_entry(section: str, entry_id: int, request: Request):
    # Hide the entry by marking it inactive, preserving its database row.
    user_id = request.state.user.id
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id)
        entry.active = False
        entry.deleted_at = utc_now()
        db.commit()
    return RedirectResponse(config(section)[2], status_code=303)
