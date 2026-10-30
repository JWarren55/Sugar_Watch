"""Keep database timestamps in UTC and translate only at the display boundary."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from markupsafe import Markup, escape

LEGACY_TIMEZONE = "America/Chicago"


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc(value, zone=LEGACY_TIMEZONE):
    # Accept offset-aware API timestamps or convert local form values explicitly.
    if value is None:
        return utc_now()
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(400, "Enter a valid date and time.") from exc
    if value.tzinfo is None:
        try:
            local_zone = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(400, "Choose a valid timezone.") from exc
        local = value.replace(tzinfo=local_zone)
        if (
            local.astimezone(timezone.utc).astimezone(local_zone).replace(tzinfo=None)
            != value
        ):
            raise HTTPException(
                400, "That local time does not exist due to daylight saving time."
            )
        value = local
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_iso(value):
    return (
        value.replace(tzinfo=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
        if value
        else ""
    )


def local_time(value):
    # Show an explicit UTC fallback until the browser translates the timestamp.
    if not value:
        return "-"
    return Markup('<time class="local-time" datetime="{}">{} UTC</time>').format(
        escape(utc_iso(value)), escape(value.strftime("%Y-%m-%d %H:%M:%S"))
    )
