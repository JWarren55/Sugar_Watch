"""Freeze food nutrition using standard mass, volume, and nutrient units."""

from copy import deepcopy
from math import isfinite

from fastapi import HTTPException

NUTRIENT_UNITS = {
    "calories": "kcal",
    "fat": "g",
    "saturated_fat": "g",
    "trans_fat": "g",
    "cholesterol": "mg",
    "sodium": "mg",
    "carbs": "g",
    "fiber": "g",
    "sugar": "g",
    "added_sugar": "g",
    "protein": "g",
    "vitamin_d": "mcg",
    "calcium": "mg",
    "iron": "mg",
    "potassium": "mg",
    "caffeine": "mg",
}
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
CONVERSIONS = {
    "g": (1, "g"),
    "kg": (1000, "g"),
    "oz": (28.349523125, "g"),
    "lb": (453.59237, "g"),
    "ml": (1, "mL"),
    "l": (1000, "mL"),
    "fl oz": (29.5735295625, "mL"),
    "cup": (236.5882365, "mL"),
    "tbsp": (14.78676478125, "mL"),
    "tsp": (4.92892159375, "mL"),
}


def canonical(amount, unit):
    amount = float(amount)
    if not isfinite(amount) or amount <= 0:
        raise HTTPException(400, "Food amounts must be finite and greater than zero.")
    unit = str(unit).strip().lower()
    if unit in CONVERSIONS:
        factor, name = CONVERSIONS[unit]
        converted = amount * factor
        if not isfinite(converted):
            raise HTTPException(400, "This food amount is too large to convert.")
        return converted, name
    if unit in ("piece", "slice", "packet", "serving"):
        return float(amount), unit
    raise HTTPException(400, "Choose a supported food unit.")


def normalized_unit(unit):
    return {"ml": "mL", "l": "L"}.get(
        str(unit).strip().lower(), str(unit).strip().lower()
    )


def normalize_serving(data):
    if data.get("serving_size") is not None and data.get("serving_unit"):
        data["serving_size"], data["serving_unit"] = canonical(
            data["serving_size"], data["serving_unit"]
        )
    return data


def from_food(food, amount, unit, strict=True):
    # Copy the food definition so future edits cannot change historical totals.
    snapshot = {
        "version": 1,
        "name": food.name if food else "Unknown food",
        "brand": food.brand if food else None,
        "basis_amount": None,
        "basis_unit": None,
        "basis_nutrients": {
            key: getattr(food, key, None) if food else None for key in NUTRIENT_UNITS
        },
        "nutrient_units": NUTRIENT_UNITS,
    }
    if food and food.serving_size and food.serving_unit:
        snapshot["basis_amount"], snapshot["basis_unit"] = canonical(
            food.serving_size, food.serving_unit
        )
    return scale_snapshot(snapshot, amount, unit, strict)


def scale_snapshot(original, amount, unit, strict=True):
    snapshot = deepcopy(original)
    quantity, name = canonical(amount, unit)
    if name == "serving" and snapshot.get("basis_amount"):
        quantity, name = quantity * snapshot["basis_amount"], snapshot["basis_unit"]
    basis = snapshot.get("basis_amount")
    if not isfinite(quantity):
        raise HTTPException(400, "This food amount is too large to convert.")
    ratio = quantity / basis if basis and name == snapshot.get("basis_unit") else None
    if ratio is not None and not isfinite(ratio):
        raise HTTPException(400, "This serving calculation is too large.")
    if ratio is None and strict:
        raise HTTPException(
            400,
            "This unit cannot be converted to the food's serving. Choose matching weight, volume, or count units.",
        )
    snapshot["amount"], snapshot["unit"], snapshot["servings"] = quantity, name, ratio
    snapshot["totals"] = {
        key: (value * ratio if value is not None and ratio is not None else None)
        for key, value in snapshot["basis_nutrients"].items()
    }
    if any(
        value is not None and not isfinite(value)
        for value in snapshot["totals"].values()
    ):
        raise HTTPException(
            400, "This food amount produces nutrition totals that are too large."
        )
    return snapshot


def manual_snapshot(snapshot, amount, unit, form):
    snapshot = deepcopy(snapshot)
    quantity, name = canonical(amount, unit)
    if name == "serving" and snapshot.get("basis_amount"):
        quantity, name = quantity * snapshot["basis_amount"], snapshot["basis_unit"]
    if not isfinite(quantity):
        raise HTTPException(400, "This food amount is too large to convert.")
    totals = {}
    for nutrient in NUTRIENT_UNITS:
        raw = str(form.get("nutrition_" + nutrient, "")).strip()
        try:
            value = float(raw) if raw else None
        except ValueError as exc:
            raise HTTPException(400, "Enter a valid nutrition amount.") from exc
        if value is not None and (not isfinite(value) or value < 0):
            raise HTTPException(
                400, "Nutrition amounts must be finite and nonnegative."
            )
        totals[nutrient] = value
    snapshot.update(
        {
            "basis_amount": quantity,
            "basis_unit": name,
            "basis_nutrients": totals,
            "amount": quantity,
            "unit": name,
            "servings": 1,
            "totals": totals,
        }
    )
    return snapshot
