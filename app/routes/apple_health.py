"""Owned Apple Health connection management, scoped ingestion, and sleep history."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.core.email_access import email_allowed
from app.db import models
from app.db.session import SessionLocal
from app.routes.common import templates
from app.services.apple_health import HealthImportError, asleep_seconds, parse_export
from app.services.apple_shortcuts import STREAMS
from app.utils.pagination import paginate

router = APIRouter()
KINDS = {
    "sleep": models.SleepInterval,
    "metric": models.HealthMetricSample,
    "workout": models.HealthWorkout,
}


def connection_page(request, new_token=None):
    user_id = request.state.user.id
    with SessionLocal() as db:
        native_import = (
            db.query(models.HealthNativeImport)
            .filter_by(user_id=user_id)
            .order_by(models.HealthNativeImport.id.desc())
            .first()
        )
        shortcut_progress = (
            db.query(models.HealthShortcutProgress)
            .filter_by(user_id=user_id)
            .order_by(models.HealthShortcutProgress.metric)
            .all()
        )
        token = (
            db.query(models.HealthImportToken)
            .filter_by(user_id=user_id, active=True)
            .order_by(models.HealthImportToken.id.desc())
            .first()
        )
        samples, pagination = paginate(
            db.query(models.HealthMetricSample)
            .filter_by(user_id=user_id, active=True)
            .order_by(
                models.HealthMetricSample.start_time.desc(),
                models.HealthMetricSample.id.desc(),
            ),
            request,
        )
        workouts, workout_pagination = paginate(
            db.query(models.HealthWorkout)
            .filter_by(user_id=user_id, active=True)
            .order_by(
                models.HealthWorkout.start_time.desc(), models.HealthWorkout.id.desc()
            ),
            request,
            "workouts_",
        )
    return templates.TemplateResponse(
        request=request,
        name="apple_health.html",
        context={
            "token": token,
            "native_import": native_import,
            "shortcut_progress": shortcut_progress,
            "shortcut_streams": STREAMS,
            "new_token": new_token,
            "endpoint": str(request.url_for("import_apple_health")),
            "samples": samples,
            "pagination": pagination,
            "workouts": workouts,
            "workout_pagination": workout_pagination,
        },
    )


@router.get("/integrations/apple-health")
def apple_health_page(request: Request):
    return connection_page(request)


@router.post("/integrations/apple-health/token")
def create_import_token(request: Request):
    raw = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.query(models.User).filter_by(
            id=request.state.user.id
        ).with_for_update().one()
        db.query(models.HealthImportToken).filter_by(
            user_id=request.state.user.id, active=True
        ).update({"active": False})
        db.add(
            models.HealthImportToken(
                user_id=request.state.user.id,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                active=True,
            )
        )
        db.commit()
    return connection_page(request, raw)


@router.post("/integrations/apple-health/revoke")
def revoke_import_token(request: Request):
    with SessionLocal() as db:
        db.query(models.User).filter_by(
            id=request.state.user.id
        ).with_for_update().one()
        db.query(models.HealthImportToken).filter_by(
            user_id=request.state.user.id, active=True
        ).update({"active": False})
        db.commit()
    return RedirectResponse("/integrations/apple-health", status_code=303)


@router.post("/integrations/apple-health/import")
async def import_apple_health(request: Request):
    if (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "Send a JSON export.")
    aggregation = request.headers.get("automation-aggregation", "").strip().lower()
    if aggregation not in ("", "none", "raw", "no aggregation"):
        raise HTTPException(
            400, "Turn Summarize Data off; aggregated uploads are not accepted."
        )
    try:
        rows, ignored = parse_export(await request.json())
    except (json.JSONDecodeError, UnicodeDecodeError, HealthImportError):
        # Validation messages are fixed strings, but JSON exceptions may echo private records.
        raise HTTPException(
            400,
            "Invalid health export. Use JSON Version 2, Summarize Data off, offset-aware timestamps, and batches of at most 5000 records.",
        )
    user_id, token_id = request.state.health_import
    counts = {
        "sleep": 0,
        "metric": 0,
        "workout": 0,
        "updated": 0,
        "skipped": 0,
        "ignored": ignored,
    }
    with SessionLocal() as db:
        user = db.query(models.User).filter_by(id=user_id).with_for_update().one()
        from app.core.settings import settings

        token = (
            db.query(models.HealthImportToken)
            .filter_by(id=token_id, user_id=user_id, active=True)
            .with_for_update()
            .one_or_none()
        )
        if (
            token is None
            or not user.active
            or not email_allowed(db, user.email, settings)
        ):
            raise HTTPException(401, "A valid Apple Health import token is required.")
        existing = {}
        for kind, model in KINDS.items():
            keys = [values["import_key"] for k, values in rows if k == kind]
            for offset in range(0, len(keys), 500):
                for record in db.query(model).filter(
                    model.user_id == user_id,
                    model.import_key.in_(keys[offset : offset + 500]),
                ):
                    existing[(kind, record.import_key)] = record
        for kind, values in rows:
            record = existing.get((kind, values["import_key"]))
            if record is None:
                db.add(KINDS[kind](user_id=user_id, active=True, **values))
                counts[kind] += 1
            elif not record.active:
                counts["skipped"] += 1
            elif any(getattr(record, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(record, key, value)
                counts["updated"] += 1
            else:
                counts["skipped"] += 1
        token.last_success_at = datetime.now(timezone.utc).replace(tzinfo=None)
        token.last_counts = counts
        db.commit()
    return {"status": "ok", **counts}


@router.get("/sleep")
def sleep_page(request: Request, days: int = Query(7)):
    if days not in (7, 30):
        raise HTTPException(422, "Choose 7 or 30 days.")
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(days=days)
    with SessionLocal() as db:
        query = (
            db.query(models.SleepInterval)
            .filter(
                models.SleepInterval.user_id == request.state.user.id,
                models.SleepInterval.active.is_(True),
                models.SleepInterval.end_time >= start,
                models.SleepInterval.start_time <= end,
            )
            .order_by(
                models.SleepInterval.start_time.desc(), models.SleepInterval.id.desc()
            )
        )
        entries, pagination = paginate(query, request)
        # Clip intervals at the selected boundaries before unioning them.
        from types import SimpleNamespace

        intervals = [
            SimpleNamespace(
                start_time=max(row.start_time, start),
                end_time=min(row.end_time, end),
                stage=row.stage,
            )
            for row in query.all()
        ]
        seconds = asleep_seconds(intervals)
    return templates.TemplateResponse(
        request=request,
        name="sleep.html",
        context={
            "entries": entries,
            "pagination": pagination,
            "days": days,
            "asleep_hours": round(seconds / 3600, 2),
        },
    )
