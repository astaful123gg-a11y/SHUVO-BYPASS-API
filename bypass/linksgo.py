import asyncio
import re
import sys
from curl_cffi.requests import AsyncSession

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BASE = "https://linksgo.in"


def extract_gt_link(html: str) -> str | None:
    m = re.search(r'<a[^>]*id=["\']gt-link["\'][^>]*>', html, re.I)
    if m:
        mh = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.I)
        if mh and "javascript" not in mh.group(1):
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
    """Find the next stop on the jkstudentspoint blog/countdown chain."""
    m = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*URL=[\'"]?(https?://[^"\'>]+)', html, re.I)
    if m and m.group(1) not in seen:
        return m.group(1)
    m = re.search(r'window\.location\.href\s*=\s*["\'](https?://[^"\']+)', html)
    if m and "example.com" not in m.group(1) and m.group(1) not in seen:
        return m.group(1)
    for c in re.findall(r'https?://[^\s"\'<>]+\?[a-z]+=' + re.escape(code), html):
        if c not in seen:
            return c
    return None


async def bypass_linksgo(url: str, wait: int = 12, s: AsyncSession | None = None) -> str:
    """Bypass linksgo.in by traversing the jkstudentspoint blog/countdown chain."""
    code = url.rstrip("/").split("/")[-1].split("?")[0]
    close_session = s is None
    if s is None:
        s = AsyncSession(verify=False, impersonate="chrome120")

    async def try_unlock(html: str, referer: str) -> str | None:
        form = parse_form(html)
        if not form:
            return extract_gt_link(html)
        print("[+] Reached linksgo unlock page, waiting out the timer...")
        await asyncio.sleep(6)
        post = await s.post(
            f"{BASE}/links/go",
            data=form,
            headers={**HEADERS, "Referer": referer, "X-Requested-With": "XMLHttpRequest",
                     "Origin": BASE},
            timeout=25,
        )
        try:
            j = post.json()
        except Exception:
            j = {}
        target = j.get("url") or extract_gt_link(post.text)
        if not target:
            print(f"[-] Unexpected /links/go response: {post.status_code} {post.text[:200]}")
        return target

    try:
        print("[+] Initializing session on linksgo homepage...")
        await s.get(f"{BASE}/", headers=HEADERS, timeout=20)

        print(f"[+] GET initial linksgo URL: {url}")
        r = await s.get(url, headers=HEADERS, timeout=25)
        ref = str(r.url)
        seen: set[str] = {url}

        for step in range(12):
            target = await try_unlock(r.text, url)
            if target:
                print(f"[+] SUCCESS! Bypassed link: {target}")
                return target

            nxt = next_hop(r.text, code, seen)
            if nxt is None:
                break

            seen.add(nxt)
            print(f"[+] Hop {step}: {nxt}")
            if "?" in nxt or ".php" in nxt:
                print(f"[*] Waiting {wait}s for countdown timer...")
                await asyncio.sleep(wait)
            r = await s.get(nxt, headers={**HEADERS, "Referer": ref}, timeout=30)
            ref = nxt

        # Return to linksgo to collect the unlocked link
        for attempt in range(3):
            print(f"[+] Returning to linksgo page (attempt {attempt + 1})...")
            rr = await s.get(url, headers={**HEADERS, "Referer": ref}, timeout=25)
            target = await try_unlock(rr.text, url)
            if target:
                print(f"[+] SUCCESS! Bypassed link: {target}")
                return target
            await asyncio.sleep(6)

        raise ValueError("Target link not found; the ad-gate chain did not unlock.")
    finally:
        if close_session:
            await s.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python linksgo_bypass.py <linksgo_url>")
        sys.exit(1)
    try:
        res = asyncio.run(bypass_linksgo(sys.argv[1]))
        print(f"\nFinal Link: {res}")
    except Exception as e:
        print(f"\n[-] Error during bypass: {e}")
        sys.exit(1)
