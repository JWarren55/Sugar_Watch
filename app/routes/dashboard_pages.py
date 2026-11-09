from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import models
from app.db.session import SessionLocal
from app.routes.common import templates
from app.services.dashboard import NUTRIENTS, daily_summary, owned
from app.utils.pagination import paginate
from app.utils.time_utils import LEGACY_TIMEZONE, utc_now

router = APIRouter()

# These are user data views. Authentication, import credentials, and internal
# receipts are deliberately outside the selectable columns and models.
LOGS = {
    "glucose": (
        "Glucose",
        models.GlucoseReading,
        "timestamp glucose source",
        "/glucose#history",
    ),
    "food": (
        "Food",
        models.FoodEntry,
        "timestamp nutrition_snapshot amount unit",
        "/food#history",
    ),
    "foods": (
        "Saved foods",
        models.FoodItem,
        "name brand serving_size serving_unit calories carbs protein fat barcode source",
        "/food#saved-foods",
    ),
    "exercise": (
        "Exercise",
        models.ExerciseEntry,
        "timestamp exercise_type length_minutes intensity average_heart_rate peak_heart_rate distance",
        "/exercise#history",
    ),
    "medication": (
        "Medication",
        models.MedicationEntry,
        "timestamp medication_name dose unit",
        "/medication#history",
    ),
    "mood": (
        "Mood",
        models.MoodEntry,
        "timestamp feeling hunger head",
        "/mood#history",
    ),
    "measurements": (
        "Measurements",
        models.HealthHistory,
        "timestamp weight waist",
        "/health#history",
    ),
    "sleep": (
        "Sleep",
        models.SleepInterval,
        "start_time end_time stage source_name",
        "/sleep",
    ),
    "vitals": (
        "Apple Health samples",
        models.HealthMetricSample,
        "start_time end_time metric value unit source_name",
        "/integrations/apple-health#samples",
    ),
    "workouts": (
        "Apple Health workouts",
        models.HealthWorkout,
        "start_time end_time activity_type active_duration_seconds energy_kcal distance_miles source_name",
        "/integrations/apple-health#workouts",
    ),
}
LOG_LABELS = {
    "timestamp": "Date and time",
    "nutrition_snapshot": "Food",
    "glucose": "Glucose (mg/dL)",
    "length_minutes": "Duration (min)",
    "distance": "Distance (mi)",
    "weight": "Weight (lb)",
    "waist": "Waist (in)",
    "calories": "Calories (kcal)",
    "carbs": "Carbs (g)",
    "protein": "Protein (g)",
    "fat": "Fat (g)",
    "active_duration_seconds": "Duration (sec)",
    "energy_kcal": "Energy (kcal)",
    "distance_miles": "Distance (mi)",
    "average_heart_rate": "Average heart rate (bpm)",
    "peak_heart_rate": "Peak heart rate (bpm)",
}
Goal = Annotated[float, Form(gt=0, le=100000, allow_inf_nan=False)]


@router.get("/dashboard/summary")
def summary(request: Request, zone: str = Query(LEGACY_TIMEZONE, max_length=100)):
    with SessionLocal() as db:
        return daily_summary(db, request.state.user.id, zone, utc_now())


@router.get("/insight")
def insight(request: Request):
    return templates.TemplateResponse(request=request, name="insight.html")


@router.get("/logs")
def logs(request: Request, log: str = "glucose"):
    if log not in LOGS:
        raise HTTPException(404, "Choose an available log.")
    label, model, fields, manage = LOGS[log]
    columns = fields.split()
    first = getattr(model, columns[0])
    with SessionLocal() as db:
        rows, pagination = paginate(
            owned(db, model, request.state.user.id).order_by(
                first.desc(), model.id.desc()
            ),
            request,
        )
    if log == "food":
        columns.extend(NUTRIENTS)
        entries = []
        for row in rows:
            snapshot = row.nutrition_snapshot or {}
            totals = snapshot.get("totals", {})
            entries.append(
                {
                    "timestamp": row.timestamp,
                    "amount": row.amount,
                    "unit": row.unit,
                    "nutrition_snapshot": snapshot.get("name"),
                    **{key: totals.get(key) for key in NUTRIENTS},
                }
            )
        rows = entries
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "logs": LOGS,
            "log": log,
            "label": label,
            "columns": columns,
            "labels": LOG_LABELS,
            "rows": rows,
            "manage": manage,
            "pagination": pagination,
        },
    )


@router.get("/settings")
def dashboard_settings(request: Request):
    with SessionLocal() as db:
        user_id = request.state.user.id
        goals = db.get(models.NutritionGoal, user_id)
        openai_key_saved = db.get(models.OpenAICredential, user_id) is not None
    return templates.TemplateResponse(
        request=request,
        name="dashboard_settings.html",
        context={
            "goals": goals,
            "user": request.state.user,
            "openai_key_saved": openai_key_saved,
        },
    )


@router.post("/settings/nutrition")
def save_nutrition_goals(
    request: Request, calories: Goal, carbs: Goal, protein: Goal, fat: Goal
):
    values = dict(calories=calories, carbs=carbs, protein=protein, fat=fat)
    with SessionLocal() as db:
        table = models.NutritionGoal.__table__
        data = dict(user_id=request.state.user.id, **values)
        if db.bind.dialect.name == "mysql":
            statement = (
                mysql_insert(table).values(data).on_duplicate_key_update(**values)
            )
        else:
            statement = (
                sqlite_insert(table)
                .values(data)
                .on_conflict_do_update(
                    index_elements=[table.c.user_id],
                    set_=values,
                )
            )
        db.execute(statement)
        db.commit()
    return RedirectResponse(
        "/settings?nutrition=saved#nutrition-goals", status_code=303
    )
