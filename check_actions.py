#!/usr/bin/env python3
"""The profile says four tools are composite GitHub Actions. This checks that they are.

Why this exists
---------------
The profile makes one claim that is not a number: *"Four of these — `agentbound`,
`mcpaudit`, `mcp-nameguard` and `tool-boundary-corpus` — are also composite GitHub
Actions, so the same check runs where the decision is made."* A reader acts on that
sentence by adding `uses: sushant-me/mcpaudit@v1` to a workflow. If the tag moved and
the file did not come with it, or a repository was renamed, the sentence sends them to
a red step for a reason that has nothing to do with their code.

The rest of this repository exists because claims nobody re-reads drift. This is the
same rule applied to the one claim whose failure mode is somebody else's CI.

What it asserts
---------------
1. Every tool the profile names as an Action serves `action.yml` at the `v1` tag, and
   that file is a composite action (`runs:` / `using: composite`). A tag that exists but
   points at a commit from before the action was added is the interesting failure: the
   name resolves, the file does not.
2. Every tool that *does* serve an action at `v1` is named in that sentence. Otherwise
   the profile understates the work, which is the smaller version of the same bug.
3. No claim and no actions is not a failure — a profile without the sentence claims
   nothing. But a claim of zero is refused: the sentence exists to name tools.

    python3 check_actions.py
    python3 check_actions.py --self-test
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
PROFILE = HERE.parent / "profile-readme" / "README.md"

# Every repository the profile's "Start here" table names. The sentence is only allowed
# to be wrong about these; anything else in backticks near it is prose.
TOOLS = [
    "agentbound",
    "mcpaudit",
    "policygate",
    "mcp-nameguard",
    "trajectorycheck",
    "tool-boundary-corpus",
]

CLAIM_PHRASE = "composite GitHub Actions"
NAME_RE = re.compile(r"`([a-z0-9][a-z0-9._-]*)`")
RAW = "https://raw.githubusercontent.com/sushant-me/{repo}/v1/action.yml"


def fetch(repo: str) -> str | None:
    """The action.yml a reader would get at `@v1`, or None when there is not one."""
    try:
        with urllib.request.urlopen(RAW.format(repo=repo), timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 400):
            return None
        raise
    except urllib.error.URLError:
        # A network failure is not evidence that the file is absent, and reporting it as
        # absent would be this repository's favourite defect. Fail loudly instead.
        raise


def claimed(readme: str) -> set[str] | None:
    """The tools the profile names in its Action sentence, or None when it makes no claim.

    The names sit immediately before the phrase ("`a`, `b` and `c` — are also
    composite GitHub Actions"), so the window is the text between the end of the previous
    paragraph or heading and the phrase itself.
    """
    index = readme.find(CLAIM_PHRASE)
    if index == -1:
        return None
    window = readme[:index]
    stop = max(window.rfind("\n\n"), window.rfind("\n#"))
    window = window[stop if stop != -1 else 0:]
    return {name for name in NAME_RE.findall(window) if name in TOOLS}


def is_composite(text: str) -> bool:
    """A composite action declares `runs:` with `using: composite`; nothing else is one."""
    return re.search(r"^runs:\s*$", text, re.MULTILINE) is not None and re.search(
        r"^\s+using:\s*composite\s*$", text, re.MULTILINE
    ) is not None


def problems(claim: set[str] | None, actions: dict[str, str | None]) -> list[str]:
    """Everything wrong with the sentence, given the actions that actually exist."""
    out: list[str] = []
    if claim is None:
        if any(actions.values()):
            out.append(
                "no Action sentence in the profile, but "
                + ", ".join(sorted(r for r, t in actions.items() if t))
                + " serve action.yml at v1 — the profile understates the work"
            )
        return out
    if not claim:
        out.append("the Action sentence names no tool from the Start here table")
    present = {repo for repo, text in actions.items() if text}
    for repo in sorted(claim - present):
        out.append(f"profile names {repo} as an Action, but {RAW.format(repo=repo)} is not there")
    for repo in sorted(present - claim):
        out.append(f"{repo} serves an action at v1, but the profile does not name it")
    for repo in sorted(claim & present):
        text = actions[repo] or ""
        if not is_composite(text):
            out.append(f"{repo}'s action.yml at v1 is not a composite action")
    return out


def self_test() -> int:
    """The guard has to be shown firing, because passing looks exactly like a clean estate."""
    print("self-test: the Action guard must reject a stale claim\n")
    fails = 0

    def case(name: str, claim, actions, want_problems: bool) -> None:
        nonlocal fails
        found = problems(claim, actions)
        ok = bool(found) == want_problems
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            print(f"        problems={found}")
        fails += 0 if ok else 1

    good = {repo: "on: push\nruns:\n  using: composite\n  steps: []\n" for repo in TOOLS}
    four_claim = {"agentbound", "mcpaudit", "mcp-nameguard", "tool-boundary-corpus"}
    four = {repo: (good[repo] if repo in four_claim else None) for repo in TOOLS}
    all_claim = set(TOOLS)

    case("a true sentence passes", four_claim, four, False)
    case("a named tool with no action is rejected", four_claim | {"policygate"}, four, True)
    case("an unnamed tool with an action is rejected", {"agentbound"}, four, True)
    case("a tag that exists without the action file is rejected", all_claim, four, True)
    case(
        "an action.yml that is not composite is rejected",
        {"agentbound"},
        {"agentbound": "runs:\n  using: node20\n  main: index.js\n"},
        True,
    )
    case("no sentence and no actions passes", None, {repo: None for repo in TOOLS}, False)
    case("no sentence but actions exist is rejected", None, four, True)

    print()
    if fails:
        print(f"self-test FAILED ({fails})")
        return 1
    print("self-test passed: fires on a stale claim, silent on a true one")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    if not PROFILE.is_file():
        print(f"::error::no profile README at {PROFILE}; a run that read nothing verified nothing")
        return 1

    claim = claimed(PROFILE.read_text(encoding="utf-8"))
    actions = {repo: fetch(repo) for repo in TOOLS}
    found = problems(claim, actions)

    named = "none" if claim is None else (", ".join(sorted(claim)) or "empty")
    print(f"profile claims : {named}")
    for repo in TOOLS:
        state = "composite" if actions[repo] and is_composite(actions[repo] or "") else (
            "not composite" if actions[repo] else "none"
        )
        print(f"  {repo:24} action.yml at v1: {state}")

    if found:
        print()
        for problem in found:
            print(f"::error::{problem}")
        return 1
    print("\nthe Action claim matches what the tags serve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
