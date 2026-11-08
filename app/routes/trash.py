"""List, restore, and permanently delete the user's inactive records."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import DateTime, String, cast, func, literal, null, select, union_all

from app.db import models
from app.db.session import SessionLocal
from app.forms.entry_rules import SECTIONS, config, owned
from app.routes.common import templates
from app.services.nutrition import from_food
from app.utils.pagination import paginate

router = APIRouter()


@router.get("/trash")
def trash_page(request: Request):
    # Combine this user's inactive records into one paged deleted-items list.

    user_id = request.state.user.id
    section = request.query_params.get("section", "all")
    if section != "all":
        config(section)
    queries = []
    for key, (model, title, _) in SECTIONS.items():
        if section not in ("all", key):
            continue
        timestamp = getattr(model, "timestamp", cast(null(), DateTime))
        summary = getattr(
            model, "name", getattr(model, "medication_name", literal(title))
        )
        if key == "food":
            summary = func.coalesce(
                models.FoodEntry.nutrition_snapshot["name"].as_string(), literal(title)
            )
        queries.append(
            select(
                literal(key).label("section"),
                model.id.label("id"),
                cast(summary, String(255)).label("summary"),
                model.deleted_at.label("deleted_at"),
                timestamp.label("timestamp"),
            ).where(model.user_id == user_id, model.active.is_(False))
        )
    records = union_all(*queries).subquery()
    with SessionLocal() as db:
        query = db.query(records).order_by(
            func.coalesce(records.c.deleted_at, records.c.timestamp).desc(),
            records.c.section,
            records.c.id.desc(),
        )
        rows, pagination = paginate(query, request)
        return templates.TemplateResponse(
            request=request,
            name="trash.html",
            context={
                "rows": rows,
                "pagination": pagination,
                "sections": SECTIONS,
                "selected_section": section,
            },
        )


@router.post("/entries/{section}/{entry_id}/restore")
def restore_entry(section: str, entry_id: int, request: Request):
    user_id = request.state.user.id
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id, active=False)
        entry.active = True
        entry.deleted_at = None
        db.commit()
    return RedirectResponse("/trash", status_code=303)


@router.get("/entries/{section}/{entry_id}/purge")
def purge_page(section: str, entry_id: int, request: Request):
    user_id = request.state.user.id
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id, active=False)
        summary = (
            getattr(entry, "name", None)
            or getattr(entry, "medication_name", None)
            or (getattr(entry, "nutrition_snapshot", None) or {}).get("name")
            or config(section)[1]
        )
        return templates.TemplateResponse(
            request=request,
            name="purge_entry.html",
            context={
                "title": config(section)[1],
                "summary": summary,
                "timestamp": getattr(entry, "timestamp", None),
            },
        )


@router.post("/entries/{section}/{entry_id}/purge")
async def purge_entry(section: str, entry_id: int, request: Request):
    # Only permanently remove owned records already in Deleted Items.
    user_id = request.state.user.id
    form = await request.form()
    if form.get("confirmation") != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm permanent deletion.")
    with SessionLocal() as db:
        entry = owned(db, section, entry_id, user_id, active=False)
        if section == "food-item":
            foreign = (
                db.query(models.FoodEntry)
                .filter(
                    models.FoodEntry.food_item_id == entry_id,
                    models.FoodEntry.user_id != user_id,
                )
                .first()
            )
            if foreign:
                raise HTTPException(
                    409,
                    "This food is referenced by another account and cannot be permanently deleted.",
                )
            references = (
                db.query(models.FoodEntry)
                .filter(
                    models.FoodEntry.food_item_id == entry_id,
                    models.FoodEntry.user_id == user_id,
                )
                .all()
            )
            for reference in references:
                if not reference.nutrition_snapshot:
                    reference.nutrition_snapshot = from_food(
                        entry, reference.amount, reference.unit, strict=False
                    )
                reference.food_item_id = None
            db.query(models.FavoriteFood).filter(
                models.FavoriteFood.food_item_id == entry_id,
                models.FavoriteFood.user_id == user_id,
            ).delete(synchronize_session=False)
            db.flush()
        db.delete(entry)
        db.commit()
    return RedirectResponse("/trash", status_code=303)
