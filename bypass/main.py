#!/usr/bin/env python3
"""Bypass API — FastAPI service (Render ready).

Endpoints:
  GET  /                             -> info + supported sites
  GET  /health                       -> {"ok": true}
  GET  /bypass?url=<shortlink>       -> resolve (auto-switches to job mode if slow)
  GET  /api?bypass=<shortlink>       -> same (alias)
  POST /bypass  {"url": "..."}       -> same
  GET  /job?id=<job_id>              -> poll a pending job
  GET  /jobs                         -> list recent jobs

Why job mode?  Render's proxy kills any HTTP request that stays open ~100s.
Ad-gate chains often need 60-180s, so if a resolve is not done within
SYNC_BUDGET seconds the API returns {"success": false, "pending": true,
"job_id": "..."} and the work keeps running in the background. Poll
/job?id=... until "success" is true.

Local:  uvicorn main:app --reload
Render: uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import os
import time
import traceback
import uuid

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bypass import SUPPORTED, bypass, get_resolver

TIMEOUT = int(os.getenv("BYPASS_TIMEOUT", "420"))       # hard cap per job
SYNC_BUDGET = float(os.getenv("SYNC_BUDGET", "20"))     # return a pollable job before Render's proxy timeout
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "3"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
API_KEY = os.getenv("API_KEY", "")                      # optional lock

app = FastAPI(title="Bypass API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_response_caching(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


JOBS: dict[str, dict] = {}
RESULT_CACHE: dict[str, dict] = {}
ACTIVE_JOBS: dict[str, str] = {}
_LOCK = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "2")))


class BypassBody(BaseModel):
    url: str | None = None
    bypass: str | None = None
    key: str | None = None


def _err(msg: str, code: int = 400, **extra):
    return JSONResponse({"success": False, "error": msg, **extra}, status_code=code)


def _normalize(url: str) -> str:
    url = url.strip().strip('"').strip("'")
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _prune():
    now = time.time()
    for url, item in list(RESULT_CACHE.items()):
        if now - item["stored"] > CACHE_TTL:
            RESULT_CACHE.pop(url, None)
    if len(JOBS) > 200:
        for k in sorted(JOBS, key=lambda k: JOBS[k]["started"])[:100]:
            JOBS.pop(k, None)


def _cached_payload(url: str, destination: str) -> dict:
    return {
        "success": True,
        "status": "done",
        "source": url,
        "job_id": "cached",
        "took": 0,
        "bypassed": destination,
        "cached": True,
    }


async def _worker(job_id: str, url: str):
    job = JOBS[job_id]
    try:
        async with _LOCK:
            dest = await asyncio.wait_for(bypass(url), timeout=TIMEOUT)
        job.update(status="done", success=True, bypassed=dest)
        RESULT_CACHE[url] = {"bypassed": dest, "stored": time.time()}
    except asyncio.TimeoutError:
        job.update(status="error", success=False, error="Bypass timed out")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        job.update(status="error", success=False, error=f"{type(e).__name__}: {e}")
    finally:
        job["took"] = round(time.time() - job["started"], 1)
        if ACTIVE_JOBS.get(url) == job_id:
            ACTIVE_JOBS.pop(url, None)


def _payload(job_id: str) -> dict:
    j = JOBS[job_id]
    out = {
        "success": bool(j.get("success")),
        "status": j["status"],
        "source": j["url"],
        "job_id": job_id,
        "took": round(j.get("took", time.time() - j["started"]), 1),
    }
    if j["status"] == "done":
        out["bypassed"] = j["bypassed"]
    elif j["status"] == "error":
        out["error"] = j["error"]
    else:
        out["pending"] = True
        out["poll"] = f"/job?id={job_id}"
        out["message"] = (
            f"Still working (ad countdowns). Poll the 'poll' URL every {POLL_INTERVAL}s."
        )
    return out


async def _run(url: str | None, key: str | None):
    if API_KEY and key != API_KEY:
        return _err("Invalid or missing API key", 401)
    if not url:
        return _err("Missing 'url' (or 'bypass') parameter")

    url = _normalize(url)
    if get_resolver(url) is None:
        return _err(f"Unsupported site. Supported: {', '.join(SUPPORTED)}")

    _prune()
    if CACHE_TTL > 0:
        cached = RESULT_CACHE.get(url)
        if cached and time.time() - cached["stored"] <= CACHE_TTL:
            return _cached_payload(url, cached["bypassed"])

    active_job_id = ACTIVE_JOBS.get(url)
    if active_job_id and active_job_id in JOBS:
        return _payload(active_job_id)

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"url": url, "status": "running", "started": time.time()}
    ACTIVE_JOBS[url] = job_id
    task = asyncio.create_task(_worker(job_id, url))

    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=SYNC_BUDGET)
    except asyncio.TimeoutError:
        pass  # keeps running in background; client polls /job

    return _payload(job_id)


@app.get("/")
async def root():
    return {
        "name": "Bypass API",
        "version": "2.0.0",
        "supported": SUPPORTED,
        "usage": [
            "/api?bypass=https://vplink.in/qkdMQ0",
            "/bypass?url=https://linksgo.in/F9DVB",
            "/job?id=<job_id>   (when the first response says pending)",
        ],
        "note": "Resolves take 40-180s. If pending, poll /job?id=... every 5s.",
    }


@app.get("/health")
async def health():
    return {"ok": True, "jobs": len(JOBS)}


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
    return await _run(body.url or body.bypass, body.key)


@app.get("/job")
async def job_get(id: str = Query(...)):
    if id not in JOBS:
        return _err("Unknown job id", 404)
    return _payload(id)


@app.get("/jobs")
async def jobs_list():
    return {"jobs": [_payload(j) for j in list(JOBS)[-25:]]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
