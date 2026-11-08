"""Optional, unofficial LibreLinkUp client. No credentials or raw payloads in logs."""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx


class SyncError(Exception):
    """A safe diagnostic suitable for operator logs."""


@dataclass(frozen=True, repr=False)
class SyncConfig:
    email: str
    password: str
    region: str
    version: str
    patient_id: str
    user_id: int

    @classmethod
    def from_mapping(cls, env):
        required = (
            "LIBRELINKUP_EMAIL",
            "LIBRELINKUP_PASSWORD",
            "LIBRELINKUP_REGION",
            "LIBRELINKUP_VERSION",
            "LIBRELINKUP_PATIENT_ID",
            "LIBRELINKUP_USER_ID",
        )
        if any(not env.get(key, "").strip() for key in required):
            raise SyncError(
                "Libre sync is not configured; complete the protected sync environment file."
            )
        try:
            user_id = int(env["LIBRELINKUP_USER_ID"])
        except ValueError:
            raise SyncError(
                "LIBRELINKUP_USER_ID must be a positive application user ID."
            )
        region = env["LIBRELINKUP_REGION"].lower()
        if user_id <= 0 or region not in (
            "us",
            "eu",
            "eu2",
            "ca",
            "au",
            "ap",
            "de",
            "fr",
            "jp",
            "la",
            "ae",
        ):
            raise SyncError(
                "Invalid application user ID or unsupported LibreLinkUp region."
            )
        patient = env["LIBRELINKUP_PATIENT_ID"].strip()
        if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", patient):
            raise SyncError("Invalid LibreLinkUp patient identifier.")
        version = env["LIBRELINKUP_VERSION"].strip()
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise SyncError(
                "LIBRELINKUP_VERSION must be the supported app version, such as 4.16.0."
            )
        return cls(
            env[required[0]], env[required[1]], region, version, patient, user_id
        )


def _payload(response):
    if response.status_code == 429:
        raise SyncError(
            "LibreLinkUp rate limited the request; wait until the next scheduled run."
        )
    if response.status_code != 200:
        raise SyncError(
            "LibreLinkUp request failed; check account access, service availability, and app compatibility."
        )
    try:
        payload = response.json()
    except ValueError:
        raise SyncError("LibreLinkUp returned an unsupported response.")
    if not isinstance(payload, dict) or payload.get("status") != 0:
        raise SyncError(
            "LibreLinkUp rejected the request; finish account verification and any consent in the official app."
        )
    return payload.get("data")


def normalize_graph(data, patient_id):
    if not isinstance(data, dict) or not isinstance(data.get("graphData"), list):
        raise SyncError("LibreLinkUp glucose response format changed.")
    connection = data.get("connection", {})
    if connection.get("patientId") != patient_id:
        raise SyncError(
            "Glucose response does not match the configured patient; nothing was saved."
        )
    points = list(data["graphData"])
    latest = connection.get("glucoseMeasurement")
    if latest:
        points.append(latest)
    if not points:
        raise SyncError(
            "LibreLinkUp has no readings available. Check sharing in the official app."
        )
    rows = {}
    for point in points:
        try:
            # FactoryTimestamp is the provider's UTC clock; do not use local Timestamp.
            stamp = point["FactoryTimestamp"]
            try:
                instant = datetime.strptime(stamp, "%m/%d/%Y %I:%M:%S %p")
            except ValueError:
                instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if instant.tzinfo:
                    instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
            value = Decimal(str(point["ValueInMgPerDl"]))
            if (
                not value.is_finite()
                or value != value.to_integral_value()
                or not 20 <= value <= 600
            ):
                raise ValueError()
            glucose = int(value)
        except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
            raise SyncError(
                "LibreLinkUp returned an unsupported reading; no readings were saved."
            )
        identity = f"librelinkup|{patient_id}|{instant.isoformat()}"
        key = hashlib.sha256(identity.encode()).hexdigest()
        row = dict(
            timestamp=instant, glucose=glucose, source="librelinkup", import_key=key
        )
        if key in rows and rows[key] != row:
            raise SyncError(
                "LibreLinkUp returned conflicting readings; nothing was saved."
            )
        rows[key] = row
    return list(rows.values())


def fetch_readings(config, client):
    base = f"https://api-{config.region}.libreview.io"
    headers = {"product": "llu.ios", "version": config.version}
    try:
        data = _payload(
            client.post(
                base + "/llu/auth/login",
                headers=headers,
                json={"email": config.email, "password": config.password},
            )
        )
        if not isinstance(data, dict) or data.get("redirect"):
            raise SyncError("Check LIBRELINKUP_REGION against the account's region.")
        token = data.get("authTicket", {}).get("token")
        account = data.get("user", {}).get("id")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(account, str)
            or not account
        ):
            raise SyncError("LibreLinkUp login requires attention in the official app.")
        headers.update(
            {
                "Authorization": "Bearer " + token,
                "account-id": hashlib.sha256(account.encode()).hexdigest(),
            }
        )
        connections = _payload(client.get(base + "/llu/connections", headers=headers))
        if not isinstance(connections, list) or not any(
            isinstance(c, dict) and c.get("patientId") == config.patient_id
            for c in connections
        ):
            raise SyncError(
                "Configured patient is not shared with this LibreLinkUp account."
            )
        graph = _payload(
            client.get(
                base + f"/llu/connections/{config.patient_id}/graph", headers=headers
            )
        )
        return normalize_graph(graph, config.patient_id)
    except httpx.HTTPError:
        raise SyncError(
            "Unable to reach LibreLinkUp; the next scheduled run will retry."
        )


def save_readings(session_factory, user_id, rows):
    from sqlalchemy import tuple_

    from app.core.email_access import email_allowed
    from app.core.settings import settings
    from app.db import models

    with session_factory() as db:
        user = (
            db.query(models.User).filter_by(id=user_id).with_for_update().one_or_none()
        )
        if (
            user is None
            or not user.active
            or not email_allowed(db, user.email, settings)
        ):
            raise SyncError(
                "Target application account is missing, inactive, or not allowed."
            )
        # Include soft-deleted records so sync cannot resurrect them.
        keys = [row["import_key"] for row in rows]
        known = {
            key
            for (key,) in db.query(models.GlucoseReading.import_key).filter(
                models.GlucoseReading.user_id == user_id,
                models.GlucoseReading.import_key.in_(keys),
            )
        }
        # Also avoid exact overlapping CSV readings. Different sampling times remain distinct.
        matches = {
            (stamp, value)
            for stamp, value in db.query(
                models.GlucoseReading.timestamp, models.GlucoseReading.glucose
            ).filter(
                models.GlucoseReading.user_id == user_id,
                models.GlucoseReading.source.in_(("libreview", "librelinkup")),
                tuple_(
                    models.GlucoseReading.timestamp, models.GlucoseReading.glucose
                ).in_([(r["timestamp"], r["glucose"]) for r in rows]),
            )
        }
        added = 0
        for row in rows:
            identity = (row["timestamp"], row["glucose"])
            if row["import_key"] in known or identity in matches:
                continue
            db.add(models.GlucoseReading(user_id=user_id, active=True, **row))
            known.add(row["import_key"])
            matches.add(identity)
            added += 1
        db.commit()
    return added, len(rows) - added
