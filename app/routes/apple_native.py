"""Free Apple Health ZIP import and checkpointed Apple Shortcuts collection."""

import tempfile
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.core.email_access import email_allowed
from app.core.settings import settings
from app.db import models
from app.db.session import SessionLocal
from app.services.apple_health import HealthImportError, stamp
from app.services.apple_health_xml import records_from_zip
from app.services.apple_shortcuts import (
    MAX_BATCHES,
    STREAMS,
    batch_digest,
    make_plan,
    now_utc,
    parse_batch,
    read_plan,
)
from app.services.health_records import save_records

router = APIRouter()
MAX_ZIP_BYTES = 100 * 1024 * 1024


def lock_connection(db, user_id, token_id):
    user = db.query(models.User).filter_by(id=user_id).with_for_update().one()
    token = (
        db.query(models.HealthImportToken)
        .filter_by(id=token_id, user_id=user_id, active=True)
        .with_for_update()
        .one_or_none()
    )
    if token is None or not user.active or not email_allowed(db, user.email, settings):
        raise HTTPException(401, "Your connection key is no longer valid.")
    return token


async def json_object(request):
    if (
        request.headers.get("content-type", "").split(";")[0].lower()
        != "application/json"
    ):
        raise HTTPException(415, "Send a JSON dictionary.")
    try:
        body = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "The upload is not valid JSON.")
    if not isinstance(body, dict):
        raise HTTPException(400, "Send a JSON dictionary.")
    return body


@router.post("/integrations/apple-health/shortcuts/plan")
async def shortcut_plan(request: Request):
    body = await json_object(request)
    user_id, token_id = request.state.health_import
    with SessionLocal() as db:
        lock_connection(db, user_id, token_id)
        metric = body.get("metric")
        if not isinstance(metric, str) or metric not in STREAMS:
            raise HTTPException(
                400, "Choose one of the health categories in the setup guide."
            )
        cursor = (
            db.query(models.HealthShortcutProgress)
            .filter_by(user_id=user_id, metric=metric)
            .first()
        )
        # Confirmation is a client-side guard, not proof of the transport used by iOS.
        if body.get("on_wifi") is not True:
            raise HTTPException(400, "Connect to Wi-Fi before running this shortcut.")
        plan = make_plan(
            user_id,
            token_id,
            metric,
            cursor.completed_until if cursor else None,
            force=body.get("force") is True,
        )
        db.query(models.HealthShortcutBatch).filter(
            models.HealthShortcutBatch.user_id == user_id,
            models.HealthShortcutBatch.created_at < now_utc() - timedelta(days=30),
        ).delete()
        db.commit()
    return plan


@router.post("/integrations/apple-health/shortcuts/batch")
async def shortcut_batch(request: Request):
    body = await json_object(request)
    user_id, token_id = request.state.health_import
    try:
        plan, identifier = read_plan(body.get("plan"), user_id, token_id)
        index = body.get("index")
        if type(index) is not int or not 0 <= index < MAX_BATCHES:
            raise HealthImportError("The batch number is invalid.")
        records = body.get("records")
        rows = parse_batch(plan, records)
        digest = batch_digest(records)
    except (HealthImportError, ValueError, TypeError):
        raise HTTPException(
            400,
            "This batch is invalid. Check the dates, units, and selected health category; send at most 200 records.",
        )
    with SessionLocal() as db:
        token = lock_connection(db, user_id, token_id)
        batch = (
            db.query(models.HealthShortcutBatch)
            .filter_by(user_id=user_id, plan_hash=identifier, batch_index=index)
            .first()
        )
        if batch:
            if batch.payload_hash != digest:
                raise HTTPException(
                    409,
                    "This batch number was already used for different records. Request a new sync range.",
                )
            return {
                "status": "ok",
                "index": index,
                "received": batch.record_count,
                "repeated": True,
            }
        counts = save_records(db, user_id, rows)
        db.add(
            models.HealthShortcutBatch(
                user_id=user_id,
                plan_hash=identifier,
                batch_index=index,
                payload_hash=digest,
                record_count=len(records),
            )
        )
        token.last_success_at, token.last_counts = now_utc(), counts
        db.commit()
    return {"status": "ok", "index": index, "received": len(records), **counts}


@router.post("/integrations/apple-health/shortcuts/complete")
async def shortcut_complete(request: Request):
    body = await json_object(request)
    user_id, token_id = request.state.health_import
    try:
        plan, identifier = read_plan(body.get("plan"), user_id, token_id)
    except HealthImportError:
        raise HTTPException(400, "Request a new sync range before marking it complete.")
    total, records = body.get("batches"), body.get("records")
    if (
        type(total) is not int
        or not 0 <= total <= MAX_BATCHES
        or type(records) is not int
        or not 0 <= records <= 200 * MAX_BATCHES
    ):
        raise HTTPException(400, "Invalid completion counts.")
    with SessionLocal() as db:
        lock_connection(db, user_id, token_id)
        batches = (
            db.query(models.HealthShortcutBatch)
            .filter_by(user_id=user_id, plan_hash=identifier)
            .all()
        )
        if {item.batch_index for item in batches} != set(range(total)) or sum(
            item.record_count for item in batches
        ) != records:
            raise HTTPException(
                409,
                "Some batches have not arrived. Sync progress was not advanced; retry the missing batches.",
            )
        progress = (
            db.query(models.HealthShortcutProgress)
            .filter_by(user_id=user_id, metric=plan["metric"])
            .first()
        )
        expected = stamp(plan["cursor"]) if plan["cursor"] else None
        end = stamp(plan["end"])
        if progress and progress.completed_until >= end:
            return {
                "status": "ok",
                "completed_until": progress.completed_until.isoformat() + "Z",
                "repeated": True,
            }
        if (progress.completed_until if progress else None) != expected:
            raise HTTPException(
                409, "Another sync finished first. Request a fresh range."
            )
        if progress is None:
            progress = models.HealthShortcutProgress(
                user_id=user_id, metric=plan["metric"], completed_until=end
            )
            db.add(progress)
        else:
            progress.completed_until = end
        progress.last_completed_at = now_utc()
        db.commit()
    return {"status": "ok", "completed_until": plan["end"], "received": records}


def import_native_file(file, user_id):
    counts = dict(sleep=0, metric=0, workout=0, updated=0, skipped=0)
    stats = {"unsupported": 0}
    with SessionLocal() as db:
        user = db.query(models.User).filter_by(id=user_id).with_for_update().one()
        if not user.active or not email_allowed(db, user.email, settings):
            raise HTTPException(401, "Sign in again before importing.")
        pending = []
        for record in records_from_zip(file, stats):
            pending.append(record)
            if len(pending) == 500:
                added = save_records(db, user_id, pending)
                for key in counts:
                    counts[key] += added[key]
                pending = []
        if pending:
            added = save_records(db, user_id, pending)
            for key in counts:
                counts[key] += added[key]
        if not any(counts.values()):
            raise HealthImportError(
                "No supported sleep, activity, weight, heart, or workout records were found."
            )
        # Commit only after the entire XML validates, including records after the last chunk.
        db.add(models.HealthNativeImport(user_id=user_id, counts={**counts, **stats}))
        db.commit()
    return {"status": "ok", **counts, **stats}


@router.post("/integrations/apple-health/native-import")
async def native_import(request: Request):
    if request.headers.get("content-type", "").split(";")[0].lower() not in (
        "application/zip",
        "application/octet-stream",
        "application/x-zip-compressed",
    ):
        raise HTTPException(415, "Choose the original export.zip from Apple Health.")
    # ASGI middleware enforces this same limit while streaming, without buffering 100 MB.
    with tempfile.TemporaryFile() as file:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_ZIP_BYTES:
                raise HTTPException(413, "Choose an export.zip smaller than 100 MB.")
            file.write(chunk)
        file.seek(0)
        try:
            return await run_in_threadpool(
                import_native_file, file, request.state.user.id
            )
        except HealthImportError as exc:
            raise HTTPException(400, str(exc))


@router.get("/integrations/apple-health/shortcuts/setup")
def shortcut_setup(request: Request):
    from app.routes.common import templates

    base = str(request.base_url).rstrip("/") + "/integrations/apple-health/shortcuts/"
    return templates.TemplateResponse(
        request=request,
        name="apple_shortcuts_setup.html",
        context={
            "base": base,
            "streams": STREAMS,
            "units": {
                "steps": "count",
                "active_energy": "kcal or kJ",
                "body_weight": "lb, lbs, or kg",
                "heart_rate": "bpm or count/min",
                "resting_heart_rate": "bpm or count/min",
                "hrv": "ms or s",
            },
        },
    )
