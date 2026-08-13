#!/usr/bin/env python3
"""vplink.in bypass.

Chain: vplink.in/<code>
  -> shikshaads.in landing (?insurancesstudy=<code>) -> article -> /learn_more.php
  -> apnahirework.com landing (?studyeducate=<code>) -> article -> /learn_more.php
  -> apnahirework.com landing (?edustudy=<code>)     -> article -> /learn_more.php
  -> back to vplink.in/<code>  (repeat rounds until the unlock page appears)
  -> unlock page: #gt-link href, or POST /links/go

Usage:
  python vplink_bypass.py https://vplink.in/qkdMQ0 [--wait 25] [--quiet]
"""
import re
import sys
import time
from urllib.parse import urljoin, urlparse

from curl_cffi import requests

IMPERSONATE = "chrome124"
MAX_ROUNDS = 6
MAX_STEPS = 12


def js_location(html):
    m = re.search(r"location\.(?:href|replace)\s*(?:=|\()\s*['\"]([^'\"]+)", html)
    return m.group(1) if m else None


def blog_root(url):
    p = urlparse(url)
    parts = [s for s in p.path.split("/") if s]
    return f"{p.scheme}://{p.netloc}/" + (parts[0] + "/" if parts else "")


class VPLinkBypass:
    def __init__(self, wait=25.0, verbose=True):
        self.s = requests.Session(impersonate=IMPERSONATE)
        self.wait = wait
        self.verbose = verbose

    def log(self, *a):
        if self.verbose:
            print(*a, flush=True)

    def get(self, url, referer=None):
        h = {"Referer": referer} if referer else {}
        return self.s.get(url, headers=h, timeout=40, allow_redirects=True)

    # ---------- final unlock page ----------
    def extract_destination(self, html, page_url):
        m = re.search(r'id="gt-link"[^>]*href="([^"]+)"', html) or \
            re.search(r'href="([^"]+)"[^>]*id="gt-link"', html)
        if m and "javascript" not in m.group(1):
            return m.group(1)
        return self.post_go(html, page_url)

    def post_go(self, html, page_url):
        f = re.search(r'<form[^>]*id="go-link"[^>]*action="([^"]*)"(.*?)</form>', html, re.S)
        if not f:
            return None
        action = urljoin(page_url, f.group(1))
        data = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', f.group(2)))
        time.sleep(11)
        r = self.s.post(action, data=data, timeout=40, headers={
            "Referer": page_url,
            "Origin": "https://vplink.in",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
        m = re.search(r'https?:\\?/\\?/[^"\'<>\s\\]+', r.text)
        return m.group(0).replace("\\/", "/") if m else None

    # ---------- one blog hop: landing -> article -> learn_more.php ----------
    def blog_hop(self, landing_url, referer):
        html = self.get(landing_url, referer).text
        article = js_location(html)
        if not article:
            raise RuntimeError(f"no article link on {landing_url}")
        origin = "{0.scheme}://{0.netloc}/".format(urlparse(article))
        self.get(article, origin)
        self.log("    article:", article)
        time.sleep(self.wait)
        html = self.get(blog_root(article) + "learn_more.php", article).text
        nxt = js_location(html)
        if not nxt:
            raise RuntimeError("learn_more.php gave no next hop")
        return nxt, article

    # ---------- main ----------
    def resolve(self, url):
        current, referer = url, None
        for rnd in range(MAX_ROUNDS):
            resp = self.get(current, referer)
            html, cur = resp.text, str(resp.url)
            self.log(f"[round {rnd}] {resp.status_code} {cur}")

            nxt = js_location(html)
            if not nxt:  # unlock page
                dest = self.extract_destination(html, cur)
                if dest:
                    return dest
                raise RuntimeError("unlock page reached but no destination found")

            last_article = None
            for _ in range(MAX_STEPS):
                nxt, last_article = self.blog_hop(nxt, cur if last_article is None else last_article)
                self.log("    ->", nxt)
                if "vplink.in" in urlparse(nxt).netloc:
                    break
            else:
                raise RuntimeError("blog chain did not return to vplink")
            current, referer = nxt, last_article
        raise RuntimeError("too many rounds")


def main():
    args = sys.argv[1:]
    wait, verbose = 25.0, True
    if "--quiet" in args:
        verbose = False
        args.remove("--quiet")
    if "--wait" in args:
        i = args.index("--wait")
        wait = float(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        sys.exit(1)
    print("FINAL:", VPLinkBypass(wait=wait, verbose=verbose).resolve(args[0]))


if __name__ == "__main__":
    main()
