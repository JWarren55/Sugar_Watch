from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

import models
from database import SessionLocal
from routes.common import templates

router = APIRouter()


@router.get("/medication")
def medication_page(request: Request):
    # Show the user's recent medication entries.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        entries = (
            db.query(models.MedicationEntry)
            .filter(
                models.MedicationEntry.user_id == user_id,
                models.MedicationEntry.active.is_(True),
            )
            .order_by(models.MedicationEntry.timestamp.desc())
            .limit(50)
            .all()
        )
        return templates.TemplateResponse(
            request=request, name="medication.html", context={"entries": entries}
        )


@router.post("/medication")
def add_medication(
    request: Request,
    timestamp: datetime = Form(...),
    medication_name: str = Form(..., min_length=1, max_length=255),
    dose: float | None = Form(None, gt=0, allow_inf_nan=False),
    unit: str | None = Form(None, max_length=50),
):
    # Save the medication after checking its name and dose.
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    medication_name = medication_name.strip()
    unit = unit.strip() if unit else None
    if not medication_name:
        raise HTTPException(400, "Enter a medication name")
    if dose is not None and not unit:
        raise HTTPException(400, "Enter a unit for the dose")
    with SessionLocal() as db:
        db.add(
            models.MedicationEntry(
                user_id=user_id,
                timestamp=timestamp,
                medication_name=medication_name,
                dose=dose,
                unit=unit or None,
                active=True,
            )
        )
        db.commit()
    return RedirectResponse("/medication", status_code=303)
