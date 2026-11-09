"""Search, review, and save catalog foods for the signed-in account."""

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.settings import settings
from app.db import models
from app.db.session import SessionLocal
from app.forms.entry_rules import validate_values
from app.routes.common import templates
from app.services.food_catalog import CatalogError, USDAClient, normalize_brand
from app.services.nutrition import NUTRIENT_UNITS
from app.services.restaurant_menu import (
    ARBYS_SOURCE,
    ARBYS_SOURCE_LABEL,
    restaurant_food,
    search_restaurant_menu,
)

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
    brand: str = Query("", max_length=100),
    barcode: str = Query("", max_length=50),
    kind: str = Query("all", pattern="^(all|branded|common)$"),
):
    query = q.strip()
    brand = brand.strip()
    barcode = barcode.strip()
    # Accept the common "brand, food" shorthand as well as separate fields.
    if not brand and not barcode and "," in query:
        brand, query = (part.strip() for part in query.split(",", 1))
    brand = normalize_brand(brand)
    searched = bool(query or brand or barcode)
    foods, next_page, error = [], False, None
    if searched:
        try:
            if barcode:
                foods, next_page = client().barcode(barcode, page)
            else:
                foods, next_page = client().search(query, page, brand=brand, kind=kind)
        except CatalogError as exc:
            error = str(exc)
    if not barcode and kind == "all" and page == 1:
        foods = search_restaurant_menu(query, brand) + foods
    return templates.TemplateResponse(
        request=request,
        name="food_catalog.html",
        context={
            "query": query,
            "brand": brand,
            "barcode": barcode,
            "kind": kind,
            "searched": searched,
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
    return render_review(
        request,
        values,
        source="usda",
        external_id=str(fdc_id),
        source_url=f"https://fdc.nal.usda.gov/food-details/{fdc_id}/nutrients",
        source_label=f"USDA FoodData Central, food {fdc_id}",
    )


@router.get("/food/catalog/restaurant/{external_id}")
def review_restaurant_food(request: Request, external_id: str):
    food = restaurant_food(external_id)
    if food is None:
        raise HTTPException(404, "Food not found.")
    return render_review(
        request,
        validate_values("food-item", food),
        source="restaurant",
        external_id=external_id,
        source_url=ARBYS_SOURCE,
        source_label=ARBYS_SOURCE_LABEL,
    )


def render_review(request, values, *, source, external_id, source_url, source_label):
    token = signer().dumps(
        {
            "user_id": request.state.user.id,
            "source": source,
            "external_id": external_id,
            "food": values,
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="food_review.html",
        context={
            "food": values,
            "source": source,
            "source_url": source_url,
            "source_label": source_label,
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
        source = review.get("source", "usda")
        # Reviews opened before the catalog supported restaurant menus use fdc_id.
        external_id = (
            review["external_id"] if "source" in review else str(int(review["fdc_id"]))
        )
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
            .filter_by(
                user_id=request.state.user.id, source=source, external_id=external_id
            )
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
                    source=source,
                    external_id=external_id,
                    active=True,
                    **values,
                )
            )
            db.commit()
    return RedirectResponse("/food", status_code=303)
