# Privacy design — what gets published, what doesn't

See [`README.md`](../README.md) for the project overview.

**Status: implemented and verified (2026-07-17).** Parts 1 and 2 below are live in `.gitignore` and `pipeline.py`; Part 3's synthetic sample is in `sample-data/`. Kept as a design write-up (not converted to changelog-only prose) because the reasoning here is meant to guide future decisions, not just record what happened once.

### Why this needed a real plan, not a one-time redaction

The repo is headed toward being public. Inspecting the raw scrape output (`data/raw/google-*.json`) directly — rather than just `reviews.db`, which is already a step removed from it — turned up more than expected: alongside each reviewer's real name, Google's actor also returns `reviewerUrl` (a direct link to that person's live Google Maps/Local Guide profile), `reviewerPhotoUrl` (their profile photo), their internal `reviewerId`, how many reviews they've written in total (`reviewerNumberOfReviews`), and whether Google has marked them a Local Guide (`isLocalGuide`). None of this is used anywhere downstream — `normalize()` only ever extracts `review_id`, `rating`, `text`, `date`, `owner_response`, and `author` — but it was all sitting in the raw files regardless.

One finding changed the shape of the fix: **`analysis.json` and `dashboard.html` were already anonymous by construction.** Checking `analyze()`'s output-building code confirmed every quote object (`worst_quotes`, `best_quotes`, `response_gap.examples`) is built as `{id, rating, date, quote}` — the reviewer's name is never included, not because of any privacy work, but simply because the analysis is theme/aggregate-based rather than per-reviewer. The actual exposure was entirely confined to two upstream files that exist for the pipeline's own bookkeeping, not for anyone to read directly: `reviews.db` (real name only, in the `author` column) and `data/raw/*.json` (name, plus the live profile links above).

That reframed the problem from "redact the data" to "stop publishing the two files that were never meant to be read directly, and stop collecting the sharpest fields going forward" — three parts, documented below.

### Part 1 — stop publishing `reviews.db` and `data/raw/`

**Implemented:** both added to `.gitignore`. They stay exactly as they are on disk — this is a publishing decision, not a data-collection one. Nothing about `scrape`, `normalize()`, or what a business owner running this locally can see changes at all. **Verified:** `git status` after the change shows both correctly untracked, with no commit ever having included them (this project's repo had zero commits at the time this was applied, so there was nothing to remove from history either).

**Motivation:** this is the highest-leverage fix available, because it costs nothing. The two files being excluded are the *only* ones that ever carried a reviewer's real name or profile link — the entire public-facing surface of the project (`pipeline.py`, `config.json`, `README.md`, `CONTRIBUTING.md`, `PRD.md`, and critically `analysis.json`/`dashboard.html`) was already anonymous before this change, once the finding above was confirmed. It's also a durable *policy*, not a one-time cleanup: because it's expressed as a `.gitignore` rule rather than a manual redaction step, it applies automatically to anyone who forks this tool, points `config.json` at their own business, and shares their fork — they get the same protection by default, without having to know to ask for it.

This does reverse part of an earlier decision in this project ([Changelog, item 6](../CHANGELOG.md#6-extensibility-setup--git-config-extraction-and-contributingmd)) to commit the scraped data as a named real example. That earlier decision was made before the raw-JSON field inspection above — at the time, "the data" was assumed to mean review text and ratings, not live links to reviewers' personal profiles. The dashboard and `analysis.json` still fully deliver on "share the data as a named, real example" — real business name, real numbers, real quotes — since neither ever depended on the two files being excluded here.

### Part 2 — stop collecting the sharpest fields at scrape time

**Implemented:** a `strip_reviewer_pii()` function in `pipeline.py`, called in `scrape()` right after items come back from `run_actor()` and before anything is saved to `data/raw/` — so the two fields never touch disk, not even briefly:

```python
PII_FIELDS_TO_STRIP = ("reviewerUrl", "reviewerPhotoUrl")

def strip_reviewer_pii(items):
    for it in items:
        for field in PII_FIELDS_TO_STRIP:
            it.pop(field, None)
    return items
```

**What's deliberately *not* stripped, and why:**

| Field | Kept or dropped | Reasoning |
|---|---|---|
| `reviewUrl` (the review itself) | **Kept** | Lets a business owner jump straight to a specific review to reply to it — real operational value, and it points at a review, not a person. |
| `reviewerUrl`, `reviewerPhotoUrl` | **Dropped** | The two fields that point directly at a specific person — their live profile page and their photo. These are what turn "a name in a spreadsheet" into "a clickable link to a real human being," and nothing downstream uses either. |
| `reviewerNumberOfReviews`, `isLocalGuide` | **Kept** | Unused today, but a plausible input to a future feature (e.g. weighting reviews by reviewer credibility) — and on their own, a review count or a badge don't point at a specific person the way a profile URL does. Stripping them would be foreclosing a real future option for a small, debatable privacy gain. |

**Motivation:** Part 1 already solves today's problem by keeping these files out of the public repo entirely — Part 2 is defense in depth, for two reasons. First, it reduces what's captured *even in your own local copy*, on the theory that data not collected can't later leak by accident (a future `.gitignore` mistake, a copied file, a debugging session that pastes raw JSON somewhere). Second, and more importantly for extensibility: if someone else's fork of this tool ever *does* choose to publish their own `reviews.db`/`data/raw/` (Part 1's exclusion is a default, not an enforced rule — nothing stops a fork from removing it from `.gitignore`), this change means their raw data is safer by default too, without them having to know to think about it.

**Verified:** added a `selfcheck` regression test asserting `strip_reviewer_pii()` drops exactly the two fields, leaves `reviewUrl`/`reviewerNumberOfReviews`/`isLocalGuide` untouched, and doesn't crash on items missing the fields entirely (Yelp's shape, which never had them). `python pipeline.py selfcheck` passes.

### Part 3 — a small, clearly-labeled synthetic sample

**Implemented:** `sample-data/synthetic-reviews-sample.json` — 20 fabricated rows in the same shape as a `reviews.db` row, for an invented business ("Example Bakery Co", "Faketown"), plus `sample-data/README.md` explaining what it is up front. Unmissable at every level: every author is literally `"Sample Reviewer N"` (or `"anonymous"` for the fake Yelp rows, matching this project's real handling of that source); every row carries an explicit `"synthetic": true` field that has no counterpart in the real schema; every `review_id` contains the literal substring `synthetic-`. The 20 rows deliberately span both fake sources, the full 1–5★ range, and review text touching most of `THEMES`' categories (pastry, coffee, service, wait, price, freshness, cleanliness, parking), so it doubles as a plausible illustration of what theme detection reacts to.

**Motivation:** this exists purely to offset the one real cost identified in Part 1 — a new contributor cloning the repo no longer gets 960 real reviews to immediately explore for free; their first hands-on look at real per-review data now requires running their own `scrape` (a few dollars, their own Apify account). A small synthetic sample gives back "something to look at and understand the schema from" at zero privacy cost, since nothing in it describes a real person or a real business. It's explicitly *not* a substitute for real data in testing `analyze`/`render` against — those should still be exercised against a real scrape (or the existing `selfcheck` fixtures) before trusting any change; the synthetic sample's only job is orientation, not verification. `sample-data/README.md` says this explicitly, so it doesn't get mistaken for a test fixture later.

### What this plan does not fix

Review **text** itself sometimes names a staff member by name (e.g. a complaint that names an employee) — no field-stripping or file-exclusion touches free text, and there's no reliable automated way to redact a name out of prose without a proper name-recognition pass, which this project doesn't have. This exposure already exists on Google/Yelp today (the review is already public there, under the reviewer's real name, naming the employee) — this plan doesn't make it worse, but doesn't make it better either. Worth knowing, not currently worth solving given it's not a new risk introduced by this project.

### ⚠️ Maintenance warning: re-running `analyze` locally can silently reintroduce the leak

This has happened twice already (once during the original scrub, once while verifying an unrelated `/code-review` fix) — worth a permanent, prominent note rather than relying on remembering it.

**The problem:** `config.json` on this machine correctly holds the *real* business's config (its real Yelp URL, its real Google search query) — that's necessary for the pipeline to actually work locally. But that means every time `python pipeline.py analyze` is run for real (e.g. to verify a code change against real data, or to pick up a new field added to the theme/action output shape), it regenerates `analysis.json` using the **full, unfiltered** citation-selection logic — the temporary business-name exclusion described earlier in this section is deliberately *not* part of the committed code, so a fresh `analyze` run has no memory of it. Roughly one in five raw reviews mentions the business by name, so a fresh run has real odds of selecting a leaking quote into one of the ~40 published citations, or into the `business` field itself (which `analyze()` always sets from the real local `config.json`).

**The rule going forward:** after *any* local `analyze` run whose output might get committed, before running `git add`:
1. Re-apply the same temporary citation-exclusion filter shown in [item 8](../CHANGELOG.md#8-full-identity-scrub-including-git-history) to `analyze()`'s theme and `response_gap` construction, re-run `analyze`, verify zero leaks (checking both `quote` text *and* `id` — a Yelp review's fallback ID can itself embed the business's URL slug), then revert the filter so it never lands in committed code.
2. Patch `analysis.json`'s `business` field directly (a plain string replace, not another `analyze` run) to the same honest "name withheld" label used throughout.
3. Run `render` and re-check `dashboard.html` for both the same leak pattern and the static `<title>` tag (which `render()` never touches).
4. Run the full `grep -ci` sweep across every file that would be committed — README, CONTRIBUTING, this journey doc, the dashboard, `analysis.json`, `pipeline.py`, `sample-data/` — before staging anything.

**Never `git add` output from a plain, unscrubbed `analyze`/`render` run on this repo.** If a change doesn't actually need fresh real output (e.g. a pure CSS/JS fix that doesn't touch `analysis.json`'s shape), skip regenerating it entirely rather than risk this.
