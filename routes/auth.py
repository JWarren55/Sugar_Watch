import os

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

import models
from database import SessionLocal


load_dotenv()

router = APIRouter()


oauth = OAuth()

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    }
)


@router.get("/login")
async def login(request: Request):
    redirect_uri = request.url_for("google_callback")

    return await oauth.google.authorize_redirect(
        request,
        redirect_uri
    )


@router.get("/auth/google/callback")
async def google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)

        google_user = token.get("userinfo")

        google_id = google_user.get("sub")
        email = google_user.get("email")
        name = google_user.get("name")
        picture = google_user.get("picture")

        db = SessionLocal()

        try:
            stmt = select(models.User).where(
                models.User.google_id == google_id
            )

            user = db.scalar(stmt)

            if user is None:
                user = models.User(
                    google_id=google_id,
                    email=email,
                    name=name,
                    picture=picture
                )

                db.add(user)
                db.commit()
                db.refresh(user)

            request.session["user_id"] = user.id

        finally:
            db.close()

        return RedirectResponse(url="/")

    except Exception:
        return RedirectResponse(
            url="/?login=cancelled"
        )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()

    return RedirectResponse(url="/")