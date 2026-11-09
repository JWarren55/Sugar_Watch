"""Account-owned OpenAI credentials and photo estimates."""

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import delete
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.settings import settings
from app.db import models
from app.db.session import SessionLocal
from app.routes.common import templates
from app.services.food_estimate import (
    ESTIMATE_FIELDS,
    ESTIMATE_MODEL,
    MAX_NUTRIENT,
    MAX_PHOTO_BYTES,
    EstimateError,
    estimate_photo,
)
from app.services.nutrition import from_food
from app.utils.time_utils import LEGACY_TIMEZONE, to_utc

router = APIRouter()
FoodName = Annotated[str, Form(min_length=1, max_length=200)]
MealTime = Annotated[datetime, Form()]
Amount = Annotated[float, Form(ge=0, le=MAX_NUTRIENT, allow_inf_nan=False)]


def credential_cipher(user_id):
    # Derive a separate encryption key for each account and purpose.
    key = hmac.digest(
        settings.secret_key.encode(),
        f"sugar-watch:openai-key:v1:{user_id}".encode(),
        hashlib.sha256,
    )
    return Fernet(base64.urlsafe_b64encode(key))


def clean_name(name):
    if not name.strip():
        raise HTTPException(422, "Enter a food name.")
    return name.strip()


@router.post("/settings/ai-food/key")
def save_key(request: Request, api_key: Annotated[str, Form(max_length=512)]):
    api_key = api_key.strip()
    if (
        not api_key.startswith("sk-")
        or len(api_key) < 20
        or not all(33 <= ord(character) <= 126 for character in api_key)
    ):
        raise HTTPException(422, "Enter an OpenAI API key from your API project.")
    user_id = request.state.user.id
    encrypted_key = credential_cipher(user_id).encrypt(api_key.encode()).decode()
    table = models.OpenAICredential.__table__
    data = dict(user_id=user_id, encrypted_key=encrypted_key)
    with SessionLocal() as db:
        if db.bind.dialect.name == "mysql":
            statement = (
                mysql_insert(table)
                .values(data)
                .on_duplicate_key_update(encrypted_key=encrypted_key)
            )
        else:
            statement = (
                sqlite_insert(table)
                .values(data)
                .on_conflict_do_update(
                    index_elements=[table.c.user_id],
                    set_={"encrypted_key": encrypted_key},
                )
            )
        db.execute(statement)
        db.commit()
    return RedirectResponse("/settings?ai_food=saved#ai-food", status_code=303)


@router.post("/settings/ai-food/remove")
def remove_key(request: Request):
    with SessionLocal() as db:
        db.execute(
            delete(models.OpenAICredential).where(
                models.OpenAICredential.user_id == request.state.user.id
            )
        )
        db.commit()
    return RedirectResponse("/settings?ai_food=removed#ai-food", status_code=303)


@router.get("/food/estimate")
def estimate_page(request: Request):
    with SessionLocal() as db:
        key_saved = db.get(models.OpenAICredential, request.state.user.id) is not None
    return templates.TemplateResponse(
        request=request,
        name="food_estimate.html",
        context={
            "key_saved": key_saved,
            "nutrients": ESTIMATE_FIELDS,
            "max_nutrient": MAX_NUTRIENT,
            "max_photo_bytes": MAX_PHOTO_BYTES,
        },
    )


@router.post("/food/estimate")
def estimate(
    request: Request,
    photo: Annotated[UploadFile, File()],
    name: FoodName,
    timestamp: MealTime,
    description: Annotated[str, Form(max_length=1000)] = "",
    client_timezone: Annotated[str, Form(max_length=100)] = LEGACY_TIMEZONE,
):
    name = clean_name(name)
    timestamp = to_utc(timestamp, client_timezone)
    image = photo.file.read(MAX_PHOTO_BYTES + 1)
    if len(image) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Choose a smaller photo.")
    if (
        photo.content_type != "image/jpeg"
        or not image.startswith(b"\xff\xd8\xff")
        or not image.endswith(b"\xff\xd9")
    ):
        raise HTTPException(422, "Choose a readable food photo.")
    user_id = request.state.user.id
    with SessionLocal() as db:
        credential = db.get(models.OpenAICredential, user_id)
        if credential is None:
            raise HTTPException(409, "Add your OpenAI API key in Settings first.")
        encrypted_key = credential.encrypted_key
    try:
        api_key = credential_cipher(user_id).decrypt(encrypted_key.encode()).decode()
    except InvalidToken:
        raise HTTPException(
            409, "Replace your saved OpenAI API key in Settings."
        ) from None
    try:
        return estimate_photo(api_key, image, name, description.strip(), timestamp)
    except EstimateError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/food/estimate/log")
def log_estimate(
    request: Request,
    name: FoodName,
    timestamp: MealTime,
    calories: Amount,
    carbs: Amount,
    protein: Amount,
    fat: Amount,
    client_timezone: Annotated[str, Form(max_length=100)] = LEGACY_TIMEZONE,
):
    timestamp = to_utc(timestamp, client_timezone)
    food = models.FoodItem(
        name=clean_name(name),
        serving_size=1,
        serving_unit="serving",
        calories=calories,
        carbs=carbs,
        protein=protein,
        fat=fat,
    )
    snapshot = from_food(food, 1, "serving")
    snapshot.update(source="ai_estimate", model=ESTIMATE_MODEL)
    with SessionLocal() as db:
        db.add(
            models.FoodEntry(
                user_id=request.state.user.id,
                timestamp=timestamp,
                amount=snapshot["amount"],
                unit=snapshot["unit"],
                nutrition_snapshot=snapshot,
                active=True,
            )
        )
        db.commit()
    return RedirectResponse("/food#history", status_code=303)
