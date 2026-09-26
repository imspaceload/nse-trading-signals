from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.sms import add_to_watchlist, get_watchlist, remove_from_watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    symbol: str


@router.get("")
def list_watchlist():
    try:
        return get_watchlist()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
def add(body: WatchlistAdd):
    sym = body.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Symbol is required")
    return {"success": add_to_watchlist(sym), "symbol": sym}


@router.delete("/{symbol}")
def remove(symbol: str):
    sym = symbol.strip().upper()
    return {"success": remove_from_watchlist(sym), "symbol": sym}
