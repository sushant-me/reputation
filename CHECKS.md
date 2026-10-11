# How the checks work, and why they check what they do

This repository is three layers of checking. They exist in this order because each
one was built to catch what the previous one could not, and the failures that
motivated them are recorded here rather than left to be rediscovered.

```
verify_evidence.py     the 19 machine-checkable claims, against their live sources
check_surfaces.py      the same claims as they appear in prose, on published pages
check_links.py         that every external link on those pages still resolves
check_secrets.py       that no credential is sitting in a public repository
```

## Layer 1 — `verify_evidence.py`

`evidence.json` holds every claim I make about my own work. Each entry names the
public source it came from and the method used to check it, and the script re-fetches
every source on each push and once a week.

**It exits non-zero the moment a claim stops being true.** The point is that a stale
claim cannot sit here quietly: the README badge goes red first, not after someone
notices.

Two details worth knowing:

**`on-request` is a first-class outcome, not a failure.** Some claims rest on a
document I hold rather than a public URL — a signed experience letter, a conference
acceptance. Those are reported as `on-request` rather than passed silently, because
the difference between "verified" and "documented, on request" is the whole point.
A claim that cannot be checked is stated as such, not dressed as a pass.

**The `named_person_said` method checks a quotation, not a person.** Where a claim
rests on someone else's endorsement, the script looks for their own words in their
own comment. **An endorsement nobody can point at is not evidence, so the quotation
is the thing that is verified — and editing the comment takes the claim down with
it.** That is deliberate: a screenshot of praise is not verifiable, and a link to the
sentence is.

**What each source kind actually proves, and what it does not.** The methods are
narrower than the claims they support, and the boundary is worth stating:

| method | proves | does not prove |
|---|---|---|
| `github_issues_open` | the issues exist, are open, and any quoted phrase is still in the body | **who filed them, or why** |
| `github_pr_comment` | the comment exists, is by the named person, and still contains the quoted words | that the person endorses more than the quoted words |
| `url_live` | the page resolves and contains the named string | anything about the page beyond that string |
| `named_person_said` | the words are in that person's own comment | that they meant them as endorsement of the whole claim |

**One worked example, because the distinction is easy to miss.** A claim records that
three tracked issues were filed from an audit. The issues exist, are open, and are
traceable to their repository — **but they were opened by the maintainer, not by me.**
**The source verifies that the issues are real; it does not verify authorship, and it
cannot distinguish "filed from an audit" from "filed by me".** The wording is accurate
and the check is accurate; they simply cover different things, and a reader deserves to
know which part is machine-verified.

**That is not a defect in the checks — it is the reason `required` rules sit beside
`forbidden` ones.** A check has a scope, and the honest thing is to write the scope
down rather than let a passing check imply it covers more than it does.

## Layer 2 — `check_surfaces.py`

**Why it exists.** `verify_evidence.py` checks claims. It did not notice three
separate errors, because all three were *details inside* a claim that had been true
when it was written:

- **A merge that was reverted.** The claim that a fix landed in
  `google/go-github` was true when written and false the next day, so the page
  described code that is not in `master`.
- **Two cases collapsed into one number.** A sentence said that weakening *either*
  invariant fails a stated count of tests. The count was correct for both invariants
  at once; each fails half of it. One number had been made to serve two cases.
- **A byte count that appears nowhere.** A page described a malformed input at one
  size, and no issue in that repository mentions that size at all — the source says
  117 bytes.

**Each was found by hand, one at a time, on pages that had already been published.**
This script is the fix: every error becomes a rule, so the specific mistake cannot
return.

**The errors above are described rather than quoted, and that is deliberate — see
the note on quoted history at the end of this document.**

### The two rule kinds, and why both are needed

**`forbidden`** — a string known to be wrong or stale. If it reappears anywhere on a
surface, the check fails and reports the reason it was removed.

**`required`** — a corrected string that must appear on the surfaces making the claim.

**The `required` half is the part people miss.** Without it, "fixing" a wrong page by
*deleting the sentence* would pass every check. **A forbidden-string rule can only
detect the error coming back; it cannot detect the evidence going missing.** The two
together mean a surface has to contain the right thing and not the wrong thing — and
a check that only forbids is a check that rewards silence.

### Prose counts

Numbers stated in prose are asserted against the corpus they describe. The run prints
the truth and compares:

```
prose counts checked: 72 (truth: 27 claims, 19 live, 8 on request, 23 corpus cases)
```

**This is the rule that caught its own README.** The quickstart comment hardcoded the
totals, and by 2026-10-11 both had drifted — the stated claim count and the stated
on-request count were each short of the corpus, and the check had been failing on that
line. **The fix was not to update the numbers but to stop restating them** — a computed
value duplicated into prose is a claim nothing re-checks, which is the same rule this
repository applies to every other claim.

### Live checks

Beyond the string rules, two things are checked against the world rather than against
a file:

- **every `releases/tag/vX.Y.Z` link must equal that repository's actual latest
  release**, because a release moves and a label does not;
- **a small set of live pages is fetched** and asserted, so a surface that is correct
  in the repository but broken when served is still caught.

### What it asserts today

```
surface declarations:    29/29 matched  (109 files)
forbidden strings:       31 rules
required strings:        45 assertions
release links checked:   3
live pages checked:      21 assertions on 3 pages
prose counts checked:    72 (truth: 27 claims, 19 live, 8 on request, 23 corpus cases)

PASS  every known error is absent, and every correction is present
```

## Layer 3 — `check_links.py` and `check_secrets.py`

**`check_links.py`** resolves every external link on the surfaces. It classifies
unreachable links as `unverified` rather than `broken`, so a transient outage does not
cry wolf — **and it reports how many links it actually resolved, because a total
network failure previously produced `PASS 0 of 62` and exit 0, which is
indistinguishable from a clean estate.** The count is in the output for that reason.

**`check_secrets.py`** closes a gap in GitHub's own scanning. GitHub's free secret
scanning matches **provider** patterns — AWS `AKIA…`, GitHub `ghp_…`, Stripe
`sk_live_…`. **A plain `KEY = "value"` assignment is not one of those**, and the
detector that covers it is part of paid Secret Protection: setting it through the API
is accepted and silently ignored, and it reads back `disabled`.

**So this scan is red on purpose, and the red is the honest state.** There are live
credentials in an archived public repository, rotation is the only real remediation
because deleting the file does not un-publish the blob, and the archive status makes
the repository read-only. **A credential detector that could only ever report green
would be worse than none.** `--self-test` is provided so the detector's ability to
*fail* is itself checked.

## The rule all three layers share

**A check that cannot fail is not a check, and a check that passes when the evidence
is simply missing is worse than one that fails.** Every design choice above follows
from that:

- `on-request` instead of a silent pass, so "uncheckable" is visible;
- `required` rules beside `forbidden` ones, so deleting a bad sentence is not a fix;
- a link checker that reports its resolved count, so `0 of 62` cannot read as clean;
- a secret scan that is red on purpose, so green means something.

## A constraint worth knowing: history cannot be quoted

**A `forbidden` rule forbids the string anywhere on a surface, and the checker cannot
distinguish "quoting a past mistake as history" from "asserting it as a claim."**

This document was written once already, and the first version failed the check three
times — twice for quoting a wrong byte count while explaining that it had been wrong,
and once for quoting a stale total while explaining that totals drift. **The checker
was right and the document was wrong.** A page is a published surface; a reader
skimming it can take a quoted figure as a claim, and they have no way to know it was
being cited as an example.

**So the practical rule for writing here is: describe an error, do not reproduce it.**
"It said one size and the source says 117 bytes" is safe. Writing the wrong size out —
even inside quotation marks, even inside a fenced block — fails the check, deliberately.

**Whether that is the right trade is worth being honest about.** The stricter design
means the repository's own documentation cannot cite its own bugs verbatim, which costs
some precision. The looser design would mean carving exceptions into the rule — a marker
for quoted text, or skipping fenced blocks — and every exception is a hole an author can
mistake for a safe place to write the wrong string. **I chose strict, because the wrong
number appearing once on a published page does more damage than losing the verbatim
citation of it.**
