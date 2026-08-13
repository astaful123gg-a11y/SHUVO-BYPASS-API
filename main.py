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
SYNC_BUDGET = float(os.getenv("SYNC_BUDGET", "75"))     # < Render's ~100s cut-off
API_KEY = "SHUVOxbypasser"                               # hard-coded lock

app = FastAPI(title="Bypass API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict] = {}
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
    if len(JOBS) <= 200:
        return
    for k in sorted(JOBS, key=lambda k: JOBS[k]["started"])[:100]:
        JOBS.pop(k, None)


async def _worker(job_id: str, url: str):
    job = JOBS[job_id]
    try:
        async with _LOCK:
            dest = await asyncio.wait_for(bypass(url), timeout=TIMEOUT)
        job.update(status="done", success=True, bypassed=dest)
    except asyncio.TimeoutError:
        job.update(status="error", success=False, error="Bypass timed out")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        job.update(status="error", success=False, error=f"{type(e).__name__}: {e}")
    finally:
        job["took"] = round(time.time() - job["started"], 1)


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
        out["message"] = "Still working (ad countdowns). Poll the 'poll' URL every 5s."
    return out


async def _run(url: str | None, key: str | None):
    if API_KEY and key != API_KEY:
        return _err("Invalid or missing API key", 401)
    if not url:
        return _err("Missing 'url' (or 'bypass') parameter")

    url = _normalize(url)
    if get_resolver(url) is None:
        return _err(f"Unsupported site. Supported: {', '.join(SUPPORTED)}")

    job_id = uuid.uuid4().hex[:12]
    _prune()
    JOBS[job_id] = {"url": url, "status": "running", "started": time.time()}
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
    