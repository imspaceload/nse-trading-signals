from datetime import datetime

import pytz
from fastapi import APIRouter

from app.services import zerodha
from app.services.market_data import is_market_open

router = APIRouter(prefix="/api", tags=["health"])
IST = pytz.timezone("Asia/Kolkata")


@router.get("/health")
def health():
    """Cheap liveness probe the UI polls: API up, Kite login state, market state."""
    kite_ok = zerodha.is_connected() if zerodha.is_configured() else False
    return {
        "status": "ok",
        "kite_connected": kite_ok,
        "kite_configured": zerodha.is_configured(),
        "market_open": is_market_open(),
        "server_time": datetime.now(IST).isoformat(),
    }
