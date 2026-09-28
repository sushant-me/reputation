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
    # The per-paper disclosure notes. These are the site's own corrections -- the place
    # it explains that an abstract carries the wrong denominator, that a label means
    # something narrower than it looks, or that a paper is accepted rather than
    # published. That makes them a claims surface twice over: they assert what the
    # status *is*, and they are the only place a reader can learn the difference. The
    # PREBAS "in IEEE Xplore" overstatement on the homepage survived a fact-check
    # because the venue claim was true while the paper claim was not, so the page that
    # states the distinction is now scanned rather than trusted.
    "portfolio/src/app/publications/*/page.tsx",
    # The publications *content*, not only the page that renders it. This file was the one
    # surface no rule reached, and it is where a live, indexed claim went unchecked: it
    # published a manuscript naming a benchmark corpus that was never built, beside an earlier
    # draft of a paper whose headline figures the authors' own repository had already measured
    # false and withdrawn. `page.tsx` was scanned and did not contain them, because the strings
    # live here. A surface list built from the pages a reader sees will always miss the data
    # those pages are built from.
    "portfolio/content/publications.ts",
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
    # beyond-attention makes measured claims too, and it was not scanned -- the
    # same omission the comment above describes. Its README carries the
    # learned-gate numbers, including one row that does NOT reproduce across
    # Python versions, and the correction that the gate's discrete decision was
    # already exactly right. Those are exactly the claims worth re-reading.
    "beyond-attention/README.md",
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
    # A whole manuscript described a corpus that does not exist. The name appeared in exactly
    # one place in the workspace -- the abstract published on the portfolio -- with no code, no
    # corpus, no results file and no repository anywhere behind it, and it was served with
    # citation markup next to a paper that genuinely ships its artifacts. Forbidden outright:
    # there is no legitimate use of this name, anywhere, in any document.
    "MAPI-6K": (
        "no such dataset was ever built. The manuscript naming it has been withdrawn; "
        "the name must not reappear on any surface."
    ),
    "MAPI-6k": "same nonexistent dataset, different capitalisation.",
    # The site claimed its own checkability more broadly than the ledger supported. "Every factual
    # claim about my own work is re-checked weekly" stood on the press page, the writing template,
    # the publication template and the homepage, while the ledger held 23 claims covering 2 of the
    # 9 papers -- and 7 of 8 publication pages had no entry at all. A claim of verification that
    # nothing verifies is the same defect this repository exists to catch, pointed at itself.
    "every claim on this page is re-checked": (
        "the ledger does not cover every claim on that page. State the coverage instead."
    ),
    "Every factual claim I make": (
        "same overstatement on the writing template; state the ledger's coverage."
    ),
    "Every factual claim Sushant makes about his own work is re-checked": (
        "same overstatement on the publication template; state the ledger's coverage."
    ),
    "novel dataset of 6,000 inter-agent": (
        "the corpus behind this claim does not exist. Withdrawn; do not restate the size."
    ),
    # The containment figure, in the form published as a result. The paper's own repository
    # measured 66.3% decision accuracy and retracted the hundred-percent claim, so publishing
    # it again is publishing a number its author already knows is wrong.
    "100% containment": (
        "retracted. The repository measures 66.3% decision accuracy and the best arm still "
        "approved 6 of 208 hard-denial actions."
    ),
    # Deliberately NOT forbidding the hundred-percent *adherence* phrase: the firewall
    # repository's README quotes it in order to retract it, which is what a correction should
    # look like. The rules above are limited to strings with no legitimate use -- a dataset that
    # does not exist, and a figure the author has already withdrawn. A rule that also banned the
    # retraction would force the README to stop saying what it got wrong.
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
    # The homepage stat read "Papers accepted, one in IEEE Xplore". The venue's research
    # track is published in IEEE Xplore, but that is a fact about the track, not about
    # this paper -- which is accepted, is in neither IEEE Xplore nor Crossref, and whose
    # inclusion in the proceedings depended on an author registration that was never
    # completed. The sentence was true of the venue and false of the paper, which is how
    # it survived a fact-check that was reading for the venue claim. Phrase pinned
    # narrowly ("one in IEEE Xplore") so the accurate standfirst -- "whose research track
    # is published in IEEE Xplore" -- does not trip it.
    "one in IEEE Xplore": (
        "the paper is accepted, not published, and has no Xplore or Crossref record. "
        "Say 'accepted', or name the conference, not the database."
    ),
    "one of which is in IEEE Xplore": (
        "same conflation of the track's venue with this paper's status."
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
    ("portfolio/src/app/page.tsx", "one at an IEEE conference",
     "the PREBAS status stays 'accepted at an IEEE conference', not 'in IEEE Xplore'"),
    ("portfolio/src/app/publications/[slug]/page.tsx", "neither IEEE Xplore nor Crossref",
     "the paper page keeps stating that it is not published yet, with the date checked"),
    ("beyond-attention/README.md", "0.420",
     "the unflattering raw-gate number survives an edit"),
    # This pinned "does not reproduce across Python versions" until
    # beyond-attention corrected the section it names: the row moves on seed
    # *and* on platform, 3.11 is not an exception, and believing it was one is
    # what made that repository's own check fail at random. Pinning the
    # superseded wording made this rule fire on the more accurate section -
    # a guard reporting an error that is not an error, which is the failure the
    # comment above warns about, pointed the other way. What it protects is
    # unchanged: the limit stays stated. So it follows the wording that is true.
    ("beyond-attention/README.md", "One published row does not reproduce",
     "the reproducibility limit is not quietly dropped"),
    ("beyond-attention/README.md", "ten orders of magnitude",
     "the measured reason annealing is the fragile row"),
    ("beyond-attention/README.md", "0.160",
     "the straight-through negative result"),
    ("beyond-attention/README.md", "no-op on the discrete answer",
     "the correction, not the original overstatement"),
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
    # This pinned the literal "54 tests". A pinned number is the right shape for a
    # measurement that must not drift, and the wrong shape for one that is
    # *supposed* to change: tool-boundary-corpus has a commit that corrects this
    # README to 58 after a test file was added, and the rule would have fired on
    # the correction the moment it was pushed - a guard blocking an update, which
    # is the "errors which are not errors" failure this file warns about. Nothing
    # here can count another repository's tests, so freezing the number only ever
    # asserted "the README still says what it said". The sentence that carries the
    # claim is pinned instead: it survives the number changing, and still fails if
    # the claim is deleted.
    ("tool-boundary-corpus/README.md",
     "tests (the harness's own behaviour is tested with fake detectors)",
     "the suite count is stated rather than deleted"),
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
     "the local-analysis property"),    # The correction to "every claim is re-checked" must survive as a statement, not as a
    # deletion: the three FORBIDDEN rules above stop the overstatement returning, and this
    # holds the replacement in place. Removing the sentence instead of fixing it is the other
    # way this defect comes back.
    ("portfolio/src/app/press/page.tsx", "holds 23 claims",
     "the ledger's actual coverage is stated rather than implied"),

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
    # The advisory id is asserted on both pages because these are the surfaces a reader
    # actually lands on, and the security work existed only on GitHub until it was added.
    # A deploy that drops it is a page that is behind the repository - the failure this
    # check exists to catch - so it is asserted rather than trusted to stay.
    ("https://sushantpoudel2028.com.np/", "the portfolio",
     ["117-byte", "generalised into", "GHSA-qwvv-fcmm-r3j2", "Bhaktapur"],
     ["5-byte", "Patch merged into"]),
    ("https://sushant-me.github.io/hire/", "the hire page",
     ["117-byte input", "generalised into", "from graduation", "GHSA-qwvv-fcmm-r3j2", "Bhaktapur"],
     ["month year"]),
    # The author's own write-up of the evaluation, and the page an editor or a reader lands on
    # first. These five figures are the public claim itself - each was checked against the
    # study's committed metrics.json before being asserted here - so a rewrite or a redeploy
    # that changes one of them is exactly the drift this file exists to catch, on the surface
    # where it matters most. The raw table cells (103 / 277 / 141) are deliberately NOT
    # asserted: they are layout, and a reformat would fail the check with nothing actually wrong.
    ("https://sushantpoudel2028.com.np/writing/structured-output-made-it-less-safe",
     "the evaluation write-up",
     ["46.2%", "17.2%", "23.5%", "66.3%", "6 of 208"],
     []),
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
                if as_int(found) != truth[key]:
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


def committed_condition_count() -> int | None:
    """Experimental conditions in the study, counted from metrics.json rather than remembered.

    The study's own checker printed "(5 conditions)" because it counted every top-level key in
    results/metrics.json, and that includes `_replication` - a block of bookkeeping about the
    run, not a fifth way of asking the model. The design has four: naive, zeroshot, cot and
    cot_av, plus a 200-scenario replication of three of them. The same "5 conditions" then
    appeared in evidence.json, which is where this repository's prose counts come from.

    Underscore-prefixed keys are excluded, so the number follows the study if a condition is
    ever added or removed. Returns None when the study is not in this checkout.
    """
    metrics = WORKSPACE / "Edge-Native_Semantic_Firewall_" / "results" / "metrics.json"
    if not metrics.is_file():
        return None
    try:
        blocks = json.loads(metrics.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    conditions = [key for key in blocks if not key.startswith("_")]
    return len(conditions) or None


def committed_generation_count() -> int | None:
    """Raw model generations actually committed in the study repository, counted not remembered.

    Two deployed pages stated "all 1,800 raw model generations". 1,800 is the paper's
    three-condition comparison; the committed results also hold the cot_av arm (600) and a
    200-per-condition replication (600), so the repository carries 3,000. The pages
    undercounted what a reader can actually check, and nothing was watching the number
    because it lived on a deployed page rather than in evidence.json.

    Counting the lines of results/*.jsonl makes the number follow the repository instead of
    the reverse. Returns None when the study is not in this checkout.
    """
    directory = WORKSPACE / "Edge-Native_Semantic_Firewall_" / "results"
    if not directory.is_dir():
        return None
    total = 0
    for path in sorted(directory.glob("*.jsonl")):
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                total += sum(1 for line in handle if line.strip())
        except OSError:
            return None
    return total or None


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


# Test counts stated in `evidence.json`, derived from the suites themselves.
#
# `check_surfaces` compares counts written in PROSE against `evidence.json`, which makes that
# file the source of truth -- and it was the one surface no rule derived. Three of its counts
# had gone stale (policygate said 58 against 60 collected, mcpaudit said 71 against 89, the
# corpus said "23 tests" where 23 is the number of CASES and the suite collects 58) while every
# project README already stated the correct figure. A number nothing re-derives is the exact
# failure this repository exists to catch, so it is re-derived here from what pytest reports.
#
# `def test_` counts are deliberately NOT used: they overcount (70 and 90 on these same two
# repositories) and they are the static count the README already documents as the trap.
# Every claim id that states a test count must appear here, or the count is recorded
# and never checked. Three were missing until this was noticed: tool-agentbound,
# tool-mcp-nameguard and tool-trajectorycheck all have a `.venv` and a runnable
# suite, so `collected_test_count` would have worked for them -- the map was simply
# incomplete, and the gap was not theoretical. `tool-agentbound` said 129 while the
# suite collected 140, and every run of this checker passed.
TEST_COUNT_SUITES = {
    "tool-policygate": "policygate",
    "tool-mcpaudit": "mcpaudit",
    "tool-boundary-corpus": "tool-boundary-corpus",
    "tool-agentbound": "agentbound",
    "tool-mcp-nameguard": "mcp-nameguard",
    "tool-trajectorycheck": "trajectorycheck",
}


def collected_test_count(repo: str) -> int | None:
    """What pytest actually collects in a sibling repository, or None if it is not here."""
    root = WORKSPACE / repo
    python = root / ".venv" / "bin" / "python"
    if not root.is_dir() or not python.exists():
        return None
    try:
        out = subprocess.run(
            [str(python), "-m", "pytest", "--collect-only", "-q"],
            cwd=root, capture_output=True, text=True, timeout=300, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"(\d+)\s+tests? collected", out)
    return int(found.group(1)) if found else None


def test_count_disagreements() -> tuple[list[str], int, list[str]]:
    """Every test count stated in evidence.json, compared with the suite it describes.

    Returns (problems, how many were checked, how many could not be). A suite that is not in
    this checkout is reported rather than passed silently: a count nobody could check must not
    look like a count that was checked.
    """
    claims = json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))["claims"]
    problems: list[str] = []
    checked = 0
    skipped: list[str] = []
    for claim in claims:
        repo = TEST_COUNT_SUITES.get(claim.get("id", ""))
        if repo is None:
            continue
        stated = None
        for metric in claim.get("metrics") or []:
            found = re.match(r"\s*(\d+)\s+tests?\b", metric)
            if found:
                stated = int(found.group(1))
                break
        if stated is None:
            continue
        actual = collected_test_count(repo)
        if actual is None:
            skipped.append(f"evidence.json {claim['id']} (suite not in this checkout)")
            continue
        checked += 1
        if stated != actual:
            problems.append(
                f"evidence.json: {claim['id']} states {stated} tests, but pytest "
                f"collects {actual} in {repo}")
    return problems, checked, skipped


def html_text(path: pathlib.Path) -> str:
    """Visible text of an HTML document, for comparing against what it rendered to."""
    import html as _html

    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    return _html.unescape(re.sub(r"<[^>]+>", " ", raw))


def numbers(text: str) -> set[str]:
    """Standalone numeric tokens. Wrapping and layout do not split a number."""
    return set(re.findall(r"(?<![a-z0-9])(\d+(?:\.\d+)?)(?![a-z0-9])", text.lower().replace(",", "")))


#: Identity facts that must survive the trip from a document into its PDF. These are the fields an
#: employer reads first, they change rarely, and the PDF is generated by hand - which is exactly the
#: combination that let five of them go stale at once. Single tokens only: the reason the check above
#: compares numbers rather than words is that prose wraps, so anything added here must not.
PDF_FACT_TOKENS = (
    "Bhaktapur",
    "sushant.poudel2028@gmail.com",
    "sushant-me",
)


def check_pdf_sources(files: list[pathlib.Path]) -> list[str]:
    """Every number in an attached PDF must still appear in the HTML it was rendered from.

    The PDFs are rendered from their HTML by hand, so an edit to the HTML does not reach the
    copy an employer or funder opens. That is not hypothetical: `PROPOSAL.pdf` still carried
    the previous corpus count, in two sentences, after the number had been corrected in both
    the `.md` and the `.html` and after specific rules had been added for it - the rules
    matched the plain-text surfaces and had nothing to say about a PDF.

    Comparing the *word* sets produced five false positives per document, all of them line
    wrapping (`full-` + `stack`, a URL split across lines). Numbers do not wrap, so a number
    that appears in the PDF and nowhere in the HTML is either a stale figure or a rendering
    error, and it is the class of divergence that costs something.
    """
    problems: list[str] = []
    for pdf in files:
        if pdf.suffix != ".pdf":
            continue
        source = pdf.with_suffix(".html")
        if not source.exists():
            continue
        text = read(pdf)
        if not text.strip():
            # An unreadable PDF used to pass every assertion below, because an empty string
            # yields an empty number set and an empty set has nothing that is not a subset.
            # The check could not tell "the PDF agrees with its HTML" from "the PDF was never
            # read" - so a missing pdftotext, a scanned page or a corrupt file reported a
            # clean result for a document nothing had looked at.
            #
            # That is the failure this guard was written about: PROPOSAL.pdf kept carrying a
            # superseded corpus count through several corrections. Making the read itself
            # asserted is what stops the guard going quiet the same way.
            problems.append(
                f"{pdf.name} produced no text, so nothing was checked against it. "
                "Is pdftotext installed?"
            )
            continue
        # A number comparison cannot see a stale WORD, and that is not hypothetical: five PDFs
        # carried the previous city for several rounds after their HTML said the new one, and this
        # guard reported nothing because a city is not a number. The comparison below was narrowed
        # to numbers because whole-word sets produced line-wrap false positives, so these tokens are
        # single words that cannot wrap - the failure was a place name, and a place name is one word.
        html = html_text(source)
        for token in PDF_FACT_TOKENS:
            if token in html and token not in text:
                problems.append(
                    f"{pdf.name} does not contain {token!r} although {source.name} does: the PDF "
                    "was not regenerated after the HTML changed")
        stale = sorted(numbers(text) - numbers(html))
        if stale:
            problems.append(
                f"{pdf.name} contains {stale}, which {source.name} no longer contains: the PDF "
                "was not regenerated after the HTML changed")
    return problems


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
    generations = committed_generation_count()
    if generations is not None:
        counts["raw_generations"] = generations
    conditions = committed_condition_count()
    if conditions is not None:
        counts["conditions"] = conditions
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
    # Thousands are written with a comma on the deployed pages, so the token is captured
    # with it and normalised by as_int() rather than by int().
    (re.compile(r"\b(\d[\d,]*)\s+raw model generations\b"), "raw_generations",
     "raw model generation count"),
    (re.compile(r"\b(\d[\d,]*)\s+raw model outputs\b"), "raw_generations",
     "raw model generation count"),
    (re.compile(r"\b(\d+)\s+conditions\b"), "conditions", "condition count"),
]


def strip_fenced(text: str) -> str:
    """Prose with fenced code blocks removed, for the count rules only.

    A count inside a ``` block is usually a transcript of what a command printed, not a claim
    about the design - and a transcript has to stay verbatim or it stops being evidence. When the
    study's checker was found to be mislabelling a replication block as a condition, the writeup
    that had pasted its output kept the wrong line on purpose and carried a correction beneath it;
    the rule then failed on the preserved quote. Transcripts are excluded, prose is not.
    """
    return re.sub(r"^\s*```.*?^\s*```", " ", text, flags=re.S | re.M)


def as_int(token: str) -> int:
    """A captured count, comma or no comma. Prose writes 3,000; int() refuses that."""
    return int(token.replace(",", ""))


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


def hackinghub_figure_disagreements(files: list[pathlib.Path]) -> list[str]:
    """A surface that states the HackingHub figure must state the *current* one.

    That figure is replicated across sixteen artifacts -- profile README, hire
    page, portfolio, three CV variants in four formats, the evidence sheet,
    evidence.json -- and `verify_evidence.py` reads back exactly one of them. It
    went stale twice in a single day for that reason: the board moves, one file is
    checked, and the other fifteen are corrected by hand.

    A number replicated sixteen ways should be derived from one place. Where it
    cannot be, it should at least be *compared* to one place, which is what this
    does: the expected value comes from `evidence.json` -- the file that is
    actually verified against the live API -- and every other surface that states
    a different one is a failure.

    Two deliberate limitations:

    * ``.pdf`` is skipped. These are the artifacts that reach an employer, and
      they matter most; but they are binary, a regex over one is not a check, and
      they are generated from the HTML that *is* checked here. They are covered
      by being regenerated from a checked source, not by this function.
    * The next-ranked account's figures (``... holds 97 flags``) are a different
      claim and are excluded, or this would fail on correct data.
    """
    import json
    import re

    try:
        evidence = json.loads((HERE / "evidence.json").read_text())
        claim = next(c for c in evidence["claims"]
                     if c["id"] == "hackinghub-rank-1")
    except Exception:
        return []          # verify_evidence.py owns that file and reports on it

    flags = claim["verification"]["expect"]["flags"]
    xp = claim["verification"]["expect"]["xp"]

    # The runner-up's figure is a different claim. Enumerating the phrasings is
    # fragile -- the first version of this looked only for "next"/"account holds"
    # and a CV saying "ahead of a runner-up on 97 flags" tripped it -- so the
    # marker list is deliberately broad, and a false positive here is a loud
    # failure on correct data.
    other = re.compile(
        r"(next|runner[- ]?up|second|behind|ahead of|account holds|the account)",
        re.I)

    problems: list[str] = []
    for path in files:
        if path.suffix == ".pdf":
            continue
        try:
            text = path.read_text(errors="replace")
        except Exception:
            continue
        for match in re.finditer(r"(\d[\d,]*) (?:flags|XP)", text):
            if other.search(text[max(0, match.start() - 60):match.start()]):
                continue
            stated = int(match.group(1).replace(",", ""))
            unit = match.group(0).split()[-1]
            expected = flags if unit == "flags" else xp
            if stated != expected:
                problems.append(
                    f"{path.relative_to(WORKSPACE)} states {match.group(0)!r} "
                    f"but evidence.json says {expected} {unit}")
    return problems


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

    # 0c. A figure replicated across surfaces must agree across surfaces.
    problems.extend(hackinghub_figure_disagreements(files))

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

    problems.extend(check_pdf_sources(files))

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
            for found in pattern.findall(strip_fenced(text)):
                if key not in truth:
                    # The corpus is not in this checkout, so its count cannot be re-derived.
                    # Recorded rather than passed silently: a count nobody could check must
                    # not look like a count that was checked.
                    if what not in counts_skipped:
                        counts_skipped.append(what)
                    continue
                counts_checked += 1
                if as_int(found) != truth[key]:
                    problems.append(
                        f"{path.relative_to(WORKSPACE)}: says {found} for the {what}, "
                        f"but the corpus has {truth[key]}")

    # 3b. Test counts stated in evidence.json, re-derived from the suites. Section 3 makes
    #     evidence.json the source of truth for every prose count; this is the rule that stops
    #     evidence.json itself from drifting, which is how three of its counts went stale while
    #     every README already had the right number.
    tc_problems, tc_checked, tc_skipped = test_count_disagreements()
    problems.extend(tc_problems)
    counts_checked += tc_checked
    counts_skipped.extend(tc_skipped)

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
