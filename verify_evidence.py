#!/usr/bin/env python3
"""Re-check every claim in `evidence.json` against the source it names.

The point of this file is that a claim in a CV cannot be checked by a reader, so
it has to be checkable by *something*. This script is that something: it reads
`evidence.json`, hits each claim's own source live, and exits non-zero if a
machine-checkable claim no longer holds. A claim that cannot be checked from
outside (a signed letter, a conference acceptance email) is reported as
`on-request` rather than passed silently, so the difference between "verified"
and "asserted, documentation available" stays visible.

    python3 verify_evidence.py            # human-readable table
    python3 verify_evidence.py --json     # machine-readable, for CI or a hook

No third-party dependencies: GitHub is queried through `gh api` (already
authenticated), the rest over urllib.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence.json"

PASS, FAIL, SKIP = "PASS", "FAIL", "on-request"


def gh_api(path: str) -> dict | list | None:
    """GET a GitHub API path, publicly first and through `gh` only if needed.

    The public API needs no credentials and works in CI, where the workflow's own
    token can only read the repository it runs in. `gh` is the fallback for the
    local case where the unauthenticated hourly limit has been used up.
    """
    public = http_json(f"https://api.github.com/{path}")
    if public is not None:
        return public
    try:
        out = subprocess.run(
            ["gh", "api", path],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def http_json(url: str) -> dict | None:
    # The leaderboard API sits behind Cloudflare and answers 403 to the default
    # urllib user-agent, so send one.
    request = urllib.request.Request(
        url, headers={"User-Agent": "evidence-verifier/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def check_hackinghub_rank(claim: dict) -> tuple[str, str]:
    payload = http_json(claim["source"]["url"])
    if not payload:
        return FAIL, "leaderboard API unreachable"
    board = payload.get("leaderboard", {})
    rows = board.get("leaderboard", {})
    expect = claim["verification"]["expect"]
    me = next((r for r in rows.values()
               if r.get("username") == expect["username"]), None)
    if me is None:
        return FAIL, f"{expect['username']} is not on the board"
    problems = [f"{key}: expected {value}, found {me.get(key)}"
                for key, value in expect.items() if me.get(key) != value]
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, (f"rank {me['rank']}, {me['flags']} flags, {me['xp']} XP "
                  f"({board.get('title', '?')})")


def _pr(repo: str, number: int) -> dict | None:
    return gh_api(f"repos/{repo}/pulls/{number}")


def check_github_pr_merged(claim: dict) -> tuple[str, str]:
    source = claim["source"]
    pr = _pr(source["repo"], source["number"])
    if pr is None:
        return FAIL, f"could not read {source['repo']}#{source['number']}"
    if not pr.get("merged"):
        return FAIL, f"state={pr.get('state')} merged={pr.get('merged')}"
    who = (pr.get("merged_by") or {}).get("login", "?")
    return PASS, f"merged {str(pr.get('merged_at'))[:10]} by {who}"


def check_github_pr_open_or_merged(claim: dict) -> tuple[str, str]:
    source = claim["source"]
    pr = _pr(source["repo"], source["number"])
    if pr is None:
        return FAIL, f"could not read {source['repo']}#{source['number']}"
    if pr.get("merged"):
        return PASS, f"merged (was {pr['state']})"
    if pr.get("state") == "open":
        return PASS, "open"
    return FAIL, f"closed unmerged: {source['repo']}#{source['number']}"


def check_github_prs_open_or_merged(claim: dict) -> tuple[str, str]:
    sources = [claim["source"]] + claim.get("extra_sources", [])
    pairs: list[tuple[str, int]] = []
    for source in sources:
        if "numbers" in source:
            pairs += [(source["repo"], n) for n in source["numbers"]]
        elif "number" in source:
            pairs.append((source["repo"], source["number"]))
    notes, failures = [], []
    for repo, number in pairs:
        pr = _pr(repo, number)
        if pr is None:
            failures.append(f"{repo}#{number} unreadable")
            continue
        state = "merged" if pr.get("merged") else pr.get("state")
        if state not in ("open", "merged"):
            failures.append(f"{repo}#{number} {state}")
        notes.append(f"{repo.split('/')[-1]}#{number} {state}")
    if failures:
        return FAIL, "; ".join(failures)
    return PASS, ", ".join(notes)


def check_github_issues_open(claim: dict) -> tuple[str, str]:
    source = claim["source"]
    open_numbers, closed = [], []
    for number in source["numbers"]:
        issue = gh_api(f"repos/{source['repo']}/issues/{number}")
        if issue is None:
            closed.append(f"#{number} unreadable")
        elif issue.get("state") == "open":
            open_numbers.append(number)
        else:
            closed.append(f"#{number} {issue.get('state')}")
    if closed:
        return FAIL, "; ".join(closed)
    return PASS, f"{len(open_numbers)} issues open: " + ", ".join(
        f"#{n}" for n in open_numbers)


def check_public_repo_exists(claim: dict) -> tuple[str, str]:
    url = claim["source"]["url"]
    slug = url.rstrip("/").split("github.com/")[-1]
    repo = gh_api(f"repos/{slug}")
    if repo is None:
        return FAIL, f"{slug} unreadable"
    return PASS, (f"{slug}: {repo.get('language') or 'n/a'}, "
                  f"pushed {str(repo.get('pushed_at'))[:10]}")


CHECKS = {
    "hackinghub_rank": check_hackinghub_rank,
    "github_pr_merged": check_github_pr_merged,
    "github_pr_open_or_merged": check_github_pr_open_or_merged,
    "github_prs_open_or_merged": check_github_prs_open_or_merged,
    "github_issues_open": check_github_issues_open,
    "public_repo_exists": check_public_repo_exists,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable results")
    args = parser.parse_args()

    claims = json.loads(EVIDENCE.read_text())["claims"]
    results, failures = [], 0

    for claim in claims:
        method = claim["verification"]["method"]
        check = CHECKS.get(method)
        if check is None:
            status, note = SKIP, claim["verification"].get(
                "on_request", "not machine-checkable")
        else:
            status, note = check(claim)
        if status == FAIL:
            failures += 1
        results.append({"id": claim["id"], "category": claim["category"],
                        "status": status, "note": note,
                        "claim": claim["claim"]})

    if args.json:
        print(json.dumps({"results": results, "failures": failures}, indent=2))
        return 1 if failures else 0

    print(f"{'STATUS':<11} {'CLAIM':<62} NOTE")
    print("-" * 118)
    for row in results:
        label = row["claim"][:60] + ("…" if len(row["claim"]) > 60 else "")
        print(f"{row['status']:<11} {label:<62} {row['note']}")
    print("-" * 118)
    checked = sum(1 for r in results if r["status"] in (PASS, FAIL))
    on_request = sum(1 for r in results if r["status"] == SKIP)
    print(f"{len(results)} claims: {checked} checked live, "
          f"{on_request} documented on request, {failures} failing")
    if failures:
        print("\nA published claim no longer holds. Fix the claim or the source "
              "before it goes in front of anyone.", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
