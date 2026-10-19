from fastapi import APIRouter, Request

import models
from database import SessionLocal
from routes.common import templates

router = APIRouter()


@router.get("/")
def home(request: Request):
    # Show the home page with the current account, if signed in.
    user = None
    user_id = request.session.get("user_id")

    if user_id:
        db = SessionLocal()

        try:
            user = db.get(models.User, user_id)
        finally:
            db.close()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Sugar Watch", "user": user},
    )
