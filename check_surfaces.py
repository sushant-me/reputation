#!/usr/bin/env python3
"""Check the public surfaces for claims that are stale, wrong, or quietly removed.

`verify_evidence.py` checks the 19 top-level claims against their sources. It did
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
    # The PDFs, which are the artifacts that actually get attached to an application.
    # `read()` has understood PDFs for a while and nothing listed one, so the one surface
    # an employer receives was the one surface never checked - and a correction applied to
    # the HTML and not regenerated into the PDF would have gone out unnoticed.
    "cv/*.pdf",
    "reputation/*.pdf",
    "job-kit/*.pdf",
    "portfolio/src/app/page.tsx",
    "reputation/Sushant_Poudel_Evidence_Sheet.html",
    # A glob for the same reason as job-kit: the ledger and the README both state
    # claim counts, and the ledger was not being scanned at all.
    "reputation/*.md",
    # A glob rather than a list: a new document in job-kit is covered the moment it
    # exists, instead of waiting for someone to remember to add it here.
    "job-kit/*.md",
    "job-kit/*.html",
    # A queued email is a surface: it carried the stale corpus count, and it is the
    # text that would have been sent to a funder.
    "job-kit/outbox.json",
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
    # The posts and the work samples are public claims surfaces too. The benchmark
    # post states precision and recall; the version of the test count it corrects
    # lives in it; the review sample asserts four findings reproduce. None of them
    # was scanned, which is how a surface escapes a checker that lists its files
    # by hand.
    "writeups/*.md",
    "agent-review-sample/*.md",
    "mcp-audit-sample/*.md",
    "mcp-audit-sample/audit/*.md",
    "Edge-Native_Semantic_Firewall_/README.md",
    "Edge-Native_Semantic_Firewall_/docs/*.md",
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
    "18 labelled cases": (
        "the corpus grew to 19 cases; the count appears in eight places and moves "
        "whenever a case is added."
    ),
    "18 agent tool-boundary cases": "the corpus grew to 19 cases.",
    "18 labelled agent tool-boundary cases": "the corpus grew to 19 cases.",
    "18 self-authored cases": "the corpus grew to 19 cases.",
    # The corpus then grew to 23 with the declaration-drift class, so every spelling of the
    # nineteen-case count is now wrong too. Old counts stay forbidden forever: a page that
    # reverts to one must fail, not pass because the rule was retired.
    "19 labelled cases": (
        "the corpus grew to 23 cases with the declaration-drift class; the count appears "
        "in eight places and moves whenever a case is added."
    ),
    "19 agent tool-boundary cases": "the corpus grew to 23 cases.",
    "19 labelled agent tool-boundary cases": "the corpus grew to 23 cases.",
    "19 self-authored cases": "the corpus grew to 23 cases.",
    "declaration scanner) — 13 cases": (
        "the tool-list subset grew to 14 cases with the regression case."
    ),
    "27 tests": (
        "the corpus suite grew to 32 with the adapter tests; the README said 27."
    ),
    "32 tests": (
        "the corpus suite grew to 54 with the drift cases and the adapter tests, which "
        "its README said 32. The first drift adapter read only the detector's `findings` "
        "key, so the four new cases scored recall 0.000 against a detector that passed "
        "them. Forbidden globally for now; scope it to the corpus README if another "
        "project here ever ships a thirty-two-test suite."
    ),
    "Run every available": (
        "the conformance deliverable promised every scanner; the best-known one cannot be "
        "run offline, so it promises every scanner that can be."
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
    ("profile-readme/README.md", "23 agent tool-boundary cases", "the corpus count"),
    ("hire/index.html", "23 labelled agent tool-boundary cases", "the corpus count"),
    ("reputation/OPEN-LOOPS.md", "23 labelled cases", "the corpus count"),
    ("job-kit/PROPOSAL.md", "23 labelled cases", "the corpus count"),
    ("job-kit/PROPOSAL.md", "Grow the 23 self-authored cases", "the corpus count"),
    ("job-kit/LAUNCH-POSTS.md", "23 agent tool-boundary cases", "the corpus count"),
    ("job-kit/outbox.json", "23 agent tool-boundary cases", "the corpus count"),
    ("writeups/2026-09-21-a-benchmark-found-a-bug-in-my-own-detector.md",
     "declaration scanner) — 14 cases", "the tool-list subset count"),
    ("tool-boundary-corpus/README.md", "54 tests", "the suite count"),
    ("tool-boundary-corpus/README.md", "does not analyse locally",
     "the Snyk offline limitation"),
    ("tool-boundary-corpus/README.md", "adapters/mcp_scanner_adapter.py",
     "the reproducible third-party comparison"),
    ("tool-boundary-corpus/README.md", "adapters/compare.py",
     "the per-class comparison tool"),
    ("tool-boundary-corpus/README.md", "**9/9**", "the measured caught count"),
    ("tool-boundary-corpus/README.md", "**0/9**",
     "the third-party caught count on this corpus"),
    ("job-kit/PROPOSAL.md", "measures the name instead of the capability",
     "the measured third-party result"),
    ("job-kit/PROPOSAL.md", "does not analyse locally",
     "the third-party scanner limitation"),
    ("job-kit/PROPOSAL.html", "does not analyse locally",
     "the third-party scanner limitation"),
    ("hire/index.html", "Nothing leaves your machine",
     "the local-analysis property"),
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


# The deployed pages, not the sources. Everything above checks files in the
# repository, and a correction that is committed and not deployed is not a
# correction. The ledger carried a "redeploy the portfolio" item for several rounds
# while the host had in fact rebuilt itself on every push - a number nothing
# recomputed, in the document that exists because of numbers nothing recomputed.
LIVE_SITES = [
    ("https://sushantpoudel2028.com.np/", "the portfolio",
     ["117-byte", "generalised into"],
     ["5-byte", "Patch merged into"]),
    ("https://sushant-me.github.io/hire/", "the hire page",
     ["117-byte input", "generalised into", "from graduation"],
     ["month year"]),
]


def fetch(url: str, attempts: int = 3, pause: float = 4.0) -> str | None:
    """Page text, retried: a CDN can serve the previous build for a few seconds."""
    import time
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": "surface-checker/1.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < attempts - 1:
                time.sleep(pause)
    return None


def check_live_sites(truth: dict[str, int]) -> tuple[list[str], int]:
    """The deployed pages, and the counts among them.

    A surface in this repository was already correct while the page a reader clicked still
    said otherwise, so the required/forbidden phrases are asserted against the fetched
    bytes. The counts are asserted the same way, and for the same reason: `LIVE_SITES` was
    the one place a number could go stale with nothing looking at it. Running `COUNT_RULES`
    over the fetched text reuses the derivation instead of adding a second copy of the
    number to keep in step.
    """
    problems: list[str] = []
    checked = 0
    for url, label, required, forbidden in LIVE_SITES:
        text = fetch(url)
        if text is None:
            problems.append(f"{label} ({url}) could not be fetched - is it deployed?")
            continue
        for phrase in required:
            checked += 1
            if phrase not in text:
                problems.append(
                    f"{label} ({url}) does not contain {phrase!r}: the source has it, "
                    "so the deployment is behind the repository")
        for phrase in forbidden:
            checked += 1
            if phrase in text:
                problems.append(
                    f"{label} ({url}) still contains {phrase!r}, which was corrected in "
                    "the source: the deployment is behind the repository")
        for pattern, key, what in COUNT_RULES:
            if key not in truth:
                continue
            for found in pattern.findall(text):
                checked += 1
                if int(found) != truth[key]:
                    problems.append(
                        f"{label} ({url}) says {found} for the {what}, but the corpus has "
                        f"{truth[key]}: the deployment is behind the repository")
    return problems, checked


def normalise(text: str) -> str:
    """Collapse all whitespace, so a phrase matches across a line wrap.

    Prose wraps. This checker matched single-space literals against raw file text, so a
    phrase the document happened to break across two lines did not match - which made a
    **forbidden** string evadable by reformatting, and made two required strings fail on
    documents that contained them. Matching happens on normalised text now.
    """
    return " ".join(text.split())


def corpus_case_count() -> int | None:
    """The corpus's own case count, counted from its files rather than remembered.

    The count appeared as a required string in eight places, which catches a surface that
    failed to update but *not* a surface that disagrees with the corpus — and the number is
    sitting on disk a directory away, in the fixtures themselves. So it is counted here.

    It happens to agree with the eight required strings today; the point is that this rule
    would still be right if the corpus grew and nobody remembered this file.
    """
    directory = WORKSPACE / "tool-boundary-corpus" / "cases"
    if not directory.is_dir():
        return None
    return len(list(directory.glob("*.json")))


def evidence_counts() -> dict[str, int]:
    """What `evidence.json` actually contains, computed rather than remembered.

    The count of claims, and how many of them are checkable live, is derived here
    from the file and from `verify_evidence.CHECKS`. It has to be derived: the
    number was written into six different sentences across the surfaces, and after
    the fifth claim was added they disagreed with each other as well as with the
    file. This is the same class of error as the other four, and the only fix that
    lasts is for the checker to own the number.
    """
    sys.path.insert(0, str(HERE))
    import verify_evidence  # noqa: PLC0415  (deliberate: same directory, no package)

    claims = json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))["claims"]
    live = sum(1 for c in claims if c["verification"]["method"] in verify_evidence.CHECKS)
    counts = {"claims": len(claims), "checked_live": live, "on_request": len(claims) - live}
    corpus = corpus_case_count()
    if corpus is not None:
        counts["corpus_cases"] = corpus
    return counts


# Every number in prose that has to equal something in evidence.json.
#
# The corpus entries are spelled out per phrasing rather than matched with a loose
# `\d+ ... cases`, because this repository also writes subset counts in prose — the four
# declaration-drift cases, the five negatives, the fourteen tool-list cases — and a loose
# pattern would compare those against the total and report a failure that is not one.
COUNT_RULES = [
    (re.compile(r"\b(\d+)\s+claims\b"), "claims", "claim count"),
    (re.compile(r"\b(\d+)\s+(?:checked|verified)\s+live\b"), "checked_live",
     "live-checked count"),
    (re.compile(r"\b(\d+)\s+documented on request\b"), "on_request",
     "on-request count"),
    (re.compile(r"\b(\d+)\s+labelled cases\b"), "corpus_cases", "corpus case count"),
    (re.compile(r"\b(\d+)\s+labelled agent tool-boundary cases\b"), "corpus_cases",
     "corpus case count"),
    (re.compile(r"\b(\d+)\s+agent tool-boundary cases\b"), "corpus_cases",
     "corpus case count"),
    (re.compile(r"\b(\d+)\s+self-authored cases\b"), "corpus_cases", "corpus case count"),
]


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
    # 0b. No attachable PDF may be invisible.
    #
    #     The PDFs are the artifacts that actually reach an employer, and they were the one
    #     surface left out of SURFACES - which is how PROPOSAL.pdf sat for several rounds still
    #     saying "19 labelled cases" after the number had been corrected in the .md and the
    #     .html. Worse, the first version of this guard hard-coded three directory names that
    #     already had `*.pdf` globs, so it could never fire: a guard that cannot fail is the
    #     same green tick this file exists to prevent. The directories are derived from the
    #     patterns now, so any directory we claim to scan has to scan its PDFs too.
    listed = {p.resolve() for p in files}
    scanned_dirs = {pattern.split("/", 1)[0] for pattern in SURFACES if "/" in pattern}
    for directory in sorted(scanned_dirs):
        target = WORKSPACE / directory
        if not target.is_dir():
            continue
        for pdf in sorted(target.glob("*.pdf")):
            if pdf.resolve() not in listed:
                problems.append(
                    f"{directory}/{pdf.name} is a PDF in a scanned directory that no SURFACES "
                    "pattern matches, so nothing checks what it says")

    if args.require_all and missing_globs:
        problems.append(
            "--require-all: nothing matched " + ", ".join(missing_globs))

    # 1. Forbidden strings: the error history, enforced.
    for path in files:
        text = read(path)
        if not text:
            continue
        flat = normalise(text)
        for phrase, why in FORBIDDEN.items():
            if normalise(phrase) in flat:
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
        if normalise(phrase) not in normalise(read(path)):
            problems.append(
                f"{target}: {what} - expected {phrase!r}, which is missing "
                f"(a fix by deletion is not a fix)")

    # 3. Counts in prose must equal the counts in evidence.json (and, for the corpus, the
    #    count taken from the corpus's own case files).
    truth = evidence_counts()
    counts_checked = 0
    counts_skipped: list[str] = []
    for path in files:
        text = read(path)
        if not text:
            continue
        for pattern, key, what in COUNT_RULES:
            for found in pattern.findall(text):
                if key not in truth:
                    # The corpus is not in this checkout, so its count cannot be re-derived.
                    # Recorded rather than passed silently: a count nobody could check must
                    # not look like a count that was checked.
                    if what not in counts_skipped:
                        counts_skipped.append(what)
                    continue
                counts_checked += 1
                if int(found) != truth[key]:
                    problems.append(
                        f"{path.relative_to(WORKSPACE)}: says {found} for the {what}, "
                        f"but the corpus has {truth[key]}")

    # 4. The deployed pages, which nothing else looks at - including any count on them.
    live_problems, live_checked = check_live_sites(truth)
    problems.extend(live_problems)

    # 5. Live: a release label must be the release it names - on the surfaces where
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
        "live_pages_checked": live_checked,
        "counts_checked": counts_checked,
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
        print(f"live pages checked:      {live_checked} assertions on {len(LIVE_SITES)} pages")
        print(f"prose counts checked:    {counts_checked} "
              f"(truth: {truth['claims']} claims, {truth['checked_live']} live, "
              f"{truth['on_request']} on request"
              + (f", {truth['corpus_cases']} corpus cases"
                 if "corpus_cases" in truth else "") + ")")
        if counts_skipped:
            print(f"counts NOT re-derived:   {', '.join(counts_skipped)} "
                  f"(source not in this checkout)")
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
