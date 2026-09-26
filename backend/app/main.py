"""
NSE Trading API — FastAPI app.

Run from the backend/ folder:   uvicorn app.main:app --port 8000
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.core import config  # noqa: F401  (loads .env)
from app.api import auto_trader, health, kite, market, ticker, watchlist
from app.services import zerodha


@asynccontextmanager
async def lifespan(_app: FastAPI):
    zerodha.restore_saved_token()   # pick up today's Kite login after a restart
    yield


app = FastAPI(title="NSE Trading API", version="1.2.0", lifespan=lifespan)

# No cookies/credentials are used, so a wildcard origin is fine (and credentials + "*" is invalid anyway).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024)   # scanner / option-chain payloads compress well


# One error shape for the frontend: {"detail": "<human readable message>"}
@app.exception_handler(RequestValidationError)
async def validation_error(_req: Request, exc: RequestValidationError):
    first = (exc.errors() or [{}])[0]
    field = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse(status_code=422, content={"detail": f"Invalid {field or 'request'}: {first.get('msg', 'bad value')}"})


@app.exception_handler(Exception)
async def unhandled_error(req: Request, exc: Exception):
    print(f"[api] unhandled error on {req.method} {req.url.path}: {exc!r}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error — check the API logs."})


for module in (health, market, watchlist, kite, auto_trader, ticker):
    app.include_router(module.router)
