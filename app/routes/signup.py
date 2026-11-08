"""Public request/confirmation pages; Google remains the sign-in provider."""

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.core.email_settings import email_settings, normalize_email
from app.db.session import SessionLocal
from app.routes.common import templates
from app.services.email_delivery import DeliveryError, send_verification
from app.services.email_verification import (
    approve_token,
    lookup_token,
    reserve_verification,
)

router = APIRouter()


def render(request, state, *, token=None, status=200):
    return templates.TemplateResponse(
        request=request,
        name="email_signup.html",
        context={
            "signup_enabled": email_settings.enabled,
            "state": state,
            "verification_token": token,
        },
        status_code=status,
    )


@router.get("/join")
def join_page(request: Request):
    return render(request, "request")


@router.post("/join")
def request_link(request: Request, email: str = Form(..., max_length=254)):
    if not email_settings.enabled:
        return render(request, "unavailable", status=503)
    address = normalize_email(email)
    if address is None:
        return render(request, "invalid", status=400)
    token = reserve_verification(
        address, request.client.host if request.client else "unknown"
    )
    if token:
        link = (
            email_settings.public_base_url
            + "/verify-email?"
            + urlencode({"token": token})
        )
        try:
            send_verification(email_settings, address, link)
        except DeliveryError:
            return render(request, "delivery_error", status=503)
    # Same response for send limits, existing accounts, and new addresses.
    return render(request, "sent")


@router.get("/verify-email")
def verification_page(request: Request):
    if not email_settings.enabled:
        return render(request, "unavailable", status=503)
    token = request.query_params.get("token", "")
    with SessionLocal() as db:
        valid = lookup_token(db, token) is not None
    # GET never approves an address, including when a mail scanner opens the link.
    return render(
        request,
        "confirm" if valid else "expired",
        token=token if valid else None,
        status=200 if valid else 400,
    )


@router.post("/verify-email")
def confirm_verification(request: Request, token: str = Form(..., max_length=100)):
    if not email_settings.enabled:
        return render(request, "unavailable", status=503)
    if not approve_token(token):
        return render(request, "expired", status=400)
    request.session["verified_email_notice"] = True
    return RedirectResponse("/join/verified", status_code=303)


@router.get("/join/verified")
def verified_page(request: Request):
    # This informational page never creates a login session or grants approval.
    if not request.session.pop("verified_email_notice", False):
        return RedirectResponse("/join", status_code=303)
    return render(request, "verified")
