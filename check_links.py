#!/usr/bin/env python3
"""Every external link on the pages a reader reaches must resolve.

Why this exists
---------------
Two project links on the portfolio were dead and nothing was watching. One pointed
at a repository that is private, so it returned 404 for every visitor; the other
had a phrase pasted into the URL, so it resolved a repository name containing a
space and parentheses. Both had been broken for who knows how long, and were found
only because a person happened to check all of them by hand. A portfolio that 404s
spends the credibility the rest of the page earns, so the check belongs here,
where it runs on every push and weekly.

What fails the run
------------------
**404 and 410 only.** Those are the codes that mean *gone*.

403 and 429 do **not** fail it. A 403 usually means the site declines automated
clients, which says nothing about whether a reader can reach the page; failing on
it would turn this red for reasons that are not the repository's fault, and a check
that cries wolf is a check someone switches off. Those are reported as unverified
so the distinction stays visible.

Anything else that looks transient (timeouts, connection resets, 5xx) is retried
once and then reported as unverified rather than broken, for the same reason.

Stdlib only, like the rest of this repository: no dependency to keep in step.
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PAGES = [
    ("https://sushantpoudel2028.com.np/", "the portfolio"),
    ("https://sushant-me.github.io/hire/", "the hire page"),
]

# Assets and services that are not pages a reader follows: fonts, badge images,
# and the vocabularies a search engine reads rather than a person.
SKIP = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "img.shields.io",
    "shield",
    "badge",
    "schema.org",
    "www.w3.org",
)

HEADERS = {
    # Some hosts 403 a request with no user agent; this is not evasion, it is
    # making the request look like the browser request it is meant to imitate.
    "User-Agent": "Mozilla/5.0 (compatible; reputation-link-check/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

GONE = {404, 410}
NOT_VERIFIABLE = {401, 403, 405, 406, 429}

# A URL a reader cannot follow even if the host is up. This exists because the
# first version of this check missed one of the two defects it was written for:
# the malformed link had a phrase pasted into it, so the request failed before it
# could 404, and the failure was classified as "unverified" rather than "gone".
# Whitespace is never valid in a URL; the rest are characters that break parsing.
MALFORMED_RE = re.compile(r'[\s<>"{}|\\^`]')


def malformed(url: str) -> str:
    m = MALFORMED_RE.search(url)
    return f"contains {m.group(0)!r}" if m else ""


def fetch(url: str, attempts: int = 2, timeout: int = 25) -> str | None:
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            if attempt == attempts - 1:
                return None
    return None


def status_of(url: str) -> tuple[int | None, str]:
    """Return (status, note). status is None when the request never completed."""
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.status, ""
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:
            if attempt == 1:
                return None, type(e).__name__
    return None, "unreachable"


def links_on(page_url: str) -> set[str]:
    html = fetch(page_url)
    if html is None:
        return set()
    found = set(re.findall(r'href="(https?://[^"]+)"', html))
    found |= set(re.findall(r'src="(https?://[^"]+)"', html))
    return {u.rstrip("/") for u in found if not any(s in u for s in SKIP)}


def main() -> int:
    targets: dict[str, set[str]] = {}
    for url, label in PAGES:
        got = links_on(url)
        if not got:
            print(f"FAIL  could not read {label} ({url}) - 0 links found")
            return 1
        targets[label] = got

    all_links = sorted(set().union(*targets.values()))
    print(f"checking {len(all_links)} external links on {len(PAGES)} pages\n")

    # Malformed URLs are decided before any request: no request can succeed, so
    # asking would only produce a misleading "unverified".
    malformed_links = {u: malformed(u) for u in all_links if malformed(u)}
    requestable = [u for u in all_links if u not in malformed_links]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(status_of, requestable))

    broken, unverified = [], []
    for url, (status, note) in zip(requestable, results):
        if status in GONE:
            broken.append(f"{url} -> {status}")
        elif status is None or status in NOT_VERIFIABLE or status >= 500:
            why = f"{status}" if status else (note or "unreachable")
            unverified.append(f"{url} -> {why}")

    for url, why in malformed_links.items():
        print(f"  MALFORMED   {url} -> {why}")
    for line in broken:
        print(f"  GONE        {line}")
    for line in unverified:
        print(f"  unverified  {line} (not counted as broken)")

    print()
    total_bad = len(broken) + len(malformed_links)
    if total_bad:
        print(
            f"{total_bad} link(s) a reader cannot follow: {len(broken)} return 404/410 "
            f"and {len(malformed_links)} are malformed. Repoint or remove them."
        )
        return 1
    checked = len(all_links) - len(unverified)
    print(
        f"PASS  {checked} of {len(all_links)} external links resolve; {len(unverified)} "
        "could not be verified from CI and are not treated as broken"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
