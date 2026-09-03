import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import models
from database import engine
from routes import auth, glucose, home


load_dotenv()


app = FastAPI()


app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY")
)


app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


models.Base.metadata.create_all(bind=engine)


app.include_router(home.router)
app.include_router(auth.router)
app.include_router(glucose.router)