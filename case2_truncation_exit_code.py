#!/usr/bin/env python3
"""Case 2 as a defect/control pair: a scanner that prints its own truncation and passes.

Submitted to the Open Evidence Lab (probityai/agent-evidence-atlas#49) in response to
@astrogilda's request for "Case 2 as a defect/control pair with the before and after
exit codes".

The defect lived in `check_secrets.py` in this repository. Nothing about it was silent:
the scan reached `MAX_FILE_FETCHES`, printed the number of repositories it had not
opened, and then returned success anyway. The check reported "no credential-shaped
values found in public repositories" over an account it had read ~half of.

That makes it a different failure from a scanner that crashes or lies. The information
was on stdout and the exit code ignored it.

This harness runs the exit-code decision ONLY, with no network access, so both arms are
reproducible offline and in CI. It is the decision that is under test, not the API path.

Usage:
    python3 case2_truncation_exit_code.py        # exits 0 when the pair holds
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

# ---------------------------------------------------------------------------
# The two versions of the decision, reduced to the minimum that carries it.
#
# Both are quoted from real revisions of check_secrets.py in this repository:
#   defect  = the code before f950b642c
#   control = the code from f950b642c onward
# ---------------------------------------------------------------------------

DEFECT = textwrap.dedent(
    """
    import sys

    # Real values from the run that exposed this: the account held 90 owned public
    # repositories and a complete scan reads 1208 files, against a global cap of 600.
    MAX_FILE_FETCHES = 600
    MIN_FILES_READ = 25
    read_count = 612                       # it did read a lot -- just not everything
    findings = []                          # nothing matched in the half it did read
    skipped = [f"repo-{i}" for i in range(40)]   # 40 repositories never opened

    print(f"files read        : {read_count}")
    if skipped:
        print(f"truncated         : {len(skipped)} repo(s)")
        for s in skipped[:3]:
            print(f"    - {s}")
    print()

    if findings:
        print("FINDINGS: credential-shaped value(s) in public repositories")
        sys.exit(1)

    if read_count < MIN_FILES_READ:
        print(f"::error::only {read_count} file(s) read, below the {MIN_FILES_READ} floor")
        sys.exit(1)

    # The defect: `skipped` was never consulted here.
    print("no credential-shaped values found in public repositories")
    sys.exit(0)
    """
)

CONTROL = textwrap.dedent(
    """
    import sys

    MAX_FILE_FETCHES = 600
    MIN_FILES_READ = 25
    read_count = 612
    findings = []
    skipped = [f"repo-{i}" for i in range(40)]

    print(f"files read        : {read_count}")
    if skipped:
        print(f"truncated         : {len(skipped)} repo(s)")
        for s in skipped[:3]:
            print(f"    - {s}")
    print()

    if findings:
        print("FINDINGS: credential-shaped value(s) in public repositories")
        sys.exit(1)

    if read_count < MIN_FILES_READ:
        print(f"::error::only {read_count} file(s) read, below the {MIN_FILES_READ} floor")
        sys.exit(1)

    # The control: a truncated scan is the same failure as reading nothing, one step
    # later, so it is fatal here.
    if skipped:
        print(f"::error::{len(skipped)} repository(ies) were never scanned because the")
        print(f"         fetch cap ({MAX_FILE_FETCHES}) was reached:")
        for s in skipped[:3]:
            print(f"           - {s}")
        print("         a partial scan is not evidence of a clean account.")
        sys.exit(1)

    print("no credential-shaped values found in public repositories")
    sys.exit(0)
    """
)


def run(label: str, source: str) -> tuple[int, str]:
    """Executes one arm in a fresh interpreter and returns its exit code and tail."""
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=30,
    )
    tail = [ln for ln in result.stdout.strip().splitlines() if ln.strip()][-3:]
    print(f"  {label}")
    print(f"    exit code: {result.returncode}")
    for line in tail:
        print(f"    | {line}")
    print()
    return result.returncode, result.stdout


def main() -> int:
    print("Case 2: a scanner that printed its truncation and passed anyway")
    print("=" * 70)
    print("Scenario, shared by both arms: 612 files read, 0 findings, 40 repositories")
    print("never opened because the global fetch cap of 600 was reached.")
    print()

    defect_code, defect_out = run("DEFECT  (before f950b642c)", DEFECT)
    control_code, control_out = run("CONTROL (f950b642c onward)", CONTROL)

    print("=" * 70)
    checks = [
        (
            "the defect exits 0",
            defect_code == 0,
            f"got {defect_code}",
        ),
        (
            "the defect claims a clean account",
            "no credential-shaped values found" in defect_out,
            "the clean-sheet line is absent",
        ),
        (
            "the defect still prints its own truncation",
            "truncated" in defect_out,
            "the truncation line is absent -- then it would be a *silent* failure, "
            "which is a different and easier defect",
        ),
        (
            "the control exits 1",
            control_code == 1,
            f"got {control_code}",
        ),
        (
            "the control names the cause",
            "were never scanned" in control_out,
            "the error does not say what happened",
        ),
    ]

    ok = True
    for label, passed, detail in checks:
        print(f"  {'ok  ' if passed else 'FAIL'} {label}" + ("" if passed else f"  ({detail})"))
        ok &= passed

    print()
    if ok:
        print("PASS  both arms hold: same inputs, exit 0 by defect, exit 1 by control.")
        print()
        print("The transferable statement: a tool that reports its own incompleteness")
        print("truthfully and still passes has not failed quietly. It has decided that")
        print("the report of incompleteness is not an error condition -- and a caller")
        print("reading only the exit code cannot tell that decision was made.")
        return 0

    print("FAIL  the pair does not hold; see the checks above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
