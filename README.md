# Bypass API (v2)

FastAPI service that resolves ad-gated shortlinks to their final destination.

Supported: `linksgo.in`, `earnlinks.in`, `vplink.in`, `viku.urlking.in` (needs playwright + residential IP).

## Deploy on Render

1. Push this folder to a GitHub repo.
2. Render → New → Web Service → pick the repo. `render.yaml` is auto-detected.
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 620`
3. Done. Base URL: `https://<name>.onrender.com`

## Endpoints

| Endpoint | Description |
| --- | --- |
| `GET /api?bypass=<url>` | Resolve a link |
| `GET /bypass?url=<url>` | Same |
| `POST /bypass` `{"url": "..."}` | Same |
| `GET /job?id=<job_id>` | Poll a pending job |
| `GET /health` | Health check |

### Important: job mode

Render kills any HTTP request open longer than ~100s, and these chains need
40-180s. So the API answers within 75s:

```json
{"success": false, "status": "running", "pending": true,
 "job_id": "0329e7858d28", "poll": "/job?id=0329e7858d28"}
```

The work keeps running in the background — poll `/job?id=...` every 3s until:

```json
{"success": true, "status": "done", "bypassed": "https://t.me/...", "took": 78.5}
```

`success: false` with `status: "running"` and `pending: true` is not a failure.
It means the Render request returned early and the resolver is still working.
Keep polling with the returned `job_id`; only treat `status: "error"` as a failed
resolve.

Fast links finish inside the first request and return `success: true` directly.

### Client snippet

```python
import requests, time
BASE = "https://your-app.onrender.com"

def resolve(url):
    d = requests.get(f"{BASE}/api", params={"bypass": url}, timeout=120).json()
    while d.get("status") == "running":
        time.sleep(5)
        d = requests.get(f"{BASE}/job", params={"id": d["job_id"]}, timeout=30).json()
    return d
```

`examples/bot.py` (Telegram) and `examples/web.html` already do this polling.

## Env vars

| Var | Default | Meaning |
| --- | --- | --- |
| `SYNC_BUDGET` | 20 | Seconds to wait before switching to job mode |
| `BYPASS_TIMEOUT` | 420 | Hard cap per job |
| `BYPASS_RETRIES` | 2 | Retries per link |
| `VPLINK_WAIT` | 15 | Countdown wait for vplink blogs |
| `LINKSGO_WAIT` | 9 | Countdown wait for linksgo blogs |
| `EARNLINKS_WAIT` | 8 | Countdown wait for earnlinks blogs |
| `MAX_CONCURRENCY` | 2 | Parallel resolves (free plan = keep low) |
| `POLL_INTERVAL` | 3 | Suggested seconds between job polls |
| `CACHE_TTL` | 300 | Seconds to reuse a successful result |
| `API_KEY` | – | If set, every call needs `&key=...` |

## Notes

- Free Render instances sleep after 15 min; the first call can take ~50s extra to wake.
- `playwright` is **not** in requirements (it breaks/slows the free build). Install it
  manually if you want `urlking`; it also needs a non-datacenter IP for Cloudflare.

## Add a new site

1. `bypass/<site>.py` with a resolver `def resolve(url) -> str` (sync or async).
2. Register it in `RESOLVERS` inside `bypass/__init__.py`.
