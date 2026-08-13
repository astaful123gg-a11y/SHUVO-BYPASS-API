"""Bypass modules registry.

Add a new site: write bypass/<site>.py with an async or sync resolver
and register it in RESOLVERS below.
"""
import asyncio
import inspect
import os
from urllib.parse import urlparse

from .linksgo import bypass_linksgo
from .earnlinks import bypass_earnlinks
from .vplink import VPLinkBypass

VPLINK_WAIT = float(os.getenv("VPLINK_WAIT", "15"))
LINKSGO_WAIT = float(os.getenv("LINKSGO_WAIT", "9"))
EARNLINKS_WAIT = float(os.getenv("EARNLINKS_WAIT", "8"))
RETRIES = int(os.getenv("BYPASS_RETRIES", "2"))


def _vplink(url: str) -> str:
    return VPLinkBypass(wait=VPLINK_WAIT, verbose=True).resolve(url)


async def _linksgo(url: str) -> str:
    return await bypass_linksgo(url, wait=LINKSGO_WAIT)


async def _earnlinks(url: str) -> str:
    return await bypass_earnlinks(url, wait=EARNLINKS_WAIT)


def _urlking(url: str) -> str:
    # needs playwright + a non-datacenter IP (Cloudflare Turnstile)
    try:
        from .urlking import bypass_urlking
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "urlking needs playwright installed (pip install playwright && "
            f"playwright install chromium): {e}"
        ) from e
    return bypass_urlking(url)


# domain (without www) -> resolver
RESOLVERS = {
    "linksgo.in": _linksgo,
    "earnlinks.in": _earnlinks,
    "vplink.in": _vplink,
    "viku.urlking.in": _urlking,
    "urlking.in": _urlking,
}

SUPPORTED = sorted(RESOLVERS)


def _host(url: str) -> str:
    h = (urlparse(url).netloc or "").lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def get_resolver(url: str):
    host = _host(url)
    if host in RESOLVERS:
        return RESOLVERS[host]
    for domain, fn in RESOLVERS.items():
        if host.endswith("." + domain):
            return fn
    return None


async def _call(fn, url: str) -> str:
    if inspect.iscoroutinefunction(fn):
        return await fn(url)
    return await asyncio.to_thread(fn, url)


async def bypass(url: str) -> str:
    """Resolve any supported shortlink to its final destination."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    fn = get_resolver(url)
    if fn is None:
        raise ValueError(
            f"Unsupported site '{_host(url)}'. Supported: {', '.join(SUPPORTED)}"
        )
    last = None
    for i in range(max(1, RETRIES)):
        try:
            dest = await _call(fn, url)
            if dest:
                return dest
            last = ValueError("resolver returned no destination")
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"[!] attempt {i + 1} failed: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(2)
    raise last if last else RuntimeError("bypass failed")
