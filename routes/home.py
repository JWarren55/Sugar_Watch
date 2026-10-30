from fastapi import APIRouter, Request

from routes.common import templates

router = APIRouter()


@router.get("/")
def home(request: Request):
    # Show the home page with the current account, if signed in.
    user = request.state.user

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Sugar Watch", "user": user},
    )
