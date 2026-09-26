from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import zerodha

router = APIRouter(prefix="/api/kite", tags=["kite"])


class KiteCallback(BaseModel):
    request_token: str


@router.get("/login-url")
def login_url():
    url = zerodha.get_login_url()
    if not url:
        raise HTTPException(status_code=503, detail="Kite not configured")
    return {"url": url}


@router.post("/callback")
def callback(body: KiteCallback):
    if zerodha.complete_login(body.request_token):
        return {"success": True, "message": "Kite login successful"}
    raise HTTPException(status_code=400, detail="Kite login failed — invalid request token")
