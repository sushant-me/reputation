#!/usr/bin/env python3
"""Append a claim to evidence.json WITHOUT repeating the round-70 and round-96 mistake.

Adding a claim is three coupled edits, and performing the first one alone has now
silently invalidated published surfaces twice:

  1. append the claim
  2. give it a `verification` block the verifier's dispatch table recognises
     (omitting it crashes check_surfaces.py with KeyError: 'verification')
  3. update every surface that states the count, and remember the LIVE deployment
     is one of them

This script refuses to do 1 without 2, and reports the surfaces that step 3 still
needs. It does not edit prose for you -- it tells you exactly which files will fail,
so the count is never left drifting.

Usage:  python3 reputation/add_claim.py claim.json
"""
from __future__ import annotations
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "reputation" / "evidence.json"
REQUIRED_TOP_LEVEL = ("claim", "id", "category", "verification", "source")
REQUIRED_VERIFICATION = ("method", "expect")


def load():
    d = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    items = d if isinstance(d, list) else (d.get("claims") or d.get("evidence"))
    return d, items


def main(argv):
    if len(argv) != 2:
        print(__doc__); return 2
    claim = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))

    # --- every field the two checkers read, checked BEFORE step 1 ---
    # verify_evidence.py reads claim["id"] and claim["category"]; omitting either
    # raises KeyError there. check_surfaces.py reads verification["method"].
    miss_top = [k for k in REQUIRED_TOP_LEVEL if k not in claim]
    if miss_top:
        print(f"REFUSED: claim is missing {miss_top}.")
        print("  verify_evidence.py reads `id` and `category`; check_surfaces.py reads")
        print("  `verification.method`. Omitting any of them crashes a checker.")
        return 1

    # --- step 2 enforced BEFORE step 1 ---
    v = claim.get("verification")
    if not isinstance(v, dict):
        print("REFUSED: the claim has no `verification` object.")
        print("  Every claim needs one, or check_surfaces.py raises KeyError: 'verification'.")
        print("  Minimum shape: {\"verification\": {\"method\": ..., \"expect\": ...}}")
        return 1
    missing = [k for k in REQUIRED_VERIFICATION if k not in v]
    if missing:
        print(f"REFUSED: `verification` is missing {missing}.")
        return 1
    try:
        sys.path.insert(0, str(ROOT / "reputation"))
        import verify_evidence
        if v["method"] not in verify_evidence.CHECKS:
            # A method outside CHECKS is not automatically wrong: those are the
            # "documented on request" claims, which is a legitimate category. Accept it
            # only if an existing claim already uses that method, so a typo is still
            # refused while `human_asserted` and its siblings are allowed through.
            d0, items0 = load()
            known_on_request = {c.get("verification", {}).get("method")
                                for c in items0 if isinstance(c, dict)
                                and c.get("verification", {}).get("method") not in verify_evidence.CHECKS}
            if v["method"] not in known_on_request:
                print(f"REFUSED: method {v['method']!r} is neither in verify_evidence.CHECKS nor")
                print(f"  used by any existing on-request claim. Known on-request methods: "
                      f"{sorted(m for m in known_on_request if m)}")
                return 1
            print(f"NOTE: {v['method']!r} is an on-request method (counted, not live-checked).")
    except Exception as exc:
        print(f"NOTE: could not import verify_evidence to check the method ({exc}).")

    d, items = load()
    before = len(items)
    if any(json.dumps(x).find(str(v.get("url", "\0"))) != -1 for x in items):
        print("REFUSED: a claim with that verification URL is already present.")
        return 1
    items.append(claim)
    EVIDENCE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"added: claims {before} -> {len(items)}")

    # --- step 3: name the surfaces that now disagree ---
    print("\nstep 3 -- these surfaces still state the OLD count and will fail the checker:")
    try:
        out = subprocess.run(
            [sys.executable, str(ROOT / "reputation" / "check_surfaces.py")],
            capture_output=True, text=True, timeout=900).stdout
        fails = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
        if not fails:
            print("  none -- nothing states the count, or they were already generic.")
        for l in fails:
            if "claim count" in l or "on-request" in l:
                print("  " + l[:150])
        if any("sushantpoudel2028.com.np" in l for l in fails):
            print("\n  ** THE LIVE DEPLOYMENT IS ONE OF THEM -- a source edit is not enough;")
            print("     it needs a push, because CI deploys on push to main. **")
    except Exception as exc:
        print(f"  could not run the checker: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
