#!/usr/bin/env python3
"""Check the public surfaces for claims that are stale, wrong, or quietly removed.

`verify_evidence.py` checks the 18 top-level claims against their sources. It did
not notice three separate errors, because all three were *details inside* a claim
that had been true when it was written:

  * "Merged into google/go-github" — true, but the fix was reverted the next day,
    so the page described code that is not in master.
  * "weakening either invariant fails six tests" — six was both invariants at
    once; each fails three. The sentence had collapsed two cases into one number.
  * "a 16 GiB allocation from a 5-byte header" — the issue says the input is 117
    bytes. No issue mentions five bytes anywhere.

Each was found by hand, one at a time, on surfaces that had already been published.
This file is the fix for that: every error becomes a rule, so the specific mistake
cannot return, and the corrected wording is asserted so a surface cannot quietly
lose it either.

Two kinds of rule:

  * **forbidden** — a string that is known to be wrong or stale. If it reappears
    anywhere, the check fails with the reason it was removed.
  * **required** — a corrected string that must appear on the surfaces that make
    the claim. Without this, "fixing" a page by deleting the sentence would pass.

Plus one live check: every `releases/tag/vX.Y.Z` link must equal that repository's
actual latest release, because a release moves and a label does not.

    python3 check_surfaces.py
    python3 check_surfaces.py --json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def resolve_workspace() -> pathlib.Path:
    """The directory holding the sibling surfaces.

    Normally the parent of this repository, because the workstation has
    `reputation/`, `profile-readme/`, `hire/`, `cv/` and `job-kit/` side by side, and
    CI checks every repository out into a subdirectory to reproduce that shape.

    The first version of the workflow checked this repository out at the root
    instead, so the script looked one level too high, found a single surface, and
    failed. Failing was correct; looking in the wrong place was not. So the parent
    is only used when it actually looks like a workspace.
    """
    for candidate in (HERE.parent, HERE):
        if any((candidate / marker).exists()
               for marker in ("reputation", "profile-readme", "hire", "job-kit")):
            return candidate
    return HERE.parent


WORKSPACE = resolve_workspace()

# Every surface a reader can reach. Globs, so a new CV variant is covered by default.
SURFACES = [
    "profile-readme/README.md",
    "hire/index.html",
    "cv/*.html",
    "cv/*.md",
    "portfolio/src/app/page.tsx",
    "reputation/Sushant_Poudel_Evidence_Sheet.html",
    "reputation/README.md",
    "job-kit/LINKEDIN.md",
    "job-kit/APPLICATIONS-READY.md",
    "job-kit/INTERVIEW-PREP.md",
    "job-kit/INTERVIEW-STRESS.md",
    "job-kit/PROPOSAL.md",
    "job-kit/PROPOSAL.html",
    # The project READMEs are claims surfaces too, and they carry numbers of their
    # own: rule counts, test counts, coverage figures, measured percentages. They
    # live in sibling repositories on the workstation and are checked out beside
    # this one in CI.
    "agentbound/README.md",
    "mcpaudit/README.md",
    "policygate/README.md",
    "mcp-nameguard/README.md",
    "trajectorycheck/README.md",
    "tool-boundary-corpus/README.md",
]

# Where a `releases/tag/vX.Y.Z` link means "this is the current release". Project
# READMEs are excluded on purpose: the corpus README links v0.1.10 as the release
# that *fixed* a false positive, which is history rather than a claim about the
# latest, and flagging it would be a false positive of the checker's own.
VERSION_CHECKED = [
    "profile-readme/README.md",
    "hire/index.html",
    "portfolio/src/app/page.tsx",
    "reputation/README.md",
]

# A string that was published and was wrong. Each entry says why it is wrong, so
# the failure message is an explanation rather than a rule number.
FORBIDDEN = {
    "5-byte header": (
        "the issue (#677) says the malformed input is 117 bytes; nothing in "
        "s2geometry mentions five bytes. Use '117-byte input'."
    ),
    "5-byte": (
        "same error in a shorter form: the input is 117 bytes (#677)."
    ),
    "weakening either the model-allow invariant or the unparseable-call path fails six": (
        "six is both invariants at once; each fails THREE tests in isolation."
    ),
    "Weakening either\n  invariant fails six tests": (
        "six is both invariants at once; each fails THREE tests in isolation."
    ),
    "Patch merged into google/go-github": (
        "describes #4556's per-method check, which is not in master. The fix was "
        "merged and then generalised by the maintainer in #4564."
    ),
    "seven memory-safety issues": (
        "seven counted two closed pull requests as issues. It is 5 open issues "
        "plus 2 open PRs, with 2 earlier fixes closed."
    ),
    "Seven memory-safety issues": (
        "seven counted two closed pull requests as issues. It is 5 open issues "
        "plus 2 open PRs, with 2 earlier fixes closed."
    ),
    "full CI matrix green": (
        "#4556 was merged and then reverted; 'full CI matrix green' described the "
        "approval, not the outcome."
    ),
    "#675 is under review": (
        "#675 is closed, and was closed with written evidence."
    ),
    "90.8% on decisive rules": (
        "the paper's own label is 'Rule A decision accuracy' over 'Rule A hard "
        "denials'. Use its words, so a reader can find the row."
    ),
    "[month year]": (
        "an unfilled placeholder on a public page; it now reads 'from graduation'."
    ),
}

# The corrected wording, asserted on the surfaces that make the claim. A page that
# simply deletes the sentence must not pass.
#
# Scoped per file on purpose. The first version demanded the same phrase from every
# CV, and three "failures" turned out to be the rule being wrong rather than the
# page: two CVs name the 16 GiB allocation without ever stating the input size, and
# `INTERVIEW-STRESS.md` writes "fails 3", in digits, where the profile writes
# "three". A checker that reports errors which are not errors gets switched off, so
# each rule names the file and the exact string that file should carry.
REQUIRED: list[tuple[str, str, str]] = [
    # (file, phrase that must appear, what it protects)
    ("profile-readme/README.md", "117-byte input", "the s2geometry input size"),
    ("hire/index.html", "117-byte input", "the s2geometry input size"),
    ("cv/Sushant_Poudel_CV_AISecurity.html", "117-byte input", "the s2geometry input size"),
    ("reputation/Sushant_Poudel_Evidence_Sheet.html", "117-byte input",
     "the s2geometry input size"),
    ("profile-readme/README.md", "4564", "the generalisation, not a bare merge"),
    ("hire/index.html", "4564", "the generalisation, not a bare merge"),
    ("profile-readme/README.md", "fails three", "the mutation numbers"),
    ("job-kit/INTERVIEW-STRESS.md", "fails 3", "the mutation numbers"),
    ("profile-readme/README.md", "117-byte", "the corrected size survives a reword"),
    ("policygate/README.md", "Rule A hard-denial",
     "the paper's own label, not a paraphrase of it"),
]


def surface_files() -> tuple[list[pathlib.Path], list[str]]:
    """The surface files that exist here, and which declarations matched nothing.

    Returned separately because a glob can match several files (`cv/*.html` is
    three) and because "no file matched this declaration" is the fact worth
    reporting: it is how a checker silently stops covering something.
    """
    found: list[pathlib.Path] = []
    matched: set[str] = set()
    for pattern in SURFACES:
        hits = [p for p in sorted(WORKSPACE.glob(pattern)) if p.is_file()]
        if hits:
            matched.add(pattern)
            found += hits
    return found, [p for p in SURFACES if p not in matched]


def read(path: pathlib.Path) -> str:
    if path.suffix == ".pdf":
        try:
            out = subprocess.run(["pdftotext", str(path), "-"],
                                 capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout if out.returncode == 0 else ""
    return path.read_text(encoding="utf-8", errors="replace")


def latest_release(repo: str) -> str | None:
    try:
        out = subprocess.run(
            ["gh", "release", "list", "--repo", f"sushant-me/{repo}", "--limit", "1",
             "--json", "tagName"],
            capture_output=True, text=True, timeout=45, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        entries = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    return entries[0]["tagName"] if entries else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-all", action="store_true",
                        help="a declared surface that is not present is a failure; "
                             "the workstation has all of them, CI does not")
    parser.add_argument("--min-surfaces", type=int, default=1,
                        help="fail below this many surfaces, so a check that reads "
                             "nothing cannot pass trivially")
    args = parser.parse_args(argv)

    files, missing_globs = surface_files()
    problems: list[str] = []

    # 0. Coverage first. This checker is about numbers nothing re-derived, and a
    #    run that finds no files is the same bug wearing a green tick.
    if len(files) < args.min_surfaces:
        problems.append(
            f"only {len(files)} surface(s) present, need at least "
            f"{args.min_surfaces}: a check with nothing to read is not a pass")
    if args.require_all and missing_globs:
        problems.append(
            "--require-all: nothing matched " + ", ".join(missing_globs))

    # 1. Forbidden strings: the error history, enforced.
    for path in files:
        text = read(path)
        if not text:
            continue
        for phrase, why in FORBIDDEN.items():
            if phrase in text:
                problems.append(
                    f"{path.relative_to(WORKSPACE)}: contains {phrase!r} - {why}")

    # 2. Required strings: the correction cannot be deleted instead of made.
    #    Only asked of surfaces that are present: in CI the CVs and job-kit are
    #    simply not here, and reporting them as failures would train the reader to
    #    ignore the output.
    for target, phrase, what in REQUIRED:
        path = WORKSPACE / target
        if not path.exists():
            if args.require_all:
                problems.append(f"{what}: {target} is not present in this checkout")
            continue
        if phrase not in read(path):
            problems.append(
                f"{target}: {what} - expected {phrase!r}, which is missing "
                f"(a fix by deletion is not a fix)")

    # 3. Live: a release label must be the release it names - on the surfaces where
    #    linking a version means "this is the current one".
    version_links = 0
    for path in files:
        if str(path.relative_to(WORKSPACE)) not in VERSION_CHECKED:
            continue
        text = read(path)
        for repo, label in re.findall(
                r"github\.com/sushant-me/([A-Za-z0-9_.-]+)/releases/tag/v([0-9][0-9.]*)",
                text):
            version_links += 1
            actual = latest_release(repo)
            if actual is None:
                problems.append(f"{path.name}: cannot read latest release of {repo}")
            elif actual != f"v{label}":
                problems.append(
                    f"{path.name}: links {repo} v{label}, but the latest release is {actual}")

    payload = {
        "surfaces_present": len(files),
        "declarations_matched": len(SURFACES) - len(missing_globs),
        "declarations_unmatched": missing_globs,
        "forbidden_rules": len(FORBIDDEN),
        "required_rules": len(REQUIRED),
        "version_links_checked": version_links,
        "problems": problems,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"surface declarations:    {len(SURFACES) - len(missing_globs)}"
              f"/{len(SURFACES)} matched  ({len(files)} files)")
        if missing_globs:
            print(f"  not in this checkout:  {', '.join(missing_globs)}")
        print(f"forbidden strings:       {len(FORBIDDEN)} rules")
        print(f"required strings:        {len(REQUIRED)} assertions")
        print(f"release links checked:   {version_links}")
        print()
        if problems:
            for problem in problems:
                print(f"FAIL  {problem}")
            print(f"\n{len(problems)} problem(s)")
        else:
            print("PASS  every known error is absent, and every correction is present")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
