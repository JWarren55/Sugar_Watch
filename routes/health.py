from datetime import date, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

import models
from database import SessionLocal
from routes.common import templates
from units import check_units, preferred_units, to_storage

router = APIRouter()


@router.get("/health")
def health_page(request: Request):
    # Load the user's profile and recent measurements.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        profile = (
            db.query(models.HealthProfile)
            .filter(
                models.HealthProfile.user_id == user_id,
                models.HealthProfile.active.is_(True),
            )
            .first()
        )
        entries = (
            db.query(models.HealthHistory)
            .filter(
                models.HealthHistory.user_id == user_id,
                models.HealthHistory.active.is_(True),
            )
            .order_by(models.HealthHistory.timestamp.desc())
            .limit(50)
            .all()
        )
        return templates.TemplateResponse(
            request=request,
            name="health.html",
            context={"profile": profile, "entries": entries},
        )


@router.post("/health/profile")
def save_health_profile(
    request: Request,
    height: float = Form(..., gt=0, allow_inf_nan=False),
    sex: str = Form(...),
    date_of_birth: date = Form(...),
    preferred_units: str = Form(...),
):
    # Save profile changes while keeping stored height in centimeters.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if preferred_units not in ("imperial", "metric"):
        raise HTTPException(400, "Invalid preferred units")
    if sex not in ("Male", "Female", "Other"):
        raise HTTPException(400, "Invalid sex selection")
    if date_of_birth > date.today():
        raise HTTPException(400, "Birth date cannot be in the future")

    with SessionLocal() as db:
        # One active profile per user; update instead of making duplicates.
        profile = (
            db.query(models.HealthProfile)
            .filter(
                models.HealthProfile.user_id == user_id,
                models.HealthProfile.active.is_(True),
            )
            .first()
        )
        if profile is None:
            profile = models.HealthProfile(user_id=user_id, active=True)
            db.add(profile)
        # Keep stored heights in centimeters so existing profiles remain valid.
        profile.height = height * 2.54 if preferred_units == "imperial" else height
        profile.sex = sex
        profile.date_of_birth = date_of_birth
        profile.preferred_units = preferred_units
        db.commit()
    return RedirectResponse("/health", status_code=303)


@router.post("/health/measurements")
def add_health_measurement(
    request: Request,
    timestamp: datetime = Form(...),
    weight: float | None = Form(None, gt=0, allow_inf_nan=False),
    waist: float | None = Form(None, gt=0, allow_inf_nan=False),
    measurement_units: str | None = Form(None),
):
    # Convert weight and waist to storage units before saving.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if weight is None and waist is None:
        raise HTTPException(400, "Enter weight and/or waist measurement")

    with SessionLocal() as db:
        units = check_units(measurement_units or preferred_units(db, user_id))
        db.add(
            models.HealthHistory(
                user_id=user_id,
                timestamp=timestamp,
                weight=to_storage(weight, "weight", units),
                waist=to_storage(waist, "waist", units),
                active=True,
            )
        )
        db.commit()
    return RedirectResponse("/health", status_code=303)
