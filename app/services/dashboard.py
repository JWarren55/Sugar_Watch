"""Account-owned data for the home dashboard and its glucose timeline."""

from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func

from app.db import models
from app.services.apple_health import asleep_intervals, asleep_seconds
from app.utils.time_utils import to_utc, utc_iso

NUTRIENTS = ("calories", "carbs", "protein", "fat")


def owned(db, model, user_id):
    return db.query(model).filter_by(user_id=user_id, active=True)


def timed(db, model, user_id, start, end):
    return owned(db, model, user_id).filter(
        model.timestamp >= start, model.timestamp <= end
    )


def overlapping(db, model, user_id, start, end):
    return owned(db, model, user_id).filter(
        model.end_time >= start, model.start_time <= end
    )


def food_snapshot(row):
    return row.nutrition_snapshot or {}


def timeline(db, user_id, start, end):
    events, workouts = [], []

    def event(kind, instant, label):
        if start <= instant <= end:
            events.append((instant, kind, label))

    def workout(begin, stop, label):
        if stop >= start and begin <= end:
            workouts.append(
                {"start": utc_iso(max(start, begin)), "end": utc_iso(min(end, stop))}
            )
            event(
                "exercise",
                max(start, begin),
                label if begin >= start else f"{label} in progress",
            )

    for row in timed(db, models.FoodEntry, user_id, start, end):
        event("food", row.timestamp, food_snapshot(row).get("name", "Food entry"))
    for row in timed(db, models.MedicationEntry, user_id, start, end):
        event("medication", row.timestamp, row.medication_name)
    for row in timed(db, models.MoodEntry, user_id, start, end):
        event("mood", row.timestamp, row.feeling or "Mood entry")
    for row in timed(db, models.HealthHistory, user_id, start, end):
        event("measurement", row.timestamp, "Body measurement")

    # Manual exercise records store a start and duration. Filter by elapsed
    # duration in Python, since date arithmetic differs between SQLite and MySQL.
    for timestamp, minutes, label in (
        owned(db, models.ExerciseEntry, user_id)
        .filter(models.ExerciseEntry.timestamp <= end)
        .with_entities(
            models.ExerciseEntry.timestamp,
            models.ExerciseEntry.length_minutes,
            models.ExerciseEntry.exercise_type,
        )
    ):
        elapsed = (max(start, timestamp) - timestamp).total_seconds() / 60
        if minutes >= elapsed:
            visible = (end - timestamp).total_seconds() / 60
            stop = end if minutes >= visible else timestamp + timedelta(minutes=minutes)
            workout(timestamp, stop, label)
    for row in overlapping(db, models.HealthWorkout, user_id, start, end):
        workout(row.start_time, row.end_time, row.activity_type)

    sleep = overlapping(db, models.SleepInterval, user_id, start, end)
    for begin, stop in asleep_intervals(sleep):
        event(
            "sleep",
            max(start, begin),
            "Sleep" if begin >= start else "Sleep in progress",
        )
        event("wake", stop, "Wake up")

    for row in overlapping(db, models.HealthMetricSample, user_id, start, end):
        event(
            "apple",
            max(start, row.start_time),
            row.metric.replace("_", " ").capitalize(),
        )

    return {
        "events": [
            {"time": utc_iso(instant), "kind": kind, "label": label}
            for instant, kind, label in sorted(events)
        ],
        "workouts": workouts,
    }


def daily_summary(db, user_id, zone, now):
    try:
        local_zone = ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(422, "Choose a valid timezone.") from exc
    today = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(local_zone).date()
    start = to_utc(datetime.combine(today, time.min, local_zone))

    totals = dict.fromkeys(NUTRIENTS, 0)
    known = set()
    food = list(timed(db, models.FoodEntry, user_id, start, now))
    incomplete = 0
    for row in food:
        values = food_snapshot(row).get("totals", {})
        if any(values.get(key) is None for key in NUTRIENTS):
            incomplete += 1
        for key in NUTRIENTS:
            if values.get(key) is not None:
                totals[key] += values[key]
                known.add(key)

    goal = db.get(models.NutritionGoal, user_id)
    metric = models.HealthMetricSample
    timed_metrics = owned(db, metric, user_id).filter(metric.start_time <= now)
    heart_rate = (
        timed_metrics.filter(metric.metric == "heart_rate", metric.start_time >= start)
        .with_entities(func.avg(metric.value))
        .scalar()
    )

    # Count matching imported intervals once and prorate intervals crossing midnight.
    energy_samples = (
        timed_metrics.filter(metric.metric == "active_energy", metric.end_time >= start)
        .with_entities(metric.start_time, metric.end_time, func.max(metric.value))
        .group_by(metric.start_time, metric.end_time)
        .all()
    )
    energy = 0
    for begin, stop, value in energy_samples:
        if stop > begin:
            duration = max(0, (min(stop, now) - max(begin, start)).total_seconds())
            value *= duration / (stop - begin).total_seconds()
        energy += value

    sleep = list(overlapping(db, models.SleepInterval, user_id, start, now))
    sleep_seconds = asleep_seconds(
        SimpleNamespace(
            start_time=max(start, row.start_time),
            end_time=min(now, row.end_time),
            stage=row.stage,
        )
        for row in sleep
    )
    last_import = max(
        (
            stamp
            for model, field in (
                (models.HealthNativeImport, models.HealthNativeImport.created_at),
                (models.HealthImportToken, models.HealthImportToken.last_success_at),
                (
                    models.HealthShortcutProgress,
                    models.HealthShortcutProgress.last_completed_at,
                ),
            )
            if (
                stamp := db.query(func.max(field))
                .filter(model.user_id == user_id)
                .scalar()
            )
        ),
        default=None,
    )

    return {
        "date": today.isoformat(),
        "nutrition": {
            key: round(totals[key], 1) if key in known or not food else None
            for key in NUTRIENTS
        },
        "incomplete_food_entries": incomplete,
        "goals": {key: getattr(goal, key) if goal else None for key in NUTRIENTS},
        "heart_rate": round(heart_rate) if heart_rate is not None else None,
        "active_energy": round(energy) if energy_samples else None,
        "sleep_minutes": round(sleep_seconds / 60) if sleep else None,
        "apple_updated": utc_iso(last_import),
    }
