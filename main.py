import os

from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

import models
from database import SessionLocal, engine

app = FastAPI()
models.Base.metadata.create_all(bind=engine)

load_dotenv()

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY")
)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


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


@app.get("/")
def home(request: Request):
    user = None
    user_id = request.session.get("user_id")
    
    if user_id:
        db = SessionLocal()
        try:
            user = db.get(models.User, user_id)
        finally:
            db.close()
            
    return templates.TemplateResponse(
        request=request,
        name="index.html"
        context={
            "title": "Sugar Watch"
            "user": user
        }
    )
        


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@app.get("/auth/google/callback")
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
            ## SELECT * FROM users WHERE google_id = 'input';
            stmt = select(models.User).where(models.User.google_id)
            
            user = db.scalar(stmt)
            
            if user is None:
                user = models.User(
                    google_id=google_id,
                    email=email,
                    name=name,
                    picture=picture
                )
                ## INSERT INTO users (...) VALUES (...);
                db.add(user)
                db.commit()
                db.refresh(user)
                
            request.session["user_id"] = user.id
            
        finally:
            db.close()
            
        return RedirectResponse(url="/")

    except Exception:
        return RedirectResponse(url="/?login=cancelled")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")