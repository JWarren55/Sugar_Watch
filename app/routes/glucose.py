from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.db import models
from app.db.session import SessionLocal
from app.routes.common import templates
from app.services.dashboard import timeline
from app.utils.pagination import paginate
from app.utils.time_utils import to_utc

router = APIRouter()


@router.get("/glucose")
def glucose_page(request: Request):
    # Show the user's most recent glucose readings.
    user_id = request.state.user.id

    with SessionLocal() as db:
        query = (
            db.query(models.GlucoseReading)
            .filter(
                models.GlucoseReading.user_id == user_id,
                models.GlucoseReading.active.is_(True),
            )
            .order_by(
                models.GlucoseReading.timestamp.desc(), models.GlucoseReading.id.desc()
            )
        )
        readings, pagination = paginate(query, request)

    return templates.TemplateResponse(
        request=request,
        name="glucose.html",
        context={
            "readings": readings,
            "pagination": pagination,
            "imported": request.query_params.get("imported"),
            "skipped": request.query_params.get("skipped"),
        },
    )


@router.post("/glucose")
def add_glucose(
    request: Request,
    glucose: int = Form(..., ge=20, le=600),
    timestamp: datetime | None = Form(None),
    client_timezone: str = Form("America/Chicago"),
):
    # Save a validated reading for the signed-in user.
    user_id = request.state.user.id

    reading_time = to_utc(timestamp, client_timezone)

    with SessionLocal() as db:
        reading = models.GlucoseReading(
            user_id=user_id,
            glucose=glucose,
            timestamp=reading_time,
            source="manual",
            active=True,
        )

        db.add(reading)
        db.commit()

    return RedirectResponse(url="/glucose", status_code=303)


@router.post("/glucose/import/libreview")
async def import_libreview(
    request: Request,
    file: UploadFile = File(...),
    timezone_name: str = Form(...),
    date_order: str = Form(...),
):
    from app.services.libre_import import parse_libreview

    content = await file.read(4 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(413, "Export is too large; choose a shorter date range.")
    try:
        rows, ignored = parse_libreview(content, timezone_name, date_order)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    user_id = request.state.user.id
    imported = skipped = 0
    with SessionLocal() as db:
        # Serialize imports per account, including overlapping uploads, on MySQL.
        db.query(models.User).filter(models.User.id == user_id).with_for_update().one()
        for row in rows:
            existing = (
                db.query(models.GlucoseReading)
                .filter_by(user_id=user_id, import_key=row["import_key"])
                .first()
            )
            if existing:
                skipped += 1
                continue
            db.add(models.GlucoseReading(user_id=user_id, active=True, **row))
            imported += 1
            db.flush()
        db.commit()
    return RedirectResponse(
        f"/glucose?imported={imported}&skipped={skipped}", status_code=303
    )


def chart_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/glucose/chart")
def glucose_chart(request: Request, hours: int = Query(12), events: bool = False):
    if hours not in (6, 12, 24):
        raise HTTPException(422, "Choose 6, 12, or 24 hours.")
    end = chart_now()
    start = end - timedelta(hours=hours)
    with SessionLocal() as db:
        readings = (
            db.query(models.GlucoseReading.timestamp, models.GlucoseReading.glucose)
            .filter(
                models.GlucoseReading.user_id == request.state.user.id,
                models.GlucoseReading.active.is_(True),
                models.GlucoseReading.timestamp >= start,
                models.GlucoseReading.timestamp <= end,
            )
            .order_by(models.GlucoseReading.timestamp, models.GlucoseReading.id)
            .all()
        )

        event_data = timeline(db, request.state.user.id, start, end) if events else None

    def utc(value):
        return value.replace(tzinfo=timezone.utc).isoformat()

    return {
        "hours": hours,
        "start": utc(start),
        "end": utc(end),
        "unit": "mg/dL",
        **({"timeline": event_data} if event_data is not None else {}),
        "readings": [
            {"time": utc(row.timestamp), "glucose": row.glucose} for row in readings
        ],
    }
