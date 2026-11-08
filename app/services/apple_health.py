"""Normalize individual health samples from the supported interchange format."""

import hashlib
import json
from datetime import datetime, timezone
from math import isfinite


class HealthImportError(ValueError):
    pass


METRICS = {
    "step_count": ("steps", "count"),
    "active_energy": ("active_energy", "kcal"),
    "active_energy_burned": ("active_energy", "kcal"),
    "weight_body_mass": ("body_weight", "lb"),
    "body_mass": ("body_weight", "lb"),
    "weight": ("body_weight", "lb"),
    "resting_heart_rate": ("resting_heart_rate", "bpm"),
    "heart_rate": ("heart_rate", "bpm"),
    "heart_rate_variability": ("heart_rate_variability", "ms"),
    "heart_rate_variability_sdnn": ("heart_rate_variability", "ms"),
}
STAGES = {
    "in bed": "in_bed",
    "inbed": "in_bed",
    "in_bed": "in_bed",
    "awake": "awake",
    "asleep": "asleep",
    "unspecified": "asleep",
    "core": "core",
    "deep": "deep",
    "rem": "rem",
}


def stamp(value):
    if not isinstance(value, str):
        raise HealthImportError("Records must include timestamps with UTC offsets.")
    try:
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
        if date.tzinfo is None:
            raise ValueError()
        return date.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise HealthImportError(
            "Records must include valid timestamps with UTC offsets."
        )


def number(value):
    try:
        if isinstance(value, bool):
            raise ValueError()
        value = float(value)
        if not isfinite(value) or value < 0:
            raise ValueError()
        return value
    except (ValueError, TypeError, OverflowError):
        raise HealthImportError("Health quantities must be finite and nonnegative.")


def convert(value, unit, target):
    unit = str(unit).strip().lower()
    factors = {
        "count": {"count": 1},
        "bpm": {"bpm": 1, "count/min": 1},
        "ms": {"ms": 1, "s": 1000},
        "lb": {"lb": 1, "lbs": 1, "kg": 2.2046226218488},
        "kcal": {"kcal": 1, "kj": 1 / 4.184},
        "mi": {"mi": 1, "mile": 1, "km": 1 / 1.609344, "m": 1 / 1609.344},
    }
    if unit not in factors[target]:
        raise HealthImportError(
            "An exported unit is unsupported. Check the selected measurement units."
        )
    result = number(value) * factors[target][unit]
    if not isfinite(result):
        raise HealthImportError("A converted quantity is too large.")
    return result


def metadata(row):
    source = row.get("source", "")
    if isinstance(source, dict):
        source = source.get("name", "")
    if not isinstance(source, str) or len(source) > 255:
        raise HealthImportError("Invalid recording source.")
    external = row.get("id") or row.get("uuid")
    if external is not None and (not isinstance(external, str) or len(external) > 255):
        raise HealthImportError("Invalid source record identifier.")
    return {
        "source": "apple_health",
        "source_name": source or None,
        "external_id": external,
    }


def fingerprint(kind, values):
    identity = [kind, values.get("metric"), values.get("stage"), values["source_name"]]
    if values["external_id"]:
        identity += [values["external_id"]]
    else:
        identity += [values["start_time"].isoformat(), values["end_time"].isoformat()]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def parse_export(payload):
    if not isinstance(payload, dict):
        raise HealthImportError("Expected a health-record JSON object.")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise HealthImportError("Expected a health-record data object.")
    metrics, workouts = data.get("metrics", []), data.get("workouts", [])
    if (
        not isinstance(metrics, list)
        or not isinstance(workouts, list)
        or len(metrics) > 100
    ):
        raise HealthImportError("Invalid health export collections.")
    result, ignored, recognized, count = (
        {},
        0,
        ("workouts" in data or ("metrics" in data and not metrics)),
        0,
    )

    def add(kind, values):
        key = fingerprint(kind, values)
        values["import_key"] = key
        result[(kind, key)] = values

    for metric in metrics:
        if not isinstance(metric, dict) or not isinstance(metric.get("data"), list):
            raise HealthImportError("Invalid health metric collection.")
        name = metric.get("name")
        if not isinstance(name, str):
            raise HealthImportError("Invalid metric name.")
        count += len(metric["data"])
        if count + len(workouts) > 5000:
            raise HealthImportError(
                "Export at most 5000 records per request. Enable batch requests."
            )
        if name not in METRICS and name != "sleep_analysis":
            ignored += len(metric["data"])
            continue
        recognized = True
        for row in metric["data"]:
            if not isinstance(row, dict):
                raise HealthImportError("Invalid health record.")
            values = metadata(row)
            values["start_time"] = stamp(
                row.get("start") or row.get("startDate") or row.get("date")
            )
            values["end_time"] = stamp(
                row.get("end") or row.get("endDate") or row.get("date")
            )
            if values["end_time"] < values["start_time"]:
                raise HealthImportError("A record ends before it starts.")
            if name == "sleep_analysis":
                stage = STAGES.get(str(row.get("value", "")).strip().lower())
                if stage is None or values["end_time"] <= values["start_time"]:
                    raise HealthImportError(
                        "Sleep requires individual stages and start/end times. Turn Summarize Data off."
                    )
                values["stage"] = stage
                add("sleep", values)
            else:
                target, unit = METRICS[name]
                raw_value = row.get("qty")
                if raw_value is None and name == "heart_rate":
                    raw_value = row.get("Avg")
                value = convert(
                    raw_value, row.get("units") or metric.get("units"), unit
                )
                if target == "steps" and value != int(value):
                    raise HealthImportError(
                        "Step counts must be whole numbers. Export individual samples."
                    )
                values.update(metric=target, unit=unit, value=value)
                add("metric", values)
    if len(workouts) > 5000:
        raise HealthImportError("Export at most 5000 records per request.")
    for row in workouts:
        recognized = True
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not 0 < len(row["name"].strip()) <= 100
            or not row.get("id")
        ):
            raise HealthImportError(
                "Workouts require a name and source identifier; use export version 2."
            )
        values = metadata(row)
        values.update(
            start_time=stamp(row.get("start")),
            end_time=stamp(row.get("end")),
            activity_type=row["name"].strip(),
            active_duration_seconds=number(row.get("duration")),
        )
        if values["end_time"] <= values["start_time"]:
            raise HealthImportError("Workout end must be after its start.")
        for field, exported, unit in (
            ("energy_kcal", "activeEnergyBurned", "kcal"),
            ("distance_miles", "distance", "mi"),
        ):
            quantity = row.get(exported)
            if quantity is not None:
                if not isinstance(quantity, dict):
                    raise HealthImportError("Invalid workout quantity.")
                values[field] = convert(
                    quantity.get("qty"), quantity.get("units"), unit
                )
        add("workout", values)
    if not recognized:
        raise HealthImportError(
            "No supported health data found. Select Sleep, Steps, Active Energy, Weight, Heart Rate, HRV, or Workouts."
        )
    return [(kind, values) for (kind, _), values in result.items()], ignored


def asleep_seconds(rows):
    """Union asleep intervals, excluding in-bed/awake and overlapping duplicate sources."""
    intervals = sorted(
        (r.start_time, r.end_time)
        for r in rows
        if r.stage in ("asleep", "core", "deep", "rem")
    )
    end = None
    total = 0
    for start, stop in intervals:
        if end is None or start > end:
            total += (stop - start).total_seconds()
        elif stop > end:
            total += (stop - end).total_seconds()
        end = max(end, stop) if end is not None else stop
    return total
