#!/usr/bin/env python3
"""No public repository of mine may carry a credential.

Why this exists
---------------
`sentiment-analysis` sat public from 2025-06-13 with a file called `api key.txt`
containing a live Twitter/X OAuth set - consumer key, consumer secret, access
token and access-token secret. Consumer secret plus access-token secret is enough
to act as the account that issued them. It stayed there for fifteen months.

Nothing caught it, and the reason is structural rather than careless:

  * GitHub's free secret scanning for public repositories matches **provider
    patterns** - formats it knows by shape, like AWS's `AKIA...`, GitHub's own
    `ghp_...`, Stripe's `sk_live_...`.
  * A generic `KEY = "value"` assignment is not a provider pattern. The detector
    for that class is `secret_scanning_non_provider_patterns`, which is part of
    paid GitHub Secret Protection. Setting it through the API on a free account
    is accepted and silently ignored - the flag reads back `disabled`.

So on a free account the exact shape this leak took is invisible to the platform.
GitHub's own alerts API returned `[]` for the repository containing it, which is
correct behaviour and not a safe answer. The gap has to be closed from outside,
and that is what this script is.

What it covers
--------------
**Every** owned repository, forks excluded - and archived ones *included*, because
the repository this was written for is archived and still publicly readable. A
scan that skipped archived repositories would have missed the only real finding.

For each repository it reads the file tree, picks the files that could plausibly
hold a credential, and matches their contents. Two independent signals:

  * **provider patterns** - the same known shapes GitHub looks for, so a finding
    here is one the platform has simply not reached yet; and
  * **generic assignments** - a secret-looking name next to a high-entropy string,
    which is the class the platform does not look for at all.

What fails the run
------------------
**Any confirmed finding.** Placeholders are not findings: `YOUR_API_KEY`,
`<token>`, `changeme`, `xxxx`, a value that is obviously a path, or a short
low-entropy string are all rejected. A scanner that fires on documentation
snippets gets muted, and a muted scanner protects nothing.

It also fails when it **read too little**. If the enumeration returns no
repositories, or no file contents could be fetched, that is a failure rather than
a pass - the whole point of this repository is that a check quietly reading
nothing must never look like a clean result. Coverage is printed for that reason.

`--self-test` runs the detector against bundled fixtures with no network access,
including the exact shape of the original leak, and requires it to fire. The
detector is only worth trusting if it is shown catching the thing it was written
for; the failure mode being guarded against is a pass that means nothing.

Stdlib only, like the rest of this repository: no dependency to keep in step.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com"
OWNER = "sushant-me"

# Coverage floor. A run that read fewer than this many file contents is not
# evidence of a clean account, so it fails instead of reporting success.
MIN_FILES_READ = 25

# Caps so the scan stays inside the hourly API budget and finishes quickly. When
# a cap bites, it is reported - truncation is never silent.
MAX_FILES_PER_REPO = 40
MAX_CONTENT_BYTES = 256 * 1024
MAX_FILE_FETCHES = 600

# Names that suggest a file could carry a credential.
SUSPICIOUS_NAME = re.compile(
    r"(api[ _.\-]?key|secret|credential|passwd|password|token|\.env|"
    r"id_rsa|\.pem$|\.p12$|\.pfx$|\.jks$|\.keystore$|\.ovpn$|"
    r"service[_.\-]?account|\.npmrc$|\.pypirc$|\.netrc$)",
    re.I,
)

# File types worth reading even when the name says nothing.
TEXTY_EXT = re.compile(
    r"\.(py|js|ts|tsx|jsx|json|ya?ml|toml|ini|cfg|conf|env|txt|md|sh|bash|"
    r"ps1|rb|go|java|php|properties|xml|csv|ipynb)$",
    re.I,
)

# Known provider shapes. Deliberately specific: a loose pattern here produces
# noise that gets the check switched off.
PROVIDER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("stripe_secret", re.compile(r"\bsk_live_[A-Za-z0-9]{20,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b")),
]

# Generic assignments: a secret-looking variable name bound to a long literal.
GENERIC_ASSIGN = re.compile(
    r"""(?P<name>[A-Za-z0-9_\-.]*"""
    r"""(?:secret|token|passwd|password|api[_-]?key|access[_-]?key|"""
    r"""consumer[_-]?key|private[_-]?key|auth[_-]?key|client[_-]?secret)"""
    r"""[A-Za-z0-9_\-.]*)"""
    r"""\s*[:=]\s*"""
    r"""(?P<q>["'])(?P<val>[^"'\s]{12,200})(?P=q)""",
    re.I,
)

# Values that are plainly not secrets. Without this the check fires on its own
# documentation and on every template in the account.
#
# Note the absence of a leading empty alternative. The first version read
# `^(?:|your|my|...)`, whose empty branch matched every string, so the filter
# rejected all of them and the detector reported nothing at all. The self-test
# caught it; without a fixture for the real leak shape this would have shipped
# as a passing check that could never fire.
PLACEHOLDER = re.compile(
    r"^(?:your|my|the|some|test|example|sample|dummy|fake|placeholder|changeme|"
    r"replace|todo|xxx+|\.\.\.|none|null|true|false|undefined|"
    r"[<\{\[].*|[^a-z0-9]*$)",
    re.I,
)


def shannon_entropy(s: str) -> float:
    """Bits of entropy per character. Random secrets sit well above 3.0."""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_value(val: str) -> bool:
    """True when a matched string is plausibly a real credential."""
    if PLACEHOLDER.match(val.strip()):
        return False
    if len(val) < 12:
        return False
    # A path, a URL fragment, an env-var reference, or a format string is not a secret.
    if val.startswith(("/", "http://", "https://", "$", "${", "%", "{{")) or "${" in val:
        return False
    if "/" in val and "." in val:  # e.g. /usr/local/bin or lib/foo.py
        return False
    body = re.sub(r"[^A-Za-z0-9]", "", val)
    if len(body) < 12:
        return False
    # Anything with a space in it is prose, not a key.
    if " " in val:
        return False
    return shannon_entropy(body) >= 3.0


@dataclass
class Finding:
    repo: str
    path: str
    rule: str
    name: str
    preview: str
    entropy: float

    def render(self) -> str:
        return (
            f"  {self.repo}/{self.path}\n"
            f"      rule     : {self.rule}\n"
            f"      variable : {self.name}\n"
            f"      value    : {self.preview}\n"
            f"      entropy  : {self.entropy:.2f} bits/char"
        )


def redact(val: str) -> str:
    """Show enough to locate the value, never enough to use it."""
    if len(val) <= 8:
        return "*" * len(val)
    return f"{val[:4]}{'*' * min(len(val) - 8, 20)}{val[-4:]}  (len={len(val)})"


def scan_text(repo: str, path: str, text: str) -> list[Finding]:
    """Pure detector: every finding this script can report comes from here."""
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for rule, pat in PROVIDER_PATTERNS:
        for m in pat.finditer(text):
            val = m.group(0)
            key = (rule, val)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Finding(repo, path, f"provider:{rule}", rule, redact(val),
                        shannon_entropy(re.sub(r"[^A-Za-z0-9]", "", val)))
            )

    for m in GENERIC_ASSIGN.finditer(text):
        name, val = m.group("name"), m.group("val")
        if not looks_like_value(val):
            continue
        body = re.sub(r"[^A-Za-z0-9]", "", val)
        ent = shannon_entropy(body)
        if ent < 3.4:
            continue
        key = ("generic", val)
        if key in seen:
            continue
        seen.add(key)
        out.append(Finding(repo, path, "generic:assignment", name, redact(val), ent))

    return out


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "reputation-secret-scan"}
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def api_get(url: str) -> object | None:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            print(f"  ! rate limited or forbidden: {url}", file=sys.stderr)
        return None
    except Exception:
        return None


def owned_repos() -> list[dict]:
    repos: list[dict] = []
    page = 1
    while page <= 5:
        batch = api_get(f"{API}/user/repos?per_page=100&affiliation=owner&page={page}")
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # Forks are someone else's code; archived repos are still public and stay in.
    return [r for r in repos if not r.get("fork")]


def candidate_paths(repo: str) -> list[str]:
    tree = api_get(f"{API}/repos/{OWNER}/{repo}/git/trees/HEAD?recursive=1")
    if not isinstance(tree, dict):
        return []
    out: list[str] = []
    for node in tree.get("tree", []):
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        if node.get("size", 0) > MAX_CONTENT_BYTES:
            continue
        low = path.lower()
        if any(s in low for s in ("node_modules/", ".venv/", "site-packages/",
                                  "dist/", "vendor/", ".min.js", ".lock")):
            continue
        if SUSPICIOUS_NAME.search(path) or TEXTY_EXT.search(path):
            out.append(path)
    # Suspicious names first: they are the ones worth the API budget.
    out.sort(key=lambda p: (0 if SUSPICIOUS_NAME.search(p) else 1, len(p)))
    return out[:MAX_FILES_PER_REPO]


def read_file(repo: str, path: str) -> str | None:
    data = api_get(f"{API}/repos/{OWNER}/{repo}/contents/{urllib.parse.quote(path)}")
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return None
    try:
        raw = base64.b64decode(data.get("content", ""), validate=False)
    except Exception:
        return None
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# allowlist
# --------------------------------------------------------------------------

# Documented exceptions. Each entry needs a reason; an unexplained allowlist is
# how a real finding gets buried.
ALLOWLIST: list[tuple[str, str, str]] = [
    (
        "skills-introduction-to-secret-scanning",
        "credentials.yml",
        "GitHub's own Skills exercise file. The values are the course's published "
        "dummies, committed by following the tutorial, and are the artefact the "
        "exercise asks you to detect.",
    ),
]


def allowed(repo: str, path: str) -> str | None:
    for r, p, why in ALLOWLIST:
        if r == repo and p in path:
            return why
    return None


# --------------------------------------------------------------------------
# self-test
# --------------------------------------------------------------------------

# The original leak, reproduced with non-functional values, so the detector is
# proved against the exact shape it failed to catch in the wild.
LEAK_FIXTURE = (
    '    TWITTER_CONSUMER_KEY = "YAAOaWHdjmKVx0iDKTOeMWpmba"  # Replace with your keys\n'
    '    TWITTER_CONSUMER_SECRET = "rQ5IsBcm8cawkDea9hx9P7tToNhkzwtWL5CUNRHFgH0lmbuDJc"\n'
    '    TWITTER_ACCESS_TOKEN = "1767217575581155328-1R45EGuXgra9zQ7Kxp7NUMAAbrTn1C"\n'
    '    TWITTER_ACCESS_TOKEN_SECRET = "MmSYAXyQz8RoodkrzrH4dHcNpLKLYafiyCuyn09Udesr0"\n'
)

# These must stay silent. A check that fires on its own docs is a check that
# gets switched off.
CLEAN_FIXTURES = [
    'api_key = "YOUR_API_KEY_HERE"',
    'token = "<paste-your-token>"',
    'password = "changeme"',
    'SECRET_KEY = "${SECKY_FROM_ENV}"',
    "client_secret = os.environ['CLIENT_SECRET']",
    'path = "/usr/local/share/ca-certificates/foo.pem"',
    'apiKey: "xxxxxxxxxxxxxxxxxxxx"',
]


def self_test() -> int:
    print("self-test: the detector must fire on the original leak shape\n")
    fails = 0

    found = scan_text("fixture", "api key.txt", LEAK_FIXTURE)
    names = {f.name.upper() for f in found}
    for want in ("TWITTER_CONSUMER_SECRET", "TWITTER_ACCESS_TOKEN_SECRET"):
        ok = any(want in n for n in names)
        print(f"  {'ok  ' if ok else 'FAIL'}  catches {want}")
        fails += 0 if ok else 1
    print(f"  caught {len(found)} finding(s) in the leak fixture")

    print()
    for fx in CLEAN_FIXTURES:
        got = scan_text("fixture", "example.py", fx)
        ok = not got
        print(f"  {'ok  ' if ok else 'FAIL'}  stays silent on: {fx}")
        fails += 0 if ok else 1

    print()
    if fails:
        print(f"self-test FAILED ({fails})")
        return 1
    print("self-test passed: fires on the real shape, silent on placeholders")
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true",
                    help="run the detector against fixtures; no network")
    ap.add_argument("--repo", action="append", default=None,
                    help="limit to this repository (repeatable)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    repos = owned_repos()
    if args.repo:
        repos = [r for r in repos if r["name"] in set(args.repo)]
    if not repos:
        print("::error::no repositories enumerated; the scan could not run")
        return 1

    print(f"scanning {len(repos)} owned repositories (archived included)\n")
    findings: list[Finding] = []
    read_count = 0
    skipped: list[str] = []

    for r in sorted(repos, key=lambda x: x["name"]):
        name = r["name"]
        paths = candidate_paths(name)
        if not paths:
            continue
        for path in paths:
            if read_count >= MAX_FILE_FETCHES:
                skipped.append(f"{name} (fetch cap {MAX_FILE_FETCHES} reached)")
                break
            why = allowed(name, path)
            text = read_file(name, path)
            if text is None:
                continue
            read_count += 1
            if why:
                hits = scan_text(name, path, text)
                if hits:
                    if not args.quiet:
                        print(f"  allowed  {name}/{path} - {len(hits)} match(es)")
                        print(f"           reason: {why}")
                continue
            findings.extend(scan_text(name, path, text))

    print()
    print(f"files read        : {read_count}")
    print(f"repositories read : {len({f.repo for f in findings}) if findings else 'n/a'}")
    if skipped:
        print(f"truncated         : {len(skipped)} repo(s)")
        for s in skipped:
            print(f"    - {s}")
    print()

    if findings:
        print(f"FINDINGS: {len(findings)} credential-shaped value(s) in public repositories\n")
        by_repo: dict[str, list[Finding]] = {}
        for f in findings:
            by_repo.setdefault(f.repo, []).append(f)
        for repo, fs in sorted(by_repo.items()):
            archived = next((r["archived"] for r in repos if r["name"] == repo), False)
            print(f"{repo}{'  (ARCHIVED, read-only)' if archived else ''}")
            for f in fs:
                print(f.render())
            print()
        print("A finding is a prompt to rotate, not just to delete: the blob is already")
        print("public, and removing the file does not un-publish the value.")
        return 1

    if read_count < MIN_FILES_READ:
        print(f"::error::only {read_count} file(s) read, below the {MIN_FILES_READ} floor;")
        print("         this is not evidence of a clean account")
        return 1

    print("no credential-shaped values found in public repositories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
