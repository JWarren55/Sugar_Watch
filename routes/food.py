from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

import models
from database import SessionLocal
from routes.common import templates
from routes.entries import SCHEMAS, validate_values

router = APIRouter()


def convert_to_base_unit(amount, unit):
    # Convert compatible weights and volumes before comparing servings.
    unit = unit.lower().strip()

    # Weight -> grams
    if unit == "g":
        return amount, "g"

    if unit == "kg":
        return amount * 1000, "g"

    if unit == "oz":
        return amount * 28.3495, "g"

    if unit == "lb":
        return amount * 453.592, "g"

    # Volume -> milliliters
    if unit == "ml":
        return amount, "ml"

    if unit == "l":
        return amount * 1000, "ml"

    if unit == "fl oz":
        return amount * 29.5735, "ml"

    if unit == "cup":
        return amount * 236.588, "ml"

    if unit == "tbsp":
        return amount * 14.7868, "ml"

    if unit == "tsp":
        return amount * 4.92892, "ml"

    # Units that cannot be universally converted
    return amount, unit


def calculate_servings(food, amount, unit):
    # Calculate how many label servings match the logged amount.

    if food.serving_size is None or food.serving_unit is None:
        return None

    logged_amount, logged_unit = convert_to_base_unit(amount, unit)

    serving_amount, serving_unit = convert_to_base_unit(
        food.serving_size, food.serving_unit
    )

    if logged_unit != serving_unit:
        return None

    if serving_amount == 0:
        return None

    return logged_amount / serving_amount


def calculate_nutrition(food, amount, unit):
    # Scale each nutrition value by the number of servings.

    servings = calculate_servings(food, amount, unit)

    if servings is None:
        return None

    return {
        "servings": servings,
        "calories": (food.calories * servings if food.calories is not None else None),
        "carbs": (food.carbs * servings if food.carbs is not None else None),
        "protein": (food.protein * servings if food.protein is not None else None),
        "fat": (food.fat * servings if food.fat is not None else None),
        "fiber": (food.fiber * servings if food.fiber is not None else None),
        "sugar": (food.sugar * servings if food.sugar is not None else None),
    }


@router.get("/food")
def food_page(request: Request):
    # Load saved foods, favorites, and recent entries for this user.
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(url="/login")

    db = SessionLocal()

    try:
        saved_foods = (
            db.query(models.FoodItem)
            .filter(
                models.FoodItem.user_id == user_id, models.FoodItem.active.is_(True)
            )
            .order_by(models.FoodItem.name.asc())
            .all()
        )

        favorites = (
            db.query(models.FavoriteFood)
            .filter(
                models.FavoriteFood.user_id == user_id,
                models.FavoriteFood.active.is_(True),
            )
            .all()
        )

        favorite_food_ids = {favorite.food_item_id for favorite in favorites}

        saved_foods.sort(
            key=lambda food: (food.id not in favorite_food_ids, food.name.lower())
        )

        entries = (
            db.query(models.FoodEntry)
            .filter(
                models.FoodEntry.user_id == user_id, models.FoodEntry.active.is_(True)
            )
            .order_by(models.FoodEntry.timestamp.desc())
            .limit(50)
            .all()
        )

        entry_data = []

        for entry in entries:
            food = (
                db.query(models.FoodItem)
                .filter(
                    models.FoodItem.id == entry.food_item_id,
                    models.FoodItem.user_id == user_id,
                )
                .first()
            )

            nutrition = None

            if food is not None:
                nutrition = calculate_nutrition(food, entry.amount, entry.unit)

            entry_data.append({"entry": entry, "food": food, "nutrition": nutrition})

    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="food.html",
        context={
            "saved_foods": saved_foods,
            "entries": entry_data,
            "favorite_food_ids": favorite_food_ids,
        },
    )


@router.post("/food/create")
def create_food(
    request: Request,
    name: str = Form(...),
    brand: str | None = Form(None),
    serving_size: float | None = Form(None),
    serving_unit: str | None = Form(None),
    calories: float | None = Form(None),
    fat: float | None = Form(None),
    saturated_fat: float | None = Form(None),
    trans_fat: float | None = Form(None),
    cholesterol: float | None = Form(None),
    sodium: float | None = Form(None),
    carbs: float | None = Form(None),
    fiber: float | None = Form(None),
    sugar: float | None = Form(None),
    added_sugar: float | None = Form(None),
    protein: float | None = Form(None),
    vitamin_d: float | None = Form(None),
    calcium: float | None = Form(None),
    iron: float | None = Form(None),
    potassium: float | None = Form(None),
    caffeine: float | None = Form(None),
    barcode: str | None = Form(None),
):
    # Validate and save the nutrition values for a custom food.
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()

    try:
        values = {
            key: (value.strip() or None if isinstance(value, str) else value)
            for key, value in locals().copy().items()
            if key in SCHEMAS["food-item"].model_fields
        }
        data = validate_values("food-item", values)
        food = models.FoodItem(user_id=user_id, **data, source="manual", active=True)

        db.add(food)
        db.commit()

    finally:
        db.close()

    return RedirectResponse(url="/food", status_code=303)


@router.post("/food/quick-log")
def quick_log_food(
    request: Request,
    food_item_id: int = Form(...),
    amount: float = Form(..., gt=0, allow_inf_nan=False),
    unit: str = Form(...),
):
    # Log an amount of a saved food owned by this user.
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()

    try:
        food = (
            db.query(models.FoodItem)
            .filter(
                models.FoodItem.id == food_item_id,
                models.FoodItem.user_id == user_id,
                models.FoodItem.active.is_(True),
            )
            .first()
        )

        if food is None:
            raise HTTPException(404, "Food not found.")
        validate_values(
            "food",
            {
                "food_item_id": food.id,
                "amount": amount,
                "unit": unit,
                "timestamp": datetime.now(),
            },
        )

        entry = models.FoodEntry(
            user_id=user_id,
            food_item_id=food.id,
            timestamp=datetime.now(),
            amount=amount,
            unit=unit,
            active=True,
        )

        db.add(entry)
        db.commit()

    finally:
        db.close()

    return RedirectResponse(url="/food", status_code=303)


@router.post("/food/favorite")
def toggle_favorite(request: Request, food_item_id: int = Form(...)):
    # Add or remove a saved food from this user's favorites.
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    db = SessionLocal()

    try:
        food = (
            db.query(models.FoodItem)
            .filter(
                models.FoodItem.id == food_item_id,
                models.FoodItem.user_id == user_id,
                models.FoodItem.active.is_(True),
            )
            .first()
        )
        if food is None:
            raise HTTPException(404, "Food not found.")

        favorite = (
            db.query(models.FavoriteFood)
            .filter(
                models.FavoriteFood.user_id == user_id,
                models.FavoriteFood.food_item_id == food_item_id,
            )
            .first()
        )

        if favorite:
            favorite.active = not favorite.active

        else:
            favorite = models.FavoriteFood(
                user_id=user_id, food_item_id=food_item_id, active=True
            )

            db.add(favorite)

        db.commit()

    finally:
        db.close()

    return RedirectResponse(url="/food", status_code=303)


@router.post("/food/log-multiple")
async def log_multiple_foods(request: Request):
    # Validate the whole food list before saving the entries together.
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    food_item_ids = form.getlist("food_item_id")
    amounts = form.getlist("amount")
    units = form.getlist("unit")

    if not food_item_ids or not (len(food_item_ids) == len(amounts) == len(units)):
        raise HTTPException(400, "Add at least one complete food entry.")
    # Validate the whole batch before inserting any rows.
    rows = [
        validate_values(
            "food",
            {
                "food_item_id": food_id,
                "amount": amount,
                "unit": unit,
                "timestamp": datetime.now(),
            },
        )
        for food_id, amount, unit in zip(food_item_ids, amounts, units)
    ]
    with SessionLocal() as db:
        for row in rows:
            food = (
                db.query(models.FoodItem)
                .filter(
                    models.FoodItem.id == row["food_item_id"],
                    models.FoodItem.user_id == user_id,
                    models.FoodItem.active.is_(True),
                )
                .first()
            )
            if food is None:
                raise HTTPException(400, "Choose one of your saved foods.")
        db.add_all(
            [models.FoodEntry(user_id=user_id, **row, active=True) for row in rows]
        )
        db.commit()
    return RedirectResponse(url="/food", status_code=303)
