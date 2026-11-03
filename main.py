from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

import models
from database import engine
from form_errors import install_error_handlers
from migrations import apply_storage_migrations
from routes import (
    auth,
    entries,
    exercise,
    food,
    food_catalog,
    glucose,
    health,
    home,
    medication,
    mood,
    trash,
)
from security import RequestSafetyMiddleware, verify_request
from settings import BASE_DIR, settings

app = FastAPI(
    dependencies=[Depends(verify_request)],
    docs_url=None if settings.production else "/docs",
    redoc_url=None if settings.production else "/redoc",
    openapi_url=None if settings.production else "/openapi.json",
)

# Store sign-in state in a signed session cookie.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.production,
)
app.add_middleware(RequestSafetyMiddleware, max_body_bytes=settings.max_body_bytes)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

# Serve the browser scripts and other static files.
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Create any database tables that do not exist yet.
models.Base.metadata.create_all(bind=engine)

# Apply each recorded storage conversion once before serving requests.
apply_storage_migrations(engine)

# Register each page and its form handlers.
app.include_router(home.router)
app.include_router(auth.router)
app.include_router(glucose.router)
app.include_router(food.router)
app.include_router(food_catalog.router)
app.include_router(exercise.router)

app.include_router(medication.router)
app.include_router(health.router)
app.include_router(mood.router)

app.include_router(entries.router)
app.include_router(trash.router)

# Show helpful messages when form validation or database requests fail.
install_error_handlers(app)
