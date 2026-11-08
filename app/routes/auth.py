import logging
import os

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.email_access import email_allowed
from app.core.settings import settings
from app.db import models
from app.db.session import SessionLocal
from app.routes.common import templates

router = APIRouter()
logger = logging.getLogger(__name__)


oauth = OAuth()

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/login")
async def login(request: Request):
    # Switch hosts before creating OAuth state so the callback keeps its session.
    if request.url.hostname == "localhost":
        return RedirectResponse(
            str(request.url.replace(hostname="127.0.0.1")), status_code=307
        )
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        return RedirectResponse("/?login=configuration", status_code=303)
    redirect_uri = request.url_for("google_callback")

    try:
        return await oauth.google.authorize_redirect(request, redirect_uri)
    except Exception as exc:
        logger.error("Google sign-in could not start (%s)", type(exc).__name__)
        return RedirectResponse("/?login=provider", status_code=303)


@router.get("/auth/google/callback")
async def google_callback(request: Request):
    # Find or create the Google account, then save its ID in the session.
    if request.query_params.get("error"):
        result = (
            "cancelled"
            if request.query_params["error"] == "access_denied"
            else "provider"
        )
        return RedirectResponse("/?login=" + result, status_code=303)
    try:
        token = await oauth.google.authorize_access_token(request)

        google_user = token.get("userinfo") or {}
        if not google_user.get("sub") or not google_user.get("email"):
            return RedirectResponse("/?login=profile", status_code=303)

        email = google_user.get("email")
        if google_user.get("email_verified") is not True:
            request.session.clear()
            return RedirectResponse("/?login=unauthorized", status_code=303)

        google_id = google_user.get("sub")
        email = google_user.get("email")
        name = google_user.get("name")
        picture = google_user.get("picture")

        with SessionLocal() as db:
            if not email_allowed(db, email, settings):
                request.session.clear()
                return RedirectResponse("/?login=unauthorized", status_code=303)
            stmt = select(models.User).where(models.User.google_id == google_id)

            user = db.scalar(stmt)

            if user is None:
                user = models.User(
                    google_id=google_id, email=email, name=name, picture=picture
                )

                db.add(user)
                db.commit()
                db.refresh(user)

            # Refresh the stored address only after Google verifies authorization.
            if user.email != email:
                user.email = email
                db.commit()
            if not user.active:
                return RedirectResponse("/?login=inactive", status_code=303)
            request.session.clear()
            request.session["user_id"] = user.id

        return RedirectResponse(url="/")

    except OAuthError as exc:
        result = {
            "access_denied": "cancelled",
            "mismatching_state": "session",
        }.get(exc.error, "provider")
        logger.error("Google sign-in failed (%s)", type(exc).__name__)
        return RedirectResponse("/?login=" + result, status_code=303)
    except SQLAlchemyError as exc:
        logger.error("Sign-in database request failed (%s)", type(exc).__name__)
        return RedirectResponse("/?login=database", status_code=303)
    except Exception as exc:
        logger.error("Sign-in callback failed (%s)", type(exc).__name__)
        return RedirectResponse("/?login=failed", status_code=303)


@router.get("/logout")
def logout_page(request: Request):
    # Visiting this page is safe; signing out requires a protected POST.
    return templates.TemplateResponse(request=request, name="logout.html", context={})


@router.post("/logout")
def logout(request: Request):
    # Clear the session only after the shared CSRF check succeeds.
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/session")
def session_status(request: Request):
    # Let an expired form refresh its token after the same user signs back in.
    from app.core.security import csrf_token

    return {"user_id": request.state.user.id, "csrf_token": csrf_token(request)}
