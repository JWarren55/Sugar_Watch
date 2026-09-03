from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

import models
from database import SessionLocal


router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/")
def home(request: Request):
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
        context={
            "title": "Sugar Watch",
            "user": user
        }
    )