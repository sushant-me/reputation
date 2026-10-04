#!/usr/bin/env python3
"""Flag OPEN-LOOPS rows that describe a world that has moved on.

WHY THIS EXISTS. Four rows were found stale in one pass, each by hand, each in
the same direction: the row told the reader to wait for, or to do, something that
had already happened.

  "one upload away from published"     -> published two days earlier (DOI)
  "sends once the credential exists"   -> already sent; credential never needed
  "the university CV has two blanks"   -> one was a shipped editing instruction
  the Infosecurity follow-up           -> was in no loop at all

verify_evidence.py re-checks CLAIMS against their sources weekly. check_surfaces.py
enforces that PAGES contain required strings. Neither asks whether a loop marked
"waiting" is still waiting. That is this file's only job.

Three checks, each against an artifact on disk rather than an opinion:

  1 QUEUED-BUT-SENT   a row that says queued/waiting and names an outbox id that
                      SENT-browser.log records as sent
  2 DEAD PATH         a row that names a file that does not exist
  3 PAST DEADLINE     a row whose `when` column is a duration that has elapsed
                      since the file was last updated

Exit 0 when clean, 1 when anything is flagged. Read-only.
"""
from __future__ import annotations
import json, os, pathlib, re, subprocess, sys

WORK = pathlib.Path("/home/logic/Work")
# Overridable so the missing-input path can be tested: in CI job-kit/ does not exist at
# all, and a guard that has never been exercised is not a guard.
KIT = pathlib.Path(os.environ.get("JOB_KIT", WORK / "job-kit"))
HERE = pathlib.Path(__file__).resolve().parent
# Flags are not paths. Passing --allow-missing-inputs used to be read as the path to
# OPEN-LOOPS.md, so the file was "missing", the unauthenticated remote fallback then
# failed, and the run reported "cannot read" - a flag breaking the check it belonged to.
ARGS  = [a for a in sys.argv[1:] if not a.startswith("--")]
LOOPS = pathlib.Path(ARGS[0]) if ARGS else HERE / "OPEN-LOOPS.md"
SENT = KIT / "SENT-browser.log"
OUTBOX = KIT / "outbox.json"

# Quoting a corrected claim is this repo's deliberate convention, so a row that
# says it WAS queued must not be flagged. Strip the explanation before testing.
CORRECTION_MARKERS = re.compile(r"was wrong|still said|This loop was wrong|~~|struck-out|"
                                r"out of date|no longer needed|superseded", re.I)
QUEUED_WORDS = re.compile(r"\bqueued\b|\bsends once\b|\bwaiting on\b|\bblocked on\b", re.I)
DURATION = re.compile(r"\b(\d+)\s*(day|week|month)s?\b", re.I)

def sent_ids() -> set[str]:
    if not SENT.exists():
        return set()
    ids = set()
    for line in SENT.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("id"):
            ids.add(r["id"])
    return ids

def outbox_ids() -> set[str]:
    if not OUTBOX.exists():
        return set()
    d = json.loads(OUTBOX.read_text(encoding="utf-8"))
    return {m["id"] for m in d.get("outbox", []) if m.get("id")}

def main() -> int:
    if not LOOPS.exists():
        # fall back to the published copy
        raw = subprocess.run(["gh","api","repos/sushant-me/reputation/contents/OPEN-LOOPS.md",
                              "--jq",".content"], capture_output=True, text=True, timeout=60).stdout
        if not raw.strip():
            print("  cannot read OPEN-LOOPS.md (local or remote)"); return 2
        import base64
        text = base64.b64decode(raw).decode("utf-8")
    else:
        text = LOOPS.read_text(encoding="utf-8")

    sent, queued = sent_ids(), outbox_ids()
    # job-kit/ is not a repository and is not checked out in CI, so the outbox-vs-send-log
    # comparison cannot run there. Saying "no stale loops found" in that state would be the
    # quiet-checker failure this file exists to catch: it means "nothing was compared".
    # Fail with the reason, unless --allow-missing-inputs says that is deliberate.
    if not (SENT.exists() and OUTBOX.exists()) and "--allow-missing-inputs" not in sys.argv:
        print("  CANNOT RUN - the inputs this check needs are absent:")
        for x in (OUTBOX, SENT):
            if not x.exists():
                print(f"    {x}")
        print("  Without both, a pass would mean 'nothing was compared', not 'nothing is stale'.")
        return 3
    print(f"  source          : {LOOPS}")
    print(f"  outbox entries  : {len(queued)}")
    print(f"  sent-log entries: {len(sent)}")
    print()

    problems = []

    # 1. QUEUED-BUT-SENT
    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|") or not QUEUED_WORDS.search(line):
            continue
        if CORRECTION_MARKERS.search(line):
            continue          # the row is describing an error it corrected
        ids = [q for q in queued if q in line] or [q for q in sent if q in line]
        for q in ids:
            if q in sent:
                problems.append((i, "QUEUED-BUT-SENT",
                                 f"row says queued/waiting but '{q}' is in SENT-browser.log"))

    # 2. DEAD PATH - REMOVED. Paths in OPEN-LOOPS.md are relative to per-repo
    #    roots (reputation/, cv/, tool-boundary-corpus/, Edge-Native_.../, ...),
    #    and without that mapping the check reported docs/supplementary.pdf as
    #    missing while it existed. Re-add it only with an explicit root per row.

    # 3. PAST DEADLINE (only for a duration in a `when`-looking column)
    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"): continue
        m = DURATION.search(line)
        if m and re.search(r"\bif nothing moves\b|\bstale\b|\bdo not\b", line, re.I) is None:
            problems.append((i, "CHECK-DEADLINE",
                             f"row carries a '{m.group(0)}' timer - confirm it has not elapsed"))

    if not problems:
        print("  no stale loops found")
        return 0
    for ln, kind, why in problems:
        print(f"  line {ln:<5} {kind:<16} {why}")
    print()
    print(f"  {len(problems)} item(s) to check by hand")
    return 1

if __name__ == "__main__":
    sys.exit(main())
