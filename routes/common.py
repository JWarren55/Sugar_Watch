from fastapi.templating import Jinja2Templates

from database import SessionLocal
from units import preferred_units, to_display


def unit_context(request):
    # Share the user's unit labels and display conversions with each page.
    user_id = request.session.get("user_id")
    units = "imperial"
    if user_id:
        with SessionLocal() as db:
            units = preferred_units(db, user_id)
    labels = (
        {"weight": "kg", "waist": "cm", "distance": "km", "height": "cm"}
        if units == "metric"
        else {
            "weight": "lb",
            "waist": "inches",
            "distance": "miles",
            "height": "inches",
        }
    )

    def display(value, field):
        converted = to_display(value, field, units)
        return "-" if converted is None else round(converted, 3)

    return {"saved_units": units, "unit_labels": labels, "display": display}


templates = Jinja2Templates(directory="templates", context_processors=[unit_context])
