from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

import models
from database import SessionLocal


router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/glucose")
def glucose_page(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(url="/login")

    db = SessionLocal()

    try:
        readings = (
            db.query(models.GlucoseReading)
            .filter(
                models.GlucoseReading.user_id == user_id,
                models.GlucoseReading.active == True
            )
            .order_by(
                models.GlucoseReading.timestamp.desc()
            )
            .limit(50)
            .all()
        )

    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="glucose.html",
        context={
            "readings": readings
        }
    )


@router.post("/glucose")
def add_glucose(
    request: Request,
    glucose: int = Form(...),
    timestamp: str = Form(...)
):
    user_id = request.session.get("user_id")

    if not user_id:
        return RedirectResponse(
            url="/login",
            status_code=303
        )

    reading_time = datetime.fromisoformat(timestamp)

    db = SessionLocal()

    try:
        reading = models.GlucoseReading(
            user_id=user_id,
            glucose=glucose,
            timestamp=reading_time,
            source="manual",
            active=True
        )

        db.add(reading)
        db.commit()

    finally:
        db.close()

    return RedirectResponse(
        url="/glucose",
        status_code=303
    )