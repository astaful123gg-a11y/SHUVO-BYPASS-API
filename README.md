# Bypass API

Shortlink bypass service (FastAPI) — deploy on Render, use from a Telegram bot or website.

## Structure
```
main.py            FastAPI app (endpoints)
bypass/
  __init__.py      domain -> resolver registry + bypass()
  linksgo.py       linksgo.in
  earnlinks.py     earnlinks.in
  vplink.py        vplink.in
  urlking.py       viku.urlking.in (needs Playwright + non-datacenter IP)
requirements.txt
render.yaml
examples/bot.py    Telegram bot example
examples/web.html  Browser example
```

## Deploy on Render
1. Push this folder to a GitHub repo.
2. Render -> New -> Web Service -> pick the repo (render.yaml is auto-detected).
   Manual setup: Build `pip install -r requirements.txt`,
   Start `uvicorn main:app --host 0.0.0.0 --port $PORT --timeout-keep-alive 600`.
3. Optional env `API_KEY=yoursecret` to lock the API (then add `&key=yoursecret`).

## Usage
```
GET https://your-app.onrender.com/bypass?url=https://vplink.in/Nywa
GET https://your-app.onrender.com/api?bypass=https://vplink.in/Nywa
POST /bypass   {"url": "https://linksgo.in/F9DVB"}
```
Response:
```json
{"success": true, "source": "...", "bypassed": "https://t.me/...", "took": 96.4}
```
Errors: `{"success": false, "error": "..."}`

## Notes
- A bypass takes 1-3 minutes (ad countdown timers). Set a high client timeout;
  free Render instances also cold-start (~50s after idle).
- `viku.urlking.in` is behind Cloudflare Turnstile — it needs Playwright and
  usually fails from datacenter IPs (Render included). Others work fine.
- Supported list is live at `GET /`.

## Add a new site
Create `bypass/newsite.py` with `async def bypass_newsite(url) -> str`
(or a sync function), then register it in `bypass/__init__.py`:
```python
RESOLVERS["newsite.in"] = bypass_newsite
```
