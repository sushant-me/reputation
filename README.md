# reputation — every claim I make, and how to check it

A CV is a document nobody can verify. This repository is the opposite: it lists
each claim I make about my own work, names the public source it came from, and
re-checks all of them against those sources on every push and once a week.

```
STATUS      CLAIM                                                    NOTE
PASS        Rank 1 on the HackingHub Q3 2026 global leaderboard       rank 1, 142 flags, 14525 XP
PASS        Pull request merged into google/go-github                merged 2026-09-17 by gmlewis
PASS        Five open memory-safety issues in google/s2geometry      5 issues open: #674, #676..#679
PASS        Two hardening pull requests under review in s2geometry   s2geometry#681 open, #682 open
PASS        A maintainer independently reproduced my finding          on-keyday built both revisions and ran them
PASS        Three sisakulint issues filed from my rule audit          #646, #647, #648 open
PASS        Fixes and reports for MCP tool shadowing                 adk-go#1606, adk-java#1515, adk-python#7145
PASS        An OSS-Fuzz harness that was testing nothing, fixed      0.00% -> 93% line coverage
on-request  AI Engineer at Atmos SoftTech, March 2024 - March 2026    signed experience letter
on-request  PREBAS accepted, 2026 IEEE RTC (Chicago)                  acceptance notification
```

Run it yourself:

```bash
python3 verify_evidence.py            # 23 claims: 19 checked live, 4 on request
python3 verify_evidence.py --json     # same, machine-readable
python3 check_surfaces.py             # the pages a reader reaches
python3 check_surfaces.py --require-all   # ...including the CVs and job-kit, on the workstation
python3 check_links.py                # every external link on those pages still resolves
python3 check_secrets.py --self-test  # the credential detector fires on a known leak
python3 check_secrets.py              # ...then scans every owned repository
```

The maintainer row is checked by looking for their own words in their own
comment — the `named_person_said` method in `evidence.json`. An endorsement
nobody can point at is not evidence, so the quotation is the thing that is
verified, and editing the comment takes the claim down with it.

It exits non-zero the moment a claim stops being true, so a stale claim cannot
sit here quietly: this README's badge goes red first.

## The credential scan, and its one open finding

GitHub's free secret scanning matches **provider** patterns — AWS `AKIA…`, GitHub
`ghp_…`, Stripe `sk_live_…`. A plain `KEY = "value"` assignment is not one of
those, and the detector that covers it (`secret_scanning_non_provider_patterns`)
is part of paid Secret Protection: setting it through the API is accepted and
silently ignored, and it reads back `disabled`.

For fifteen months, then, the platform reported a clean account while
`sentiment-analysis` — public, and since archived — carried a live Twitter/X
OAuth set in a file called `api key.txt`: consumer key, consumer secret, access
token and access-token secret. The `secret-scanning/alerts` endpoint returned
`[]` for that repository, which is correct behaviour and not a safe answer.

`check_secrets.py` closes that gap from outside. **The scan is red on purpose,
and that is the honest state:**

- the four credentials **have not been rotated**, and rotation is the only real
  remediation — the blob is public, and deleting the file does not un-publish it;
- the repository is **archived**, so it is read-only and GitHub rejects the
  delete over the API: it needs unarchiving first.

It is built to fail loudly rather than quietly. There is a coverage floor, since
a scan that read nothing must not look like a clean account; every reported value
is redacted, so the CI log does not become a second copy of the credential; and
`--self-test` proves the detector fires on the original leak shape. That self-test
earned its place immediately — the placeholder filter began with an empty
alternative, matched every string, rejected all of them, and the detector
reported nothing at all. Without a fixture for the real shape, it would have
shipped as a check that could never fire.

## The second checker, and why one was not enough

`verify_evidence.py` checks the 18 top-level claims. It did **not** catch three
errors that were later found by hand, one round at a time, all on already-published
pages:

| what the page said | what the source says |
|---|---|
| "Merged into `google/go-github`" | merged, then **reverted the next day** in favour of the maintainer's broader fix — the page described code that is not in master |
| "weakening either invariant fails six tests" | six is **both** invariants at once; each fails three |
| a 16 GiB allocation attributed to a **five**-byte header | the issue says the input is **117 bytes**; nothing mentions five bytes |

That last row is spelled out rather than quoted, because `check_surfaces.py` forbids
the literal from this table down: a checker that exempts its own documentation is a
checker with an escape hatch, and an escape hatch is what the error got through the
first time.

Every one was a detail *inside* a claim that had been true when written, which is
precisely what a claim-level checker cannot see. So `check_surfaces.py` enforces the
error history itself: each wrong string is **forbidden** on every surface with the
reason it is wrong, each corrected string is **required** so a fix-by-deletion
fails, and every `releases/tag/vX.Y.Z` label must equal that repository's actual
latest release. It reports how many of its surface declarations matched, and fails
below `--min-surfaces`, because a check that found nothing to read is the same bug
wearing a green tick.

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
- `check_surfaces.py` — the other checker: forbidden and required strings across the
  published pages, plus release-link freshness. CI checks out the sibling repositories
  so it has four real surfaces; `--require-all` adds the CVs and `job-kit`, which are
  not repositories and therefore only reachable from the workstation.
- `check_links.py` — the third checker, covering both kinds of surface because both
  rot the same way: the **live pages** a reader lands on, and the **local surfaces**
  CI checks out beside this repo — the profile README, the project READMEs, the hire
  page and the portfolio source. It fails on `404`/`410` and on malformed URLs, and
  deliberately does **not** fail on `403`/`429`: a host declining automated clients
  says nothing about whether a reader can reach the page. It exists because two dead
  project links sat on the portfolio unnoticed — one pointed at a private repository
  so it 404'd for every visitor, and one had a phrase pasted into the URL. If fewer
  than six surfaces can be read it fails, because a run that found nothing to check
  has not checked anything.
- `.github/workflows/verify.yml` — runs all three on push, weekly, and on demand.

## Honest limits

- It verifies that a source says what I claim it says. It does not verify that my
  contribution was the important one — read the linked issue or pull request for
  that.
- Leaderboard positions are dated: the HackingHub board resets quarterly, so
  `Q3 2026` is part of the claim, not a footnote.
- A merge is not an endorsement, and an open pull request is not a merged one;
  the script reports the state it finds rather than the one I would prefer.
