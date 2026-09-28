# Three live credentials are public right now — rotate them

*Found 2026-09-28 by `reputation/check_secrets.py` (80 owned public repositories,
1,092 files read), then confirmed by hand. All three repositories are PUBLIC and
the files are readable without authentication.*

---

## What is exposed

### 1. Google API key — `sushant-me/nec-campus-app` ← the urgent one

| | |
|---|---|
| **File** | `android/app/google-services.json` |
| **Value** | `AIza…kvYc` — 39 characters, the standard Google key shape |
| **Entropy** | 4.68 bits/char — the highest of the three |
| **Repo state** | **public, NOT archived** — this is the only one of the three still an active repository |
| **Risk** | depends on the key's API restrictions. Unrestricted, it bills to your Google Cloud project |

This is the one to do first. The other two are archived, which at least means they
are no longer being pushed to; this one is live.

### 2. Google API key — `sushant-me/user-screen-test`

| | |
|---|---|
| **File** | `android/app/google-services.json` |
| **Value** | `AIzaSyAr…prPw` — 39 characters |
| **Repo state** | **public**, archived, last pushed 2026-07-15 |
| **Readable at** | `https://raw.githubusercontent.com/sushant-me/user-screen-test/master/android/app/google-services.json` → HTTP 200, verified by hand |

### 3. OpenWeatherMap API key — `sushant-me/weather-`

| | |
|---|---|
| **File** | `script.js` |
| **Line** | `API_KEY = "0e5b…dde2"` — 32 hex characters, redacted here on purpose (see the note below) |
| **Type** | OpenWeatherMap — 32 hex characters, their standard format |
| **Repo state** | **public**, archived, last pushed 2025-06-30 |
| **Readable at** | `https://raw.githubusercontent.com/sushant-me/weather-/master/script.js` → HTTP 200, verified by hand |

The key is used in a request URL further down the same file
(`...&appid=${API_KEY}&units=metric`), so it is a working credential, not a
placeholder.

**Why the Google keys might look harmless and are not:** a Firebase key restricted
to one package name and SHA-1 is mostly inert, and that is probably what these are.
But you cannot tell from the file whether the restriction is set, and the cost of
finding out the hard way is a bill on your Cloud project. Rotate, and set the
restriction explicitly on the replacement.

---

## Why deleting the file is not the fix

Deleting a file removes it from the current tree. It does **not** remove it from:

- the git history, which keeps every blob forever;
- GitHub's fork network, if anyone forked the repository;
- search-engine caches and code-search mirrors that have already indexed it;
- the raw CDN, which serves by commit SHA independently of the branch tip.

The blob is already public. `check_secrets.py` says this in its own output and it is
the whole point:

> *"A finding is a prompt to rotate, not just to delete: the blob is already public,
> and removing the file does not un-publish the value."*

**Rotation is the only action that ends the exposure.** Once the key is dead, the
public blob is a dead string and the archaeology stops mattering.

### And why the values are redacted in this file

This document lives in `sushant-me/reputation`, which is **public**. Writing the
full key here would publish it a second time, in a second repository, and make the
exposure worse rather than better — the exact failure this repository was built to
catch. So every value in this file is truncated after four characters, and the
scanner's own allowlist would have flagged it if it were not.

That is also why the fix is rotation rather than deletion: the redaction protects
*this* file, and nothing can protect the original.

---

## The exact steps

### The two Google keys

1. Google Cloud Console → **APIs & Services** → **Credentials**.
2. Find each key → **Delete** (deleting is better than regenerating here, because
   the old value stays public either way).
3. For the replacement, set **both** an application restriction (Android apps +
   package name + SHA-1) **and** an API restriction.
4. Re-download `google-services.json` for the new key.
5. Add `**/google-services.json` to `.gitignore` in **both** projects, so this
   cannot recur. `nec-campus-app` first.
6. If either project used it for Firebase, confirm the new file is not committed
   before you push.

### The OpenWeatherMap key

1. Sign in at `home.openweathermap.org` → **My API keys**.
2. **Delete** `0e5b…dde2` and generate a replacement.
3. Move the new key into an environment variable or a gitignored `.env`.
4. If billing is attached, check the usage graph for the period the key was public.

### Then, for all three

7. Archive is **not** protection. Two of these repositories are archived and still
   public — archiving freezes a repository, it does not hide it.
8. If a repo should not be publicly browsable, set it private
   (`gh repo edit sushant-me/<repo> --visibility private`). Do that **after**
   rotating, never instead of it.

---

## What this says about the process

`check_secrets.py` exists because `sentiment-analysis` sat public from 2025-06-13
with a live Twitter/X OAuth set — consumer key, consumer secret, access token and
access-token secret — for **fifteen months**, and nothing caught it.

**Two claims I made about the CI were wrong, and are corrected here.**

I first wrote that the scan "was not being run", and then that it "had never
passed". Checked against the run history, neither holds:

- **It is scheduled.** `secrets.yml` carries `cron: "15 6 * * 1"` — Mondays 06:15
  UTC — and the scheduled run *did* fire on 2026-09-28.
- **It ran and it worked.** The scheduled run enumerated 80 owned public
  repositories and 1,092 files, found all three credentials, and exited 1. That
  exit code is the tool being correct: it fails when a credential is public. The
  red X is accurate.
- **The workflow is new.** Its earliest run is 2026-09-22, so it did not exist
  while these keys were sitting public through 2025 and most of 2026. It did not
  miss them; it is the thing that found them.

What the history *does* show is a real bug worth recording. The first runs failed
with:

> `::error::no repositories enumerated; the scan could not run`

The enumeration returned nothing and the job failed closed — the right failure,
but not a scan. I reproduced the same message locally by passing a **filesystem
path** to `--repo` when the flag takes a **repository name**
(`--repo sushant-me/laya`, not `/home/logic/Work/laya-chat`). Later runs enumerate
correctly, so either the cause was fixed or it was that invocation.

The practical lesson is smaller than the one I first wrote and more useful: **a
check that fails closed is only as good as the person reading the red X.** Here it
was correct for a week and the keys are still live, because the finding sat in a CI
log rather than in front of someone who could rotate it. That is what this file is
for.

Two things still worth confirming in `.github/workflows/secrets.yml`: that
`GH_TOKEN` is present in the **scheduled** context (a schedule may lack secrets a
push has), and that the enumeration failure mode above cannot recur silently.

**The three honest limits of this scan**, from its own output:

- **Private repositories are out of scope** and are *not* assumed clean.
- 4 owned repositories are **empty** (no commits), so nothing was scanned in them.
- It cannot see a key inside a binary, inside a submodule it did not follow, or in
  a repository that was made private before the run.

Run it again after anything changes.


