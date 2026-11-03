"""Search, review, and explicitly save USDA foods for the signed-in account."""

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

import models
from database import SessionLocal
from entry_rules import validate_values
from food_catalog import CatalogError, USDAClient
from nutrition import NUTRIENT_UNITS
from routes.common import templates
from settings import settings

router = APIRouter()


def client():
    return USDAClient(settings.usda_api_key)


def signer():
    return URLSafeTimedSerializer(settings.secret_key, salt="usda-food-review-v1")


@router.get("/food/catalog")
def search_foods(
    request: Request,
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1, le=100),
):
    query = q.strip()
    foods, next_page, error = [], False, None
    if query:
        try:
            foods, next_page = client().search(query, page)
        except CatalogError as exc:
            error = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="food_catalog.html",
        context={
            "query": query,
            "foods": foods,
            "next_page": next_page,
            "page": page,
            "error": error,
        },
    )


@router.get("/food/catalog/{fdc_id}")
def review_food(request: Request, fdc_id: int):
    if not 0 < fdc_id < 10**10:
        raise HTTPException(404, "Food not found.")
    try:
        values = validate_values("food-item", client().food(fdc_id))
    except CatalogError as exc:
        raise HTTPException(503, str(exc))
    token = signer().dumps(
        {"user_id": request.state.user.id, "fdc_id": fdc_id, "food": values}
    )
    return templates.TemplateResponse(
        request=request,
        name="food_review.html",
        context={
            "food": values,
            "fdc_id": fdc_id,
            "review_token": token,
            "nutrient_units": NUTRIENT_UNITS,
        },
    )


@router.post("/food/catalog/save")
def save_food(request: Request, review_token: str = Form(..., max_length=12000)):
    try:
        review = signer().loads(review_token, max_age=1800)
        if review["user_id"] != request.state.user.id:
            raise BadSignature("wrong account")
        values = validate_values("food-item", review["food"])
        fdc_id = str(int(review["fdc_id"]))
    except (BadSignature, KeyError, TypeError, ValueError):
        raise HTTPException(
            400,
            "This food review expired or changed. Open the food again before saving.",
        )
    with SessionLocal() as db:
        # Serialize saves for one user so repeated clicks do not create duplicate imports.
        db.query(models.User).filter_by(
            id=request.state.user.id
        ).with_for_update().one()
        existing = (
            db.query(models.FoodItem)
            .filter_by(user_id=request.state.user.id, source="usda", external_id=fdc_id)
            .first()
        )
        if existing is not None:
            if not existing.active:
                raise HTTPException(
                    409,
                    "This food is in Deleted Items. Restore it there to use it again.",
                )
        else:
            db.add(
                models.FoodItem(
                    user_id=request.state.user.id,
                    source="usda",
                    external_id=fdc_id,
                    active=True,
                    **values,
                )
            )
            db.commit()
    return RedirectResponse("/food", status_code=303)
