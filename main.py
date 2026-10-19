import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import models
from database import engine
from form_errors import install_error_handlers
from routes import (
    auth,
    entries,
    exercise,
    food,
    glucose,
    health,
    home,
    medication,
    mood,
)

load_dotenv()

app = FastAPI()

# Store sign-in state in a signed session cookie.
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))

# Serve the browser scripts and other static files.
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create any database tables that do not exist yet.
models.Base.metadata.create_all(bind=engine)

# Register each page and its form handlers.
app.include_router(home.router)
app.include_router(auth.router)
app.include_router(glucose.router)
app.include_router(food.router)
app.include_router(exercise.router)

app.include_router(medication.router)
app.include_router(health.router)
app.include_router(mood.router)

app.include_router(entries.router)

# Show helpful messages when form validation or database requests fail.
install_error_handlers(app)
