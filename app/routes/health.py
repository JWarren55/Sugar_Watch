from datetime import date, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.db import models
from app.db.session import SessionLocal
from app.routes.common import templates
from app.utils.pagination import paginate
from app.utils.time_utils import to_utc
from app.utils.units import check_units, preferred_units, to_storage

router = APIRouter()


@router.get("/health")
def health_page(request: Request):
    # Load the user's profile and recent measurements.
    user_id = request.state.user.id

    with SessionLocal() as db:
        profile = (
            db.query(models.HealthProfile)
            .filter(
                models.HealthProfile.user_id == user_id,
                models.HealthProfile.active.is_(True),
            )
            .first()
        )
        query = (
            db.query(models.HealthHistory)
            .filter(
                models.HealthHistory.user_id == user_id,
                models.HealthHistory.active.is_(True),
            )
            .order_by(
                models.HealthHistory.timestamp.desc(), models.HealthHistory.id.desc()
            )
        )
        entries, pagination = paginate(query, request)
        return templates.TemplateResponse(
            request=request,
            name="health.html",
            context={"profile": profile, "entries": entries, "pagination": pagination},
        )


@router.post("/health/profile")
def save_health_profile(
    request: Request,
    height: float = Form(..., gt=0, allow_inf_nan=False),
    sex: str = Form(...),
    date_of_birth: date = Form(...),
    preferred_units: str = Form(...),
):
    # Save profile changes while keeping stored height in inches.
    user_id = request.state.user.id
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
        # Convert the entered height to inches before storing it.
        profile.height = to_storage(height, "height", preferred_units)
        profile.sex = sex
        profile.date_of_birth = date_of_birth
        profile.preferred_units = preferred_units
        db.commit()
    return RedirectResponse("/health", status_code=303)


@router.post("/health/measurements")
def add_health_measurement(
    request: Request,
    timestamp: datetime | None = Form(None),
    client_timezone: str = Form("America/Chicago"),
    weight: float | None = Form(None, gt=0, allow_inf_nan=False),
    waist: float | None = Form(None, gt=0, allow_inf_nan=False),
    measurement_units: str | None = Form(None),
):
    # Convert weight and waist to storage units before saving.
    user_id = request.state.user.id
    if weight is None and waist is None:
        raise HTTPException(400, "Enter weight and/or waist measurement")

    timestamp = to_utc(timestamp, client_timezone)
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
