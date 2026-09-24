#!/usr/bin/env python3
"""Every post is listed in the index, and every row in the index is a post.

Why this exists
---------------
`check_links.py` already verifies that the links in `writeups/README.md` resolve.
That is a different question from whether the index is *complete*, and the
difference had already cost something: the index listed six posts while nine
existed. The three that were missing included both posts from 2026-09-23, so a
reader arriving at the index could not see the two newest things written. Every
link in the table resolved perfectly the whole time.

This is the same shape as the defects these posts are about - a check that reads
a reduced form of its input. Link-checking reads the rows that are present and
reports that they are fine, which is true, and says nothing about the rows that
are absent.

What it asserts
---------------
1. Every `2026-*.md` post in the directory appears in the index. (catches a post
   published without a row)
2. Every post the index links to exists. (catches a renamed or removed post)
3. Rows are in non-increasing date order, newest first. (catches a row appended
   to the bottom because that was the easy place to put it)

Nothing to read is a failure, not a pass: a checkout that found no posts has not
verified an index.

    python3 check_writeups_index.py
    python3 check_writeups_index.py --self-test
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent

INDEX_NAME = "README.md"
POST_GLOB = "2026-*.md"

# A markdown link whose target is a dated post, e.g. [title](2026-09-24-x.md).
LINK_RE = re.compile(r"\((20\d\d-\d\d-\d\d-[^)\s]+\.md)\)")
# A table row beginning with its date cell: | 2026-09-24 | [..](..) | .. |
ROW_RE = re.compile(r"^\|\s*(20\d\d-\d\d-\d\d)\s*\|")

# A run that read almost nothing is not evidence that the index is complete.
MIN_POSTS = 5


def resolve_workspace() -> pathlib.Path:
    """The directory holding the sibling repositories, or this one if there is none.

    Same resolution as check_links.py and check_surfaces.py. Keeping them
    identical matters: if one looks in the wrong place it finds nothing, and
    finding nothing looks exactly like everything being fine.
    """
    for candidate in (HERE.parent, HERE):
        if (candidate / "portfolio").exists() or (candidate / "profile-readme").exists():
            return candidate
    return HERE


def compare(posts: set[str], linked: set[str], rows: list[tuple[str, str]]) -> tuple[list[str], list[str], list[str]]:
    """Return (unlisted, dangling, out_of_order). Pure, so the self-test can call it."""
    unlisted = sorted(posts - linked)
    dangling = sorted(linked - posts)

    out_of_order = []
    previous: str | None = None
    for date, target in rows:
        if previous is not None and date > previous:
            out_of_order.append(f"{target} is dated {date}, after {previous} on the row above")
        previous = date

    return unlisted, dangling, out_of_order


def read_index(index: pathlib.Path) -> tuple[set[str], list[tuple[str, str]]]:
    """Return (linked post filenames, [(row date, row target)] in file order)."""
    text = index.read_text(encoding="utf-8")
    linked = set(LINK_RE.findall(text))

    rows: list[tuple[str, str]] = []
    for line in text.split("\n"):
        match = ROW_RE.match(line)
        if not match:
            continue
        target = LINK_RE.search(line)
        if target:
            rows.append((match.group(1), target.group(1)))
    return linked, rows


def self_test() -> int:
    """Prove the check fires.

    The failure mode of this guard is silence, so it is fed the exact shape of the
    real defect - an index that links a strict subset of the posts on disk - and
    required to report it. It is also fed a complete index and required to stay
    quiet, because a check that always fails gets switched off.
    """
    good_posts = {"2026-09-20-a.md", "2026-09-21-b.md", "2026-09-24-c.md"}
    good_linked = set(good_posts)
    good_rows = [("2026-09-24", "2026-09-24-c.md"),
                 ("2026-09-21", "2026-09-21-b.md"),
                 ("2026-09-20", "2026-09-20-a.md")]

    cases = [
        ("complete index is clean", good_posts, good_linked, good_rows, False),
        ("a post missing from the index is caught",
         good_posts, {"2026-09-20-a.md", "2026-09-21-b.md"}, good_rows, True),
        ("an index row with no post is caught",
         good_posts, good_linked | {"2026-09-25-ghost.md"}, good_rows, True),
        ("a row out of date order is caught",
         good_posts, good_linked,
         [("2026-09-24", "2026-09-24-c.md"),
          ("2026-09-20", "2026-09-20-a.md"),
          ("2026-09-21", "2026-09-21-b.md")], True),
    ]

    failures = 0
    for label, posts, linked, rows, expect_detection in cases:
        unlisted, dangling, out_of_order = compare(posts, linked, rows)
        detected = bool(unlisted or dangling or out_of_order)
        ok = detected == expect_detection
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
        if not ok:
            failures += 1

    if failures:
        print(f"\n{int(failures)} self-test case(s) behaved wrongly. The guard is not "
              "guarding; do not trust a pass from it.")
        return 1
    print("\nself-test: the check fires on a partial index and stays quiet on a "
          "complete one")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true",
                        help="prove the check fires, using synthetic fixtures")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    workspace = resolve_workspace()
    writeups = workspace / "writeups"
    index = writeups / INDEX_NAME

    if not index.exists():
        print(f"FAIL  no index at {index}. Run from the workspace, or check out "
              "sushant-me/writeups beside this repository.")
        return 1

    posts = {p.name for p in writeups.glob(POST_GLOB)}
    if len(posts) < MIN_POSTS:
        print(f"FAIL  found {len(posts)} post(s), expected at least {MIN_POSTS}. A run "
              "that found nothing to check has not checked anything.")
        return 1

    linked, rows = read_index(index)
    unlisted, dangling, out_of_order = compare(posts, linked, rows)

    print(f"{len(posts)} posts on disk, {len(linked)} linked from {INDEX_NAME}\n")

    for name in unlisted:
        print(f"  UNLISTED     {name} exists but no row links to it")
    for name in dangling:
        print(f"  DANGLING     {name} is linked but does not exist")
    for note in out_of_order:
        print(f"  OUT OF ORDER {note}")

    bad = len(unlisted) + len(dangling) + len(out_of_order)
    if bad:
        print(f"\n{bad} problem(s) in the index. A post a reader cannot reach from "
              "the index is a post a reader cannot reach.")
        return 1

    print(f"PASS  every one of the {len(posts)} posts is in the index, every row "
          "points at a post, and the rows are newest-first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
