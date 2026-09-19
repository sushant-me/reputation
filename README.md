# reputation — every claim I make, and how to check it

A CV is a document nobody can verify. This repository is the opposite: it lists
each claim I make about my own work, names the public source it came from, and
re-checks all of them against those sources on every push and once a week.

```
STATUS      CLAIM                                                    NOTE
PASS        Rank 1 on the HackingHub Q3 2026 global leaderboard       rank 1, 116 flags, 11860 XP
PASS        Pull request merged into google/go-github                merged 2026-09-17 by gmlewis
PASS        Five open memory-safety issues in google/s2geometry      5 issues open: #674, #676..#679
PASS        Two hardening pull requests under review in s2geometry   s2geometry#681 open, #682 open
PASS        Fixes and reports for MCP tool shadowing                 adk-go#1606, adk-java#1515, adk-python#7145
PASS        An OSS-Fuzz harness that was testing nothing, fixed      0.00% -> 93% line coverage
on-request  AI Engineer at Atmos SoftTech, March 2024 - March 2026    signed experience letter
on-request  PREBAS accepted, 2026 IEEE RTC (Chicago)                  acceptance notification
```

Run it yourself:

```bash
python3 verify_evidence.py          # 18 claims: 14 checked live, 4 on request
python3 verify_evidence.py --json    # same, machine-readable
```

It exits non-zero the moment a claim stops being true, so a stale claim cannot
sit here quietly: this README's badge goes red first.

## Why this exists

I found a section of my own CV that said *"181 correctness tests"* long after the
suite had grown past it, and a paper listed as accepted at a venue that my own
submission portal described differently. Neither was a lie at the time it was
written. Both were the ordinary way a CV rots — and both are the kind of thing a
reader cannot check, which is exactly why they survive.

So the rule here is: if a claim cannot be pointed at a public source, it is
marked `on-request` and named as documentation I can supply, rather than printed
next to the verified ones as if it were the same kind of statement.

## The two kinds of claim

| status | meaning |
|---|---|
| `PASS` | checked live against the source named in `evidence.json` |
| `on-request` | not checkable from outside — a signed letter, a transcript, a conference acceptance email. Listed as documentation available on request, never as "verified". |

## Files

- `evidence.json` — the claims, their sources, and the check each one requires.
- `verify_evidence.py` — the checker (stdlib plus `gh` for the authenticated GitHub calls).
- `.github/workflows/verify.yml` — runs it on push, weekly, and on demand.

## Honest limits

- It verifies that a source says what I claim it says. It does not verify that my
  contribution was the important one — read the linked issue or pull request for
  that.
- Leaderboard positions are dated: the HackingHub board resets quarterly, so
  `Q3 2026` is part of the claim, not a footnote.
- A merge is not an endorsement, and an open pull request is not a merged one;
  the script reports the state it finds rather than the one I would prefer.
