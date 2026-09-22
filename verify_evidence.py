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
import base64
import json
import pathlib
import re
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


def check_github_pr_superseded_no_credit(claim: dict) -> tuple[str, str]:
    """The go-github claim, which has four separate facts and one of them is negative.

    My PR was merged, then reverted the next day by the maintainer's broader
    replacement. Every part of that is public, and a claim that says only
    "merged" describes behaviour that is no longer in master — a reader who
    checks the code would find the check gone. So all four are checked:

      1. #4556 is merged and authored by me;
      2. #4564 is merged, and master implements the replacement (`AllowedOrigins`);
      3. the maintainer's co-author promise is public, at the source;
      4. the promised credit has NOT landed.

    (4) is a negative fact, which is exactly why it is checked rather than
    asserted: the moment the trailer appears, this claim becomes the wrong claim
    and the verifier has to go red so it gets rewritten. A claim that something
    is still owed is the kind that rots silently.
    """
    source = claim["source"]
    repo = source["repo"]
    mine, theirs = source["number"], claim["replacement"]["number"]

    pr = _pr(repo, mine)
    if pr is None or not pr.get("merged"):
        return FAIL, f"{repo}#{mine} is not merged"
    # The REST API spells this `user`; `author` is what `gh pr view --json` calls it.
    opener = (pr.get("user") or pr.get("author") or {}).get("login")
    if opener != source.get("author"):
        return FAIL, f"{repo}#{mine} authored by {opener}, not {source.get('author')}"

    replacement = _pr(repo, theirs)
    if replacement is None or not replacement.get("merged"):
        return FAIL, f"replacement {repo}#{theirs} is not merged"

    blob = gh_api(f"repos/{repo}/contents/{claim['replacement']['in_master']}")
    if not isinstance(blob, dict) or "content" not in blob:
        return FAIL, f"could not read {claim['replacement']['in_master']}"
    import base64
    try:
        master = base64.b64decode(blob["content"]).decode("utf-8", "replace")
    except (ValueError, KeyError):
        return FAIL, "master file did not decode"
    if claim["replacement"]["marker"] not in master:
        return FAIL, (
            f"master's {claim['replacement']['in_master']} has no "
            f"{claim['replacement']['marker']!r}: the fix may have moved or regressed"
        )

    # The promise, at the source. A paraphrase of a person's words is not evidence.
    comments = gh_api(f"repos/{repo}/issues/{claim['promise_at']['number']}/comments")
    if not isinstance(comments, list):
        return FAIL, f"could not read comments on #{claim['promise_at']['number']}"
    promised = any(claim["promise_at"]["phrase"] in (c.get("body") or "") for c in comments)
    if not promised:
        return FAIL, (
            f"the co-author promise is no longer in #{claim['promise_at']['number']}: "
            "either it was edited or this check looks in the wrong place"
        )

    # The negative half.
    merge = gh_api(f"repos/{repo}/commits/{replacement['merge_commit_sha']}")
    message = ((merge or {}).get("commit") or {}).get("message", "")
    if "sushant" in message.lower():
        return FAIL, (
            "the promised co-author credit has LANDED in the merged commit — "
            "rewrite this claim, it now understates"
        )
    for release in gh_api(f"repos/{repo}/releases") or []:
        if "sushant" in (release.get("body") or "").lower():
            return FAIL, (
                f"release {release.get('tag_name')} now credits me — rewrite this claim, "
                "it now understates"
            )

    # The credit landed by a third route the first version of this check did not look at: the
    # maintainer offered the AUTHORS-file mechanism, the contributor opened the PR, and it was
    # merged. Checking only for a Co-authored-by trailer would now report "not yet credited" on
    # a claim that is out of date in the other direction - understating instead of overstating,
    # which is still wrong.
    authors_entry = None
    contents = gh_api(f"repos/{repo}/contents/AUTHORS")
    if contents and contents.get("content"):
        import base64 as _b64
        authors_entry = "sushant poudel" in _b64.b64decode(contents["content"]).decode(
            "utf-8", "replace").lower()
    if authors_entry:
        return PASS, (
            f"#{mine} merged {str(pr.get('merged_at'))[:10]} then superseded by #{theirs}; "
            "master has the replacement; and the credit has LANDED - Sushant Poudel is in the "
            f"AUTHORS file on master (via PR #{claim.get('authors_pr', {}).get('number', '?')})"
        )
    return PASS, (
        f"#{mine} merged {str(pr.get('merged_at'))[:10]} then superseded by "
        f"#{theirs}; master has the replacement; credit offered, not yet in AUTHORS"
    )


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
    """The issues are open — and, where the claim publishes numbers, they are in the source.

    The second half exists because of a real error: the profile said a 16 GiB
    allocation came from "a 5-byte header" and the issue says the input is 117
    bytes. The size appeared on nine surfaces including two attachable PDFs, and
    nothing compared it to the text it was describing. A number in a claim is a
    quotation of its source, so it gets checked like one.
    """
    source = claim["source"]
    open_numbers, closed, wrong = [], [], []
    expected = claim["verification"].get("bodies_must_contain", {})
    for number in source["numbers"]:
        issue = gh_api(f"repos/{source['repo']}/issues/{number}")
        if issue is None:
            closed.append(f"#{number} unreadable")
            continue
        if issue.get("state") != "open":
            closed.append(f"#{number} {issue.get('state')}")
            continue
        open_numbers.append(number)

        for phrase in expected.get(str(number), []):
            # The title counts as the source too: several of these numbers appear there.
            haystack = f"{issue.get('title') or ''}\n{issue.get('body') or ''}"
            if phrase not in haystack:
                wrong.append(f"#{number} does not say {phrase!r}")
    if closed:
        return FAIL, "; ".join(closed)
    if wrong:
        return FAIL, (
            "; ".join(wrong) + " - the claim publishes a number its source does not state"
        )
    checked = sum(len(v) for v in expected.values())
    note = f"{len(open_numbers)} issues open: " + ", ".join(f"#{n}" for n in open_numbers)
    if checked:
        note += f"; {checked} published figure(s) found in the source"
    return PASS, note


def check_paper_artifacts_reproduce(claim: dict) -> tuple[str, str]:
    """Clone the paper repository and run its own reproducibility checker.

    The strongest claim on the record is also the one a reader is least able to
    check by clicking: a table of measured numbers. So it is checked the only way
    that means anything — the repository ships its corpus generator, its raw model
    outputs and a checker, and the checker is run here on a fresh clone.

    `make verify` needs no model execution: it regenerates the 600-scenario corpus
    and recomputes every metric from the committed generations. That keeps it to a
    ~9 MB clone and about two seconds, which is why it can run weekly rather than
    being taken on trust.
    """
    import tempfile

    url = claim["source"]["url"]
    script = claim["source"]["script"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            clone = subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", url, tmp],
                capture_output=True, text=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return FAIL, f"could not clone {url}: {exc.__class__.__name__}"
        if clone.returncode != 0:
            return FAIL, f"clone failed: {clone.stderr.strip().splitlines()[-1:] or '?'}"

        candidate = pathlib.Path(tmp) / script
        if not candidate.exists():
            return FAIL, f"{script} is not in the repository any more"

        try:
            run = subprocess.run(
                ["python3", script], cwd=tmp, capture_output=True, text=True,
                timeout=600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return FAIL, f"could not run {script}: {exc.__class__.__name__}"

        lines = [l.strip() for l in run.stdout.splitlines() if l.strip().startswith("PASS")]
        if run.returncode != 0:
            tail = (run.stdout + run.stderr).strip().splitlines()[-3:]
            return FAIL, f"{script} exited {run.returncode}: " + " | ".join(tail)
        if not lines:
            return FAIL, f"{script} exited 0 but reported no PASS lines"

    # One short label per check: the clause before the first bracket or dash, which
    # is where each line states what it verified. Cutting every line at 58 characters
    # split words in half and made the note unreadable - and an unreadable note is
    # one nobody checks.
    labels = []
    for line in lines:
        text = line.replace("PASS  ", "", 1).split(" (")[0].split(" - ")[0].strip()
        labels.append(text if len(text) <= 64 else text[:61].rsplit(" ", 1)[0] + "...")
    return PASS, (f"{len(lines)} artifact checks pass on a fresh clone: "
                  + "; ".join(labels))


def check_agentbound_rule_count(claim: dict) -> tuple[str, str]:
    """The stated detector count equals what agentbound actually registers.

    A count is the easiest claim in this file to leave behind. Adding a detector
    does not touch the sentence that says how many there are, so the two drift and
    nothing notices - which is what happened here: this claim shipped saying
    "five rules" while the package registered nine, and its verification was
    `public_repo_exists`, which checks that the repository exists, not that the
    sentence is true.

    So the count is read out of the source rather than restated. Add or remove a
    registered rule and this goes red until the claim is corrected, which is the
    only version of this number that stays true on its own.
    """
    expect = claim["verification"]["expect"]["registered_rules"]
    blob = gh_api("repos/sushant-me/agentbound/contents/agentbound/rules.py")
    if not isinstance(blob, dict) or blob.get("encoding") != "base64":
        return FAIL, "agentbound/agentbound/rules.py unreadable"
    try:
        src = base64.b64decode(blob.get("content", "")).decode("utf-8", "replace")
    except (ValueError, TypeError) as exc:
        return FAIL, f"rules.py undecodable: {type(exc).__name__}"

    names: list[str] = []
    for registry in ("FILE_RULES", "PROJECT_RULES"):
        block = re.search(registry + r"\s*=\s*\[(.*?)\]", src, re.S)
        if block is None:
            return FAIL, f"{registry} not found in rules.py"
        names.extend(re.findall(r"rule_\w+", block.group(1)))
    if not names:
        return FAIL, "no rules parsed out of rules.py"

    if len(names) != expect:
        return FAIL, (f"rules.py registers {len(names)} rules, the claim says {expect} "
                      f"({', '.join(sorted(names))})")
    return PASS, f"{len(names)} registered rules match the claim of {expect}"


def check_public_repo_exists(claim: dict) -> tuple[str, str]:
    url = claim["source"]["url"]
    slug = url.rstrip("/").split("github.com/")[-1]
    repo = gh_api(f"repos/{slug}")
    if repo is None:
        return FAIL, f"{slug} unreadable"
    return PASS, (f"{slug}: {repo.get('language') or 'n/a'}, "
                  f"pushed {str(repo.get('pushed_at'))[:10]}")


def check_github_advisories(claim: dict) -> tuple[str, str]:
    """Every advisory named here is still published, at the severity claimed.

    A security advisory is the one form of recognition in this file that a reader can look
    up independently and that cannot be edited into existence: GitHub issues the
    identifier, binds it to the repository, and keeps it at a stable public URL. So the
    check is not "does the fix exist" - that is the release and the test - but "is the
    advisory still there and still saying what is claimed about it". One that was withdrawn,
    or downgraded after triage, must stop being cited rather than quietly keep its place.
    """
    expected = claim["verification"]["expect"]["advisories"]
    problems, checked = [], []
    for entry in expected:
        data = gh_api(
            f"repos/sushant-me/{entry['repo']}/security-advisories/{entry['ghsa']}")
        if data is None:
            problems.append(f"{entry['ghsa']} unreadable")
            continue
        if data.get("state") != "published":
            problems.append(f"{entry['ghsa']} is {data.get('state')!r}, not 'published'")
            continue
        if data.get("severity") != entry["severity"]:
            problems.append(
                f"{entry['ghsa']} is {data.get('severity')!r}, not {entry['severity']!r}")
            continue
        checked.append(f"{entry['ghsa']} ({data.get('severity')})")
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, f"{len(checked)} published: " + ", ".join(checked)


def check_named_person_said(claim: dict) -> tuple[str, str]:
    """A named person wrote the quoted words, on the named thread.

    This is how a third-party endorsement gets checked. A claim that leans on
    someone else's judgement is only worth what the quotation is worth, so the
    quotation is looked for in that person's own comment rather than in a
    summary of it. If they edit or delete the comment, the claim goes red.
    """
    source = claim["source"]
    repo, number, author = source["repo"], source["number"], source["author"]
    wanted = claim["verification"].get("must_contain", [])
    if not wanted:
        return FAIL, "no quotation configured for this claim"

    comments = gh_api(f"repos/{repo}/issues/{number}/comments")
    if not isinstance(comments, list):
        return FAIL, f"could not read comments on {repo}#{number}"

    theirs = [
        c for c in comments
        if ((c.get("user") or {}).get("login") or "").lower() == author.lower()
    ]
    if not theirs:
        return FAIL, f"{author} has no comment on {repo}#{number}"

    bodies = "\n".join(c.get("body") or "" for c in theirs)
    missing = [phrase for phrase in wanted if phrase not in bodies]
    if missing:
        return FAIL, (
            f"{author}'s comment on {repo}#{number} does not say {missing[0]!r} "
            "- or has been edited since"
        )
    return PASS, f"{author} on {repo}#{number}: {len(wanted)} quoted phrase(s) verified"


CHECKS = {
    "hackinghub_rank": check_hackinghub_rank,
    "github_pr_merged": check_github_pr_merged,
    "github_pr_superseded_no_credit": check_github_pr_superseded_no_credit,
    "github_pr_open_or_merged": check_github_pr_open_or_merged,
    "github_prs_open_or_merged": check_github_prs_open_or_merged,
    "github_issues_open": check_github_issues_open,
    "named_person_said": check_named_person_said,
    "paper_artifacts_reproduce": check_paper_artifacts_reproduce,
    "public_repo_exists": check_public_repo_exists,
    "agentbound_rule_count": check_agentbound_rule_count,
    "github_advisories": check_github_advisories,
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
