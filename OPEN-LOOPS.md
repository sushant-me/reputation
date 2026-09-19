# Open loops — the complete list

The reason things felt "lost" is that this list existed only in your head. Here it
is in one place, with the owner and the next action. Anything not on this list is
either finished or deliberately parked, and **parked is a decision, not a failure** —
the difference is that it is written down.

---

## Closed in this work session

| loop | what happened |
|---|---|
| **The AI repository was local-only** | 16 commits / 28,656 lines — voice front end, agent loop, selective memory, keyed long-context store, trained emotion classifier, dashboard + one-call API — were sitting on this disk while the profile README linked the repo as public. **Pushed** to `sushant-me/beyond-attention`. |
| **Claims that could not be checked** | Every claim now lives in `reputation/evidence.json` with its source, and a script re-checks all of them weekly. 15 claims, 11 verified live, 0 failing. |
| **Profile README with no verifiable claim on it** | Replaced with the receipts: merged Google patch, five s2geometry issues, HackingHub #1 with numbers, two papers. All 24 links return 200. |
| **Three repositories red for weeks** | `ghar-ko-sathi-nepal` (red since 2026-08-05), `tradiemate-australia`, `tdd-bdd-final-project` — all root-caused, fixed, and green in real CI. |
| **Notifications** | 32 unread → 0, each one explained rather than dismissed. |
| **The portfolio site was the stalest public surface** | `sushantpoudel2028.com.np` did not mention the merged Google patch, the s2geometry issues, the HackingHub rank or either accepted paper, and it omitted the two years at Atmos SoftTech entirely. Rewritten from the verified record, **deployed and confirmed live** (the page now shows all of them), and it links the reputation repo along with a note that the claims are re-checked weekly. |
| **No published writing** | The strongest story in the record — the patch I closed on myself after AddressSanitizer showed it fixed a different bug — is now a public writeup: `sushant-me/writeups` → [*The crash that wasn't*](https://github.com/sushant-me/writeups/blob/main/2026-09-19-the-crash-that-wasnt.md), linked from the profile. |
| **Hunting for openings by hand** | `job-kit/LIVE-OPENINGS.md`: verified platforms that accept Nepal (OpenTrain AI lists it explicitly, $30–65/hr contractor), plus today's specific leads and what to write for each. |
| **Nothing said what you can be hired *for*** | **https://sushant-me.github.io/hire/** is live — one page, no build step, printable: the three services (agent/LLM security review, memory-safety and fuzz-harness work, evaluation design), what a client receives, how an engagement is scoped, and the receipts. Linked from the profile. |
| **One CV had to serve every application** | `cv/Sushant_Poudel_CV_AISecurity.pdf` — a 2-page AI-security CV with the verified record at the top, built from the same evidence file as everything else. The 4-page version stays for contexts that want the full history. |
| **Applications still had to be written from scratch** | `job-kit/APPLICATIONS-READY.md` — four send-ready drafts (Mercor AI red team, BayOne AI security & governance, BirdsVue agentic AI + security, and a cold email to an AI security team), each under 200 words, with the attachments and the exact evidence to cite. Sending them needs your accounts; everything up to that is done. |
| **A client had no way to see the deliverable** | `sushant-me/agent-review-sample` — a deliberately vulnerable 180-line agent and the four-finding review I would return for it: severity, mechanism at file and line, reproduction, fix, and a *"what was not tested"* section. `python3 demo.py` reproduces all four and exits non-zero if one stops reproducing; CI runs it on Python 3.11, 3.12 and 3.13. Linked from the hire page under the review service. |
| **The paper measured a problem and shipped no fix** | `sushant-me/policygate` — a fail-closed policy gate for agent tool calls that encodes the measurement: a model may deny or escalate and **cannot authorise** an uncovered action; a failing or unparseable evaluator falls through to a refusal; every decision lands in a hash-chained audit log. 32 tests, mutation-checked (weakening the model-allow invariant fails three of them), stdlib only, CI green on 3.11–3.13. Live on the hire page and covered by the evidence script. |
| **policygate could not be dropped into anything** | Adapters for MCP-style servers, LangChain-style tools and provider-shaped function calls, all duck-typed so no framework becomes a dependency. `GatedMCPServer` also refuses a server whose tool names collide with names the framework reserves — before any call happens. `examples/agent_integration.py` prints the evidence: four attempts, two reach the server, an offline evaluator executes nothing. **A new adapter found a hole in itself**: an unparseable call was passed through as an ordinary argument, and a name-only allow rule approved arguments the gate never read; it is now escalated without consulting the policy. 58 tests; weakening either that fix or the model-allow invariant fails six of them. |
| **The MCP work had no client-facing product** | `sushant-me/mcpaudit` — audit an MCP server's tool declarations before you connect, and pin them so a later change is a diff instead of a silent steering of the agent. Eleven checks across four severities, a lock file with per-field drift detection (a changed *description* is the tool-poisoning shape), exit codes for CI, 41 tests, stdlib only, no network or SDK. **Silent on a well-behaved server — that is a test**, because my first version flagged a read-only documentation search as a sink. Now sold as its own fixed-price engagement on the hire page. |
| **The three tools were separate stories** | `mcpaudit policy` now emits the policy that `policygate` enforces, from the same declarations: collisions and instruction-carrying descriptions deny, ambiguous tools escalate, clean read-only tools are allowed, and anything the audit never saw escalates. The integration is verified in CI by loading the generated policy with the real loader (policygate pinned to a commit, 71 tests on three Python versions). **Writing it found a supply-chain bug in the generator**: an unescaped tool name could inject its own `effect = "allow"` rule into the policy governing the server — four regression tests now cover it. |
| **The detectors asserted instead of measuring** | `tool-boundary-corpus` — 18 labelled cases (13 tool-list, 5 code) and a detector-agnostic harness. Measured: mcpaudit **P=1.000 R=1.000**, agentbound **P=0.750 R=1.000**. The corpus immediately found a real false positive in agentbound (a pattern inside a string literal, which its comment fix does not cover) — kept failing and named in CI rather than deleted. Two of my fixtures were wrong, not the detector: the rules require the framework to *define* the tool, and the full signature→params→filter relation. **Fixed and re-measured:** agentbound v0.1.10 extended its prose classifier to strings bound to a name; the corpus now measures it at precision 1.000 and the CI gate was tightened from a recall floor to precision and recall. |
| **Nobody could find any of it** | GitHub **topics** set on eight repositories, so they now surface in topic search (verified: `agent-review-sample` appears under `topic:agent-security`). Draft posts written for Hacker News, r/LocalLLaMA, Show HN, r/netsec and LinkedIn in `job-kit/LAUNCH-POSTS.md` — **posting them needs your accounts**, one per day. |
| **Only one piece of writing** | A second writeup, and the more important one: [*Structured output made my safety evaluator less safe*](https://github.com/sushant-me/writeups/blob/main/2026-09-20-structured-output-made-it-less-safe.md) — the paper's counter-intuitive result, with all 21 numbers checked against the paper's own README before publication. Now the lead item in the profile's writing section. |

## Waiting on other people (your next action is a reminder, not work)

| loop | state | next action | when |
|---|---|---|---|
| s2geometry **#681**, **#682** | open, all checks pass; the *new* CI runs need a Google maintainer to approve them | if nothing moves, one short polite comment on #682 | 7 days |
| adk-go **#1606**, adk-java **#1515**, adk-python **#7145** | open, awaiting review; the red checks are fork-PR gating, not code | leave them; reply only if a maintainer replies | — |
| libphonenumber **#4079**, gson **#3121** | open, no reviewer yet | leave them | — |
| go-github **#4556** | **merged** ✔ | nothing — note it is *not* eligible for Google Patch Rewards, so do not spend time there | — |

## Yours to do, with a date

| loop | why it matters | next action |
|---|---|---|
| **Firewall paper — camera-ready + supplementary file** | the portal status says *"Accept with Revision"* and **"Supplementary File Not Uploaded"**; the paper is your strongest single asset and it is one upload away from finished | upload the supplementary file, confirm the camera-ready deadline, submit | 
| **PREBAS** | accepted; a paper that is accepted but not presented is an unfinished credential | confirm registration, presentation format and travel/remote option | 
| **CV placeholders** | the university CV has two blanks I refused to invent | fill in the expected graduation month and the high-school GPA | 
| **Transformative AI Fund draft** | a full draft exists and is eligible (individuals, any country) | submit it, or shelve it deliberately — do not leave it in limbo | 
| **`tdd-bdd-final-project` archive state** | I unarchived it to fix CI; that was a change to your account you did not ask for | decide: keep it active (`gh api -X PATCH ... -f archived=true` reverts) | 
| **HackingHub Q3 #1** | the board resets each quarter, so this becomes a dated achievement rather than a current one | decide whether to defend it in Q4 (costs time) or let it stand | 
| **WATCHLIST CTF — 4 labs** | low value now that the event context has passed | park it explicitly | 

## The standing decision

**One spine: AI agent security and verification.** The papers, the Google pull requests,
`agentbound` / `mcp-nameguard` / `trajectorycheck`, and the memory-safety work all already point at it.
The rest — CTF rank, Hult Prize, the Flutter apps, the 100+ exercise repositories — is supporting
evidence, not a competing headline.

**And the rule for the next month: start nothing new.** Every loop above is either someone else's
turn or a small finishing task. The work that creates reputation now is finishing, publishing and
applying — not adding a fourteenth project.

## How to keep this list honest

Re-run it weekly and delete rows that are done:

```bash
cd reputation && python3 verify_evidence.py     # 0 failing = your public claims are still true
gh api notifications --paginate -q 'length'     # 0 = nothing unread waiting on you
```

If a row has no next action, it is not a loop — it is a decision you have not made yet. Make it.
