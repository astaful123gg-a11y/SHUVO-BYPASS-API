#!/usr/bin/env python3
"""linksgo.in bypass — jkstudentspoint blog/countdown chain -> /links/go."""
import asyncio
import random
import re
import sys

from curl_cffi.requests import AsyncSession

UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]
IMPERSONATIONS = ["chrome120", "chrome124", "chrome116", "safari17_0"]

BASE = "https://linksgo.in"


def _headers(ua: str) -> dict:
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    }


def extract_gt_link(html: str) -> str | None:
    for pat in (
        r'<a[^>]*id=["\']gt-link["\'][^>]*>',
        r'<a[^>]*id=["\']download["\'][^>]*>',
    ):
        m = re.search(pat, html, re.I)
        if m:
            mh = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
            if mh and mh.group(1).startswith("http") and "linksgo.in" not in mh.group(1):
                return mh.group(1)
    return None


def parse_form(html: str) -> dict[str, str] | None:
    f = re.search(r'<form[^>]*id="go-link"[\s\S]*?</form>', html)
    if not f:
        return None
    data = {}
    for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', f.group(0)):
        data[m.group(1)] = m.group(2)
    return data or None


def next_hop(html: str, code: str, seen: set[str]) -> str | None:
    """Find the next stop on the blog/countdown chain."""
    m = re.search(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*URL=[\'"]?(https?://[^"\'>]+)',
        html, re.I,
    )
    if m and m.group(1) not in seen:
        return m.group(1)
    for pat in (
        r'window\.location\.href\s*=\s*["\'](https?://[^"\']+)',
        r'location\.(?:href|replace)\s*(?:=|\()\s*["\'](https?://[^"\']+)',
    ):
        m = re.search(pat, html)
        if m and "example.com" not in m.group(1) and m.group(1) not in seen:
            return m.group(1)
    for c in re.findall(r'https?://[^\s"\'<>]+\?[a-z]+=' + re.escape(code), html):
        if c not in seen:
            return c
    return None


async def _once(url: str, wait: float, impersonate: str, ua: str, verbose: bool) -> str:
    code = url.rstrip("/").split("/")[-1].split("?")[0]
    H = _headers(ua)
    s = AsyncSession(verify=False, impersonate=impersonate, timeout=40)

    def log(*a):
        if verbose:
            print(*a, flush=True)

    async def try_unlock(html: str, referer: str) -> str | None:
        form = parse_form(html)
        if not form:
            return extract_gt_link(html)
        log("[+] Unlock page reached, waiting out the timer...")
        await asyncio.sleep(7)
        post = await s.post(
            f"{BASE}/links/go",
            data=form,
            headers={**H, "Referer": referer, "X-Requested-With": "XMLHttpRequest",
                     "Origin": BASE},
            timeout=30,
        )
        try:
            j = post.json()
        except Exception:
            j = {}
        target = j.get("url") or extract_gt_link(post.text)
        if not target:
            log(f"[-] /links/go -> {post.status_code} {post.text[:160]}")
        return target

    try:
        log(f"[+] Session init ({impersonate})...")
        await s.get(f"{BASE}/", headers=H, timeout=25)
        r = await s.get(url, headers={**H, "Referer": f"{BASE}/"}, timeout=30)
        ref = str(r.url)
        seen: set[str] = {url}

        for step in range(14):
            target = await try_unlock(r.text, url)
            if target:
                return target
            nxt = next_hop(r.text, code, seen)
            if nxt is None:
                break
            seen.add(nxt)
            log(f"[+] Hop {step}: {nxt}")
            if "?" in nxt or ".php" in nxt:
                log(f"[*] Countdown wait {wait}s...")
                await asyncio.sleep(wait)
            r = await s.get(nxt, headers={**H, "Referer": ref}, timeout=40)
            ref = nxt

        for attempt in range(4):
            log(f"[+] Return to linksgo (try {attempt + 1})...")
            rr = await s.get(url, headers={**H, "Referer": ref}, timeout=30)
            target = await try_unlock(rr.text, url)
            if target:
                return target
            nxt = next_hop(rr.text, code, seen)
            if nxt:
                seen.add(nxt)
                log(f"[+] Extra hop: {nxt}")
                await asyncio.sleep(wait)
                rr = await s.get(nxt, headers={**H, "Referer": url}, timeout=40)
                ref = nxt
            else:
                await asyncio.sleep(7)

        raise ValueError("ad-gate chain did not unlock")
    finally:
        try:
            await s.close()
        except Exception:
            pass


async def bypass_linksgo(url: str, wait: float = 13, attempts: int = 3,
                         verbose: bool = True) -> str:
    """Resolve a linksgo.in short link, retrying with fresh fingerprints."""
    last = None
    for i in range(attempts):
        imp = IMPERSONATIONS[i % len(IMPERSONATIONS)]
        ua = random.choice(UAS)
        try:
            dest = await _once(url, wait + i * 4, imp, ua, verbose)
            if dest:
                if verbose:
                    print(f"[+] SUCCESS: {dest}", flush=True)
                return dest
        except Exception as e:  # noqa: BLE001
            last = e
            if verbose:
                print(f"[-] Attempt {i + 1} failed: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(3)
    raise RuntimeError(f"linksgo bypass failed after {attempts} attempts ({last})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m bypass.linksgo <linksgo_url>")
        sys.exit(1)
    print("FINAL:", asyncio.run(bypass_linksgo(sys.argv[1])))
