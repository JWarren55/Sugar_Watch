from fastapi.templating import Jinja2Templates

from security import csrf_token
from settings import BASE_DIR
from time_utils import local_time, utc_iso
from units import labels_for, to_display


def unit_context(request):
    # Share the user's unit labels and display conversions with each page.
    units = getattr(request.state, "preferred_units", "imperial")
    labels = labels_for(units)

    def display(value, field):
        converted = to_display(value, field, units)
        return "-" if converted is None else round(converted, 3)

    return {
        "saved_units": units,
        "unit_labels": labels,
        "display": display,
        "csrf_token": csrf_token(request),
        "form_user_id": getattr(getattr(request.state, "user", None), "id", None),
    }


templates = Jinja2Templates(
    directory=BASE_DIR / "templates", context_processors=[unit_context]
)

templates.env.filters["local_time"] = local_time
templates.env.globals["utc_iso"] = utc_iso


def login_response(request):
    # Return a readable error to AJAX forms instead of fetching Google redirects.
    from fastapi.responses import JSONResponse, RedirectResponse

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse(
            {"detail": ["Your session expired. Sign in again, then retry this form."]},
            status_code=401,
        )
    return RedirectResponse("/login", status_code=303)
