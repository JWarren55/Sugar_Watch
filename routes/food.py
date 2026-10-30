from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, func

import models
from database import SessionLocal
from entry_rules import read_form_values, validate_values
from nutrition import from_food, normalize_serving
from pagination import paginate
from routes.common import templates
from time_utils import to_utc

router = APIRouter()


@router.get("/food")
def food_page(request: Request):
    # Load saved foods, favorites, and recent entries for this user.
    user_id = request.state.user.id

    with SessionLocal() as db:
        saved_query = (
            db.query(models.FoodItem)
            .filter(
                models.FoodItem.user_id == user_id, models.FoodItem.active.is_(True)
            )
            .order_by(models.FoodItem.name.asc())
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

        saved_query = saved_query.order_by(None).order_by(
            case((models.FoodItem.id.in_(favorite_food_ids), 0), else_=1),
            func.lower(models.FoodItem.name),
            models.FoodItem.id,
        )
        saved_foods, saved_pagination = paginate(saved_query, request, "foods_")

        entry_query = (
            db.query(models.FoodEntry)
            .filter(
                models.FoodEntry.user_id == user_id, models.FoodEntry.active.is_(True)
            )
            .order_by(models.FoodEntry.timestamp.desc(), models.FoodEntry.id.desc())
        )

        entries, pagination = paginate(entry_query, request)

        entry_data = []

        for entry in entries:
            snapshot = entry.nutrition_snapshot or {}
            food = SimpleNamespace(
                name=snapshot.get("name", "Unknown food"), brand=snapshot.get("brand")
            )
            entry_data.append(
                {"entry": entry, "food": food, "nutrition": snapshot.get("totals")}
            )

    return templates.TemplateResponse(
        request=request,
        name="food.html",
        context={
            "saved_foods": saved_foods,
            "entries": entry_data,
            "favorite_food_ids": favorite_food_ids,
            "pagination": pagination,
            "saved_pagination": saved_pagination,
        },
    )


@router.post("/food/create")
async def create_food(request: Request):
    # Use the same allowlisted fields and validation as the food edit form.
    form = await request.form()
    data = normalize_serving(
        validate_values("food-item", read_form_values("food-item", form))
    )
    with SessionLocal() as db:
        db.add(
            models.FoodItem(
                user_id=request.state.user.id, **data, source="manual", active=True
            )
        )
        db.commit()
    return RedirectResponse("/food", status_code=303)


@router.post("/food/quick-log")
def quick_log_food(
    request: Request,
    food_item_id: int = Form(...),
    amount: float = Form(..., gt=0, allow_inf_nan=False),
    unit: str = Form(...),
    timestamp: datetime | None = Form(None),
    client_timezone: str = Form("America/Chicago"),
):
    # Log an amount of a saved food owned by this user.
    user_id = request.state.user.id

    with SessionLocal() as db:
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
        timestamp = to_utc(timestamp, client_timezone)
        validate_values(
            "food",
            {
                "food_item_id": food.id,
                "amount": amount,
                "unit": unit,
                "timestamp": timestamp,
            },
        )
        snapshot = from_food(food, amount, unit)
        entry = models.FoodEntry(
            user_id=user_id,
            food_item_id=food.id,
            timestamp=timestamp,
            amount=snapshot["amount"],
            unit=snapshot["unit"],
            nutrition_snapshot=snapshot,
            active=True,
        )

        db.add(entry)
        db.commit()

    return RedirectResponse(url="/food", status_code=303)


@router.post("/food/favorite")
def toggle_favorite(request: Request, food_item_id: int = Form(...)):
    # Add or remove a saved food from this user's favorites.
    user_id = request.state.user.id

    with SessionLocal() as db:
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

    return RedirectResponse(url="/food", status_code=303)


@router.post("/food/log-multiple")
async def log_multiple_foods(request: Request):
    # Validate the whole food list before saving the entries together.
    user_id = request.state.user.id

    form = await request.form()

    food_item_ids = form.getlist("food_item_id")
    amounts = form.getlist("amount")
    units = form.getlist("unit")

    if not food_item_ids or not (len(food_item_ids) == len(amounts) == len(units)):
        raise HTTPException(400, "Add at least one complete food entry.")
    # Validate the whole batch before inserting any rows.
    timestamp = to_utc(
        form.get("timestamp") or None, form.get("client_timezone", "America/Chicago")
    )
    rows = [
        validate_values(
            "food",
            {
                "food_item_id": food_id,
                "amount": amount,
                "unit": unit,
                "timestamp": timestamp,
            },
        )
        for food_id, amount, unit in zip(food_item_ids, amounts, units)
    ]
    with SessionLocal() as db:
        foods = {
            food.id: food
            for food in db.query(models.FoodItem)
            .filter(
                models.FoodItem.user_id == user_id,
                models.FoodItem.active.is_(True),
                models.FoodItem.id.in_([row["food_item_id"] for row in rows]),
            )
            .all()
        }
        for row in rows:
            food = foods.get(row["food_item_id"])
            if food is None:
                raise HTTPException(400, "Choose one of your saved foods.")
            snapshot = from_food(food, row["amount"], row["unit"])
            row["amount"], row["unit"] = snapshot["amount"], snapshot["unit"]
            row["nutrition_snapshot"] = snapshot
        db.add_all(
            [models.FoodEntry(user_id=user_id, **row, active=True) for row in rows]
        )
        db.commit()
    return RedirectResponse(url="/food", status_code=303)
