#!/usr/bin/env python3
"""Every external link a reader can follow must resolve.

Why this exists
---------------
Two project links on the portfolio were dead and nothing was watching. One pointed
at a repository that is private, so it returned 404 for every visitor; the other
had a phrase pasted into the URL, so it resolved a repository name containing a
space and parentheses. Both sat there until someone checked all 48 links by hand.
A portfolio that 404s spends the credibility the rest of the page earns, so the
check belongs here, where it runs on every push and weekly.

What it covers
--------------
Both kinds of surface, because both rot the same way:

  * the **live pages** a reader lands on, fetched over the network; and
  * the **local surfaces** - the profile README, the project READMEs, the hire page
    and the portfolio source - which CI already checks out beside this repository.

Sibling paths are resolved the same way `check_surfaces.py` resolves them, so the
two agree about where the workspace is. A surface that is not present is skipped;
but if nothing at all could be read the run fails, because a check that quietly
found nothing to check is the failure mode this whole repository exists to avoid.

What fails the run
------------------
**404 and 410 only.** Those are the codes that mean *gone*.

403 and 429 do **not** fail it. A 403 usually means the site declines automated
clients, which says nothing about whether a reader can reach the page; failing on
it would turn this red for reasons that are not the repository's fault, and a check
that cries wolf is one someone switches off. Those are reported as unverified so
the distinction stays visible. So are timeouts and 5xx, after one retry.

Malformed URLs - a space, a quote, anything that cannot be requested - **do** fail
it. They are decided before any request, which matters: the first version of this
check missed one of the two defects it was written for, because the malformed link
failed before it could 404 and was classified as unverified.

Stdlib only, like the rest of this repository: no dependency to keep in step.
"""

from __future__ import annotations

import pathlib
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PAGES = [
    ("https://sushantpoudel2028.com.np/", "the portfolio (live)"),
    ("https://sushant-me.github.io/hire/", "the hire page (live)"),
]

# Local surfaces, relative to the workspace. Same convention as SURFACES in
# check_surfaces.py, and deliberately overlapping with it: the render of a page and
# its source should not disagree about where a link points.
LOCAL_SURFACES = [
    "profile-readme/README.md",
    "reputation/README.md",
    "hire/index.html",
    "portfolio/src/app/page.tsx",
    "agentbound/README.md",
    "mcp-nameguard/README.md",
    "policygate/README.md",
    "mcpaudit/README.md",
    "trajectorycheck/README.md",
    "tool-boundary-corpus/README.md",
    "writeups/README.md",
    "Edge-Native_Semantic_Firewall_/README.md",
]

# Nothing to read is itself a failure. A partial checkout may legitimately miss a
# sibling, but a run that read almost nothing is not evidence that the links work.
MIN_SOURCES = 6

# Assets and services that are not pages a reader follows: fonts, badge images, and
# the vocabularies a search engine reads rather than a person.
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
    # Some hosts 403 a request with no user agent; this is not evasion, it is making
    # the request look like the browser request it is meant to imitate.
    "User-Agent": "Mozilla/5.0 (compatible; reputation-link-check/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

GONE = {404, 410}
NOT_VERIFIABLE = {401, 403, 405, 406, 429}

# A URL a reader cannot follow even if the host is up. Whitespace is never valid in
# a URL; the rest break parsing. This exists because the first version of this check
# missed the malformed link it was written for: the request failed before it could
# return 404, so it was reported as unverified and would have passed.
MALFORMED_RE = re.compile(r'[\s<>"{}|\\^`]')


def malformed(url: str) -> str:
    m = MALFORMED_RE.search(url)
    return f"contains {m.group(0)!r}" if m else ""


def resolve_workspace() -> pathlib.Path:
    """The directory holding the sibling repositories, or this one if there is none.

    Same resolution as check_surfaces.py. Keeping them identical matters: if one
    looks in the wrong place it finds nothing, and finding nothing looks exactly
    like everything being fine.
    """
    here = pathlib.Path(__file__).resolve().parent
    for candidate in (here.parent, here):
        if (candidate / "portfolio").exists() or (candidate / "profile-readme").exists():
            return candidate
    return here


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
    last = "unreachable"
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.status, ""
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:
            last = type(e).__name__
    return None, last


LINK_RE = re.compile(r'href="(https?://[^"]+)"')
SRC_RE = re.compile(r'src="(https?://[^"]+)"')
MD_RE = re.compile(r"!?\[[^\]]*\]\((https?://[^)\s]+)")


def links_in(text: str) -> set[str]:
    """External links in either an HTML surface or a Markdown one."""
    raw = set(LINK_RE.findall(text)) | set(SRC_RE.findall(text)) | set(MD_RE.findall(text))
    out = set()
    for url in raw:
        url = url.rstrip("/").rstrip(".,;")
        if any(s in url for s in SKIP):
            continue
        out.add(url)
    return out


def main() -> int:
    # url -> where it was found, so a failure says which page or file to edit.
    origins: dict[str, set[str]] = {}
    sources_read = 0

    for url, label in PAGES:
        html = fetch(url)
        if html is None:
            print(f"  unreachable  {label} ({url}) - skipped")
            continue
        sources_read += 1
        for link in links_in(html):
            origins.setdefault(link, set()).add(label)

    workspace = resolve_workspace()
    for rel in LOCAL_SURFACES:
        path = workspace / rel
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        sources_read += 1
        for link in links_in(text):
            origins.setdefault(link, set()).add(rel)

    if sources_read < MIN_SOURCES:
        print(
            f"FAIL  only {sources_read} surface(s) could be read, expected at least "
            f"{MIN_SOURCES}. Checked out beside this repository? A run that found "
            "nothing to check has not checked anything."
        )
        return 1

    all_links = sorted(origins)
    print(f"checking {len(all_links)} external links across {sources_read} surfaces\n")

    malformed_links = {u: malformed(u) for u in all_links if malformed(u)}
    requestable = [u for u in all_links if u not in malformed_links]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(status_of, requestable))

    broken, unverified = [], []
    for url, (status, note) in zip(requestable, results):
        if status in GONE:
            broken.append(f"{url} -> {status}  [{', '.join(sorted(origins[url]))}]")
        elif status is None or status in NOT_VERIFIABLE or status >= 500:
            why = f"{status}" if status else (note or "unreachable")
            unverified.append(f"{url} -> {why}")

    for url, why in sorted(malformed_links.items()):
        print(f"  MALFORMED   {url} -> {why}  [{', '.join(sorted(origins[url]))}]")
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
        f"PASS  {checked} of {len(all_links)} external links resolve across "
        f"{sources_read} surfaces; {len(unverified)} could not be verified from CI and "
        "are not treated as broken"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
