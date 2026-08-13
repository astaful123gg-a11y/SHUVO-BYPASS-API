#!/usr/bin/env python3
"""Bypass API — FastAPI service for Render.

Endpoints:
  GET  /                          -> info + supported sites
  GET  /health                    -> {"ok": true}
  GET  /bypass?url=<shortlink>    -> {"success": true, "source": ..., "bypassed": ...}
  GET  /api?bypass=<shortlink>    -> same (alias, ?bypass= style)
  POST /bypass  {"url": "..."}    -> same

Run locally:  uvicorn main:app --reload
Render start: uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import os
import time

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bypass import SUPPORTED, bypass, get_resolver

TIMEOUT = int(os.getenv("BYPASS_TIMEOUT", "300"))
API_KEY = "SHUVOxbypasser"

app = FastAPI(title="Bypass API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class BypassBody(BaseModel):
    url: str
    key: str | None = None


def _err(msg: str, code: int = 400):
    return JSONResponse({"success": False, "error": msg}, status_code=code)


async def _run(url: str | None, key: str | None):
    if API_KEY and key != API_KEY:
        return _err("Invalid or missing API key", 401)
    if not url:
        return _err("Missing 'url' (or 'bypass') parameter")
    if get_resolver(url if url.startswith("http") else "https://" + url) is None:
        return _err(f"Unsupported site. Supported: {', '.join(SUPPORTED)}")

    started = time.time()
    try:
        dest = await asyncio.wait_for(bypass(url), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        return _err("Bypass timed out", 504)
    except Exception as e:  # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}", 502)

    return {
        "success": True,
        "source": url,
        "bypassed": dest,
        "took": round(time.time() - started, 1),
    }


@app.get("/")
async def root():
    return {
        "name": "Bypass API",
        "supported": SUPPORTED,
        "usage": [
            "/bypass?url=https://vplink.in/Nywa",
            "/api?bypass=https://vplink.in/Nywa",
        ],
        "note": "Bypass can take 1-3 minutes (ad countdown timers). Keep client timeout high.",
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/bypass")
async def bypass_get(
    url: str | None = Query(None),
    bypass_: str | None = Query(None, alias="bypass"),
    key: str | None = Query(None),
):
    return await _run(url or bypass_, key)


@app.get("/api")
async def api_get(
    bypass_: str | None = Query(None, alias="bypass"),
    url: str | None = Query(None),
    key: str | None = Query(None),
):
    return await _run(bypass_ or url, key)


@app.post("/bypass")
async def bypass_post(body: BypassBody):
    return await _run(body.url, body.key)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
    