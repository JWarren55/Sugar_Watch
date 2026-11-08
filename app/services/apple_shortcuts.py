"""Small authenticated Shortcuts batches with server-owned per-category checkpoints."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.settings import settings
from app.services.apple_health import HealthImportError, parse_export, stamp

STREAMS = {
    "sleep": {"label": "Sleep", "name": "sleep_analysis", "unit": "hr"},
    "steps": {"label": "Steps", "name": "step_count", "unit": "count"},
    "active_energy": {
        "label": "Active Calories",
        "name": "active_energy",
        "unit": "kcal",
    },
    "body_weight": {"label": "Weight", "name": "weight", "unit": "lb"},
    "heart_rate": {"label": "Heart Rate", "name": "heart_rate", "unit": "bpm"},
    "resting_heart_rate": {
        "label": "Resting Heart Rate",
        "name": "resting_heart_rate",
        "unit": "bpm",
    },
    "hrv": {
        "label": "Heart Rate Variability",
        "name": "heart_rate_variability",
        "unit": "ms",
    },
}
MAX_BATCH = 200
MAX_BATCHES = 500


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(date):
    return date.isoformat(timespec="microseconds") + "Z"


def signer():
    return URLSafeTimedSerializer(settings.secret_key, salt="apple-shortcuts-plan-v1")


def make_plan(user_id, token_id, metric, cursor=None, *, now=None, force=False):
    if metric not in STREAMS:
        raise HealthImportError("Choose a supported health category.")
    now = now or now_utc()
    if cursor and cursor >= now - timedelta(hours=20) and not force:
        return {
            "status": "up_to_date",
            "metric": metric,
            "message": "Already synced recently. No Health query or upload is needed.",
        }
    # Two-day first catch-up; existing older history comes from Apple's one-time ZIP export.
    start = cursor - timedelta(days=1) if cursor else now - timedelta(days=2)
    end = min(now, cursor + timedelta(days=1)) if cursor else now - timedelta(days=1)
    if end <= start:
        raise HealthImportError("The sync range is invalid.")
    data = {
        "user_id": user_id,
        "token_id": token_id,
        "metric": metric,
        "start": iso(start),
        "end": iso(end),
        "cursor": iso(cursor) if cursor else None,
    }
    return {
        "status": "ready",
        "metric": metric,
        "start": data["start"],
        "end": data["end"],
        "plan": signer().dumps(data),
        "batch_size": MAX_BATCH,
        "message": "Send every individual sample whose start is at or after start and before end. Do not limit the Health query.",
    }


def read_plan(encoded, user_id, token_id):
    if not isinstance(encoded, str) or len(encoded) > 3000:
        raise HealthImportError("Request a new sync range.")
    try:
        data = signer().loads(encoded, max_age=24 * 60 * 60)
        if (
            data["user_id"] != user_id
            or data["token_id"] != token_id
            or data["metric"] not in STREAMS
        ):
            raise ValueError()
        start, end = stamp(data["start"]), stamp(data["end"])
        if not timedelta(0) < end - start <= timedelta(
            days=2
        ) or end > now_utc() + timedelta(minutes=5):
            raise ValueError()
        if data["cursor"] is not None:
            stamp(data["cursor"])
        return data, hashlib.sha256(encoded.encode()).hexdigest()
    except (BadSignature, ValueError, TypeError, KeyError):
        raise HealthImportError(
            "This sync range expired or belongs to another connection. Request a new range."
        )


def parse_batch(plan, records):
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_BATCH:
        raise HealthImportError("Send between 1 and 200 records in each batch.")
    stream = STREAMS[plan["metric"]]
    converted = []
    start, end = stamp(plan["start"]), stamp(plan["end"])
    for row in records:
        if not isinstance(row, dict):
            raise HealthImportError("Each sample must be a dictionary.")
        when = stamp(row.get("start"))
        if not start <= when < end:
            raise HealthImportError(
                "A sample is outside the requested start-time range."
            )
        if plan["metric"] != "sleep" and not isinstance(row.get("unit"), str):
            raise HealthImportError("Include the actual unit returned by Apple Health.")
        value = row.get("value")
        if plan["metric"] == "sleep" and isinstance(value, str):
            value = value.strip().casefold().replace("asleep (", "").replace(")", "")
        converted.append(
            {
                "start": row.get("start"),
                "end": row.get("end"),
                "source": row.get("source", ""),
                "id": row.get("id"),
                "value": value,
                "qty": value,
                "units": row.get("unit") or stream["unit"],
            }
        )
    payload = {
        "data": {
            "metrics": [
                {"name": stream["name"], "units": stream["unit"], "data": converted}
            ]
        }
    }
    rows, ignored = parse_export(payload)
    return rows


def batch_digest(records):
    return hashlib.sha256(
        json.dumps(
            records, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
