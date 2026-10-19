import logging

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

# Error pages must render even if the database is unavailable.
templates = Jinja2Templates(directory="templates")

logger = logging.getLogger(__name__)


def back_path(request):
    path = request.url.path
    if path.startswith("/entries/"):
        return path if path.endswith("/edit") else "/"
    section = path.strip("/").split("/")[0]
    return (
        "/" + section
        if section in ("food", "glucose", "exercise", "health", "medication", "mood")
        else "/"
    )


async def error_response(request, status, messages):
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse(
            request=request,
            name="form_error.html",
            context={"messages": messages, "back": back_path(request)},
            status_code=status,
        )
    return JSONResponse({"detail": messages}, status_code=status)


def install_error_handlers(app):
    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        messages = []
        for error in exc.errors():
            field = str(error.get("loc", ["Input"])[-1]).replace("_", " ").capitalize()
            messages.append(field + ": " + error["msg"])
        return await error_response(request, 422, messages)

    @app.exception_handler(HTTPException)
    async def input_error(request, exc):
        return await error_response(request, exc.status_code, [str(exc.detail)])

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.error("Database operation failed (%s)", type(exc).__name__)
        return await error_response(
            request,
            503,
            [
                "The database could not complete this request. Your form is still here; please try again."
            ],
        )
