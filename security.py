"""Shared account, form-token, response-header, and request-size protection."""

import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders

import models
from database import SessionLocal
from settings import settings
from units import preferred_units

PUBLIC_PATHS = {
    "/",
    "/login",
    "/auth/google/callback",
    "/logout",
    "/docs",
    "/redoc",
    "/openapi.json",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_SESSION_KEY = "csrf_token"


class SignInRequired(Exception):
    pass


def csrf_token(request):
    # Keep a random form token inside the signed browser session.
    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def resolve_user(request: Request):
    # Recheck the account so a deleted or inactive user cannot reuse a session.
    request.state.user = None
    request.state.preferred_units = "imperial"
    if request.url.path in ("/login", "/auth/google/callback"):
        return None
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    if type(user_id) is not int or user_id <= 0:
        request.session.clear()
        return None
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        if user is None or not user.active or not settings.permits_email(user.email):
            request.session.clear()
            return None
        request.state.preferred_units = preferred_units(db, user_id)
        request.state.user = user
        return user


async def verify_request(request: Request, user=Depends(resolve_user)):
    if request.url.path not in PUBLIC_PATHS and user is None:
        raise SignInRequired()
    expected = csrf_token(request)
    if request.method in SAFE_METHODS:
        return
    # Origin checking supplements the token instead of relying on browser cookies alone.
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme, parsed.netloc.lower()) != (
            request.url.scheme,
            request.url.netloc.lower(),
        ):
            raise HTTPException(403, "This form must be submitted from Sugar Watch.")
    submitted = request.headers.get("x-csrf-token")
    if submitted is None:
        form = await request.form()
        submitted = form.get("csrf_token")
    if (
        not isinstance(submitted, str)
        or len(submitted) != len(expected)
        or not secrets.compare_digest(submitted.encode(), expected.encode())
    ):
        raise HTTPException(
            403, "This form expired. Reload the page before trying again."
        )


class RequestSafetyMiddleware:
    def __init__(self, app, max_body_bytes):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def safe_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "same-origin"
                if not scope["path"].startswith("/static/"):
                    headers["Cache-Control"] = "no-store"
                    if scope["path"] not in ("/docs", "/redoc"):
                        headers["Content-Security-Policy"] = (
                            "default-src 'self'; script-src 'self'; "
                            "style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; "
                            "connect-src 'self'; frame-ancestors 'none'; "
                            "base-uri 'self'; form-action 'self'; object-src 'none'"
                        )
            await send(message)

        if scope["method"] in SAFE_METHODS:
            return await self.app(scope, receive, safe_send)

        # Buffer a bounded body so oversized forms are rejected before parsing.
        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            limit = (
                4 * 1024 * 1024
                if scope["path"] == "/glucose/import/libreview"
                else self.max_body_bytes
            )
            if len(body) + len(chunk) > limit:
                response = JSONResponse(
                    {
                        "detail": [
                            f"This form is too large. Submit less than {limit // (1024 * 1024)} MB."
                        ]
                    },
                    status_code=413,
                )
                return await response(scope, receive, safe_send)
            body.extend(chunk)
            more = message.get("more_body", False)
        consumed = False

        async def replay_body():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_body, safe_send)
