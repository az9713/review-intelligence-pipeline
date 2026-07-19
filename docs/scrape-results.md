# Scrape results — July 16, 2026 run

The live scrape has been run once. This section documents exactly what came back, including two data-quality findings discovered while inspecting the results (both since fixed — see below). `analyze` and `render` have since been run against the corrected data; current results are in [`README.md`'s Current status](../README.md#current-status).

## Run summary

| | Google Maps | Yelp |
|---|---|---|
| Actor run ID | `2TYxWeqfSLDvoF5qG` | `PRgClG1dRu6Y2iZXO` |
| Reviews returned | 460 | 500 *(hit the 500 cap — more history exists)* |
| Reported cost | $0.25 | $0.15 |
| Poll cycles observed | ~10 (`RUNNING` for ~100s+ before completion) | ~5 (`RUNNING` for ~50s+ before completion) |
| Raw output file | `data/raw/google-20260716-233221.json` | `data/raw/yelp-20260716-233325.json` |

**Total: 960 reviews stored, $0.40 spent** of the $5.00 Apify credit ($4.60 remaining). Both runs ended `SUCCEEDED` — no failures, no retries, no abort triggered.

## Rating distribution

| Stars | Google | Yelp |
|---|---|---|
| 1★ | 42 | 90 |
| 2★ | 18 | 60 |
| 3★ | 37 | 79 |
| 4★ | 87 | 127 |
| 5★ | 276 | 144 |
| **Average** | **4.17★** | **3.35★** |

The two sources disagree by nearly a full star. This is a real pattern worth investigating once themes are computed, not necessarily a data error — Google and Yelp attract different reviewer populations (Google reviews skew toward casual visitors leaving a quick rating after Maps navigation; Yelp reviewers are self-selected users of a review-focused app, who tend to write when they have something to complain about).

## Date coverage

Google reviews span **2014-05-21 to 2026-07-11** — a full 12-year history, distributed roughly:

| Year | Google reviews |
|---|---|
| 2014–2017 | 67 |
| 2018–2021 | 167 |
| 2022–2025 | 200 |
| 2026 (partial) | 26 |

Yelp reviews originally had **no usable date** in `reviews.db` on this run — see the finding below. That gap has since been fixed; Yelp's real date range is `2013-05-24` to `2026-05-20`, per [the verification table](#verification-against-the-real-data).

## Data quality findings — fixed 2026-07-16

**Status: all three findings below have been fixed and verified against the live database.** See [The fix — applied and verified](#the-fix--applied-and-verified) for the diffs and verification table. The rest of this section is preserved as-is for the historical record of what was found and why.

Inspecting `data/raw/yelp-20260716-233325.json` directly (bypassing `normalize()`) turned up the actual field names the Yelp actor returns, compared against what `normalize()` in `pipeline.py` was looking for:

| Field | Yelp actor's real key | Keys `normalize()` currently checks | Result |
|---|---|---|---|
| Review date | `reviewDate` (e.g. `"2026-05-20T09:57:17-07:00"`) | `publishedAtDate`, `review_date`, `date`, `created_at`, `localizedDate` | **Not matched.** All 500 Yelp rows have `review_date = NULL`. |
| Owner reply | `publicReply` (a nested object: `{"text": "...", "name": "...", "role": "OWNER", "created_at": "..."}`) | `responseFromOwnerText`, `owner_response`, `business_owner_replies`, `ownerResponse` | **Not matched.** All 500 Yelp rows have `owner_response = NULL`, even though real owner replies exist in the raw data (confirmed example: a signed thank-you reply to a named reviewer, timestamped `2026-05-20T13:31:30-07:00`). |
| Reviewer name | nested under `author` (e.g. `{"name": null, ...}` for this actor — often unpopulated) — but the *business* name is separately present at the top level as `name: "<the business's name>"` | `name`, `reviewer_name`, `user_name`, `author` (checked in this order) | **Matched the wrong field.** Because `name` is checked before `author`, every one of the 500 Yelp rows recorded `author` as the business itself instead of the actual reviewer. Confirmed: `SELECT COUNT(DISTINCT author) FROM reviews WHERE source='yelp'` returns exactly `1`. |

Google-side mapping was spot-checked and is correct: 459 distinct real reviewer names, real dates across the full 12-year range, and 245 real owner-response texts correctly captured.

**Why the existing safety net didn't catch this:** `normalize()` only drops a review as "unmappable" (and prints a `skipped N unmappable` warning) when the *review ID* or *rating* is missing — those two fields matched fine for every Yelp row, so all 500 rows were silently upserted with the date/reply/author fields simply wrong or null. Partial-field mapping failures like this one produce no warning at all under the current logic.

**Downstream impact this would have had if `analyze` had been run before the fix** (avoided — the fix landed first):
- The quarterly rating **trend** would have been built from Google's 460 dated reviews only — Yelp's 500 reviews would have been invisible to trend and deterioration-signal analysis, despite being over half the dataset.
- The **owner-response gap** metric would have reported 100% of Yelp's negative reviews as unanswered, even though real replies exist — this would likely have surfaced as a false "start responding to reviews" action.
- **Themes** would have been unaffected either way — they're computed from `text`, which was mapped correctly for both sources from the start.
- Any dashboard **quote attribution** for Yelp reviews would have shown the business's own name as the author of a Yelp customer's own words.

**Fix:** applied — see [The fix — applied and verified](#the-fix--applied-and-verified) below for the exact diffs, the regression test added, and the before/after verification against `reviews.db`.

## Deep dive: the Yelp `review_date` NULL problem

This was the most consequential of the three findings — a NULL date doesn't just leave one field blank, it makes the review invisible to every date-based computation `analyze()` performs (see [Downstream impact](#data-quality-findings--fixed-2026-07-16) above). It's documented separately here in full, code-traced detail. **Status: fixed and verified** — see [The fix](#the-fix--applied-and-verified) and [verification](#verification-against-the-real-data) below.

### How this was found

Not by any automated check — `pipeline.py`'s own commands (`scrape`, `analyze`, `selfcheck`) never flagged anything wrong. Both actor runs reported `SUCCEEDED`, the scrape script printed `upserted 500 reviews` with no `skipped` count, and `selfcheck` was already green before the live scrape ever ran. By every signal the pipeline itself produces, this run looked completely clean.

The bug surfaced from manual, ad hoc auditing of the database — done to compile statistics for this documentation, not as part of running the pipeline:

1. While pulling scrape-result numbers for the README, this query was run against the already-populated `reviews.db`:
   ```sql
   SELECT source, MIN(review_date), MAX(review_date), COUNT(*) FROM reviews GROUP BY source;
   ```
   Result: `('google', '2014-05-21', '2026-07-11', 460)` and **`('yelp', None, None, 500)`**. A `MIN`/`MAX` of `NULL` across 500 rows is only possible if every one of those rows has a `NULL` date — that's what made this stand out rather than reading as an unremarkable summary line.
2. A follow-up query confirmed the scope: `SELECT COUNT(*) FROM reviews WHERE review_date IS NULL` returned exactly **500** — the entire Yelp row count, meaning this wasn't a handful of malformed reviews but a systematic, total mapping failure for that one source.
3. To find *why*, the raw scrape output was read directly, bypassing `normalize()` entirely: `data/raw/yelp-20260716-233325.json` was loaded in a throwaway Python snippet, and the key list of a single item was printed in full. That's what revealed `reviewDate` as the actor's actual field name — a key never checked by `normalize()`'s candidate list.
4. The same technique — grouping and counting in SQL, then cross-checking against the raw JSON when a number looked wrong — surfaced the two related bugs the same way: `owner_response` came back entirely empty for the `yelp` source despite real replies being visible in the raw file, and `SELECT COUNT(DISTINCT author) FROM reviews WHERE source='yelp'` returned exactly **1**, where hundreds of distinct reviewer names were expected.

The common thread: every one of these queries reads data that was already scraped and stored — nothing here re-ran the pipeline, called Apify again, or spent additional credit. The audit is just SQL against `reviews.db` plus a manual glance at the JSON already sitting in `data/raw/`.

### Symptom

```sql
SELECT COUNT(*) FROM reviews WHERE source='yelp' AND review_date IS NULL;
-- 500   (every single Yelp row)

SELECT COUNT(*) FROM reviews WHERE source='google' AND review_date IS NULL;
-- 0     (every Google row has a real date)
```

### Root cause, traced line by line

The relevant code is `normalize()` and `parse_date()` in `pipeline.py`:

```python
# pipeline.py, line 103
date = parse_date(first(item, "publishedAtDate", "review_date", "date", "created_at", "localizedDate"))
```

```python
# pipeline.py, lines 73-78 — first() tries each key in order, returns the first non-empty match
def first(item, *keys):
    for k in keys:
        v = item.get(k)
        if v not in (None, ""):
            return v
    return None
```

```python
# pipeline.py, lines 81-93 — parse_date() extracts YYYY-MM-DD from whatever string it's given
def parse_date(v):
    if not v:
        return None
    v = str(v)
    m = re.search(r"\d{4}-\d{2}-\d{2}", v)
    if m:
        return m.group(0)
    ...
```

Trace what happens for one real Yelp item from `data/raw/yelp-20260716-233325.json`. Its actual keys (confirmed by direct inspection) include `reviewDate`, not any of the five candidates `first()` checks:

```
item.keys() includes: ..., 'reviewDate', 'reviewEncid', 'reviewUrl', ...
                       (no 'publishedAtDate', no 'review_date', no 'date',
                        no 'created_at', no 'localizedDate')
```

So `first(item, "publishedAtDate", "review_date", "date", "created_at", "localizedDate")` checks all five candidate keys against `item.get(k)`, finds every one of them absent (`item.get(k)` returns `None` for a missing key), and falls through to `return None` on line 78.

`parse_date(None)` is then called. Its very first line, `if not v: return None`, short-circuits immediately — `None` is falsy, so the function returns `None` without ever reaching the regex. The actual date string, `"2026-05-20T09:57:17-07:00"`, sitting right there in the item under the key `reviewDate`, is never looked at.

Back in `normalize()`, the resulting tuple's `date` field is `None`. This is not treated as an error: the only fields that cause a row to be dropped entirely are `review_id` and `rating` (line 108: `if rid is None or rating is None: return None`) — `date` being `None` is accepted as a normal, storable value. The row proceeds to `db()`'s `INSERT OR REPLACE`, and SQLite stores it as `NULL`. No exception, no warning, no printed message — the row looks completely normal in every log line the script produces (`upserted 500 reviews`, no `skipped` count).

### Why the offline selfcheck didn't catch this

`selfcheck()`'s synthetic test data (`pipeline.py`, lines 271-274) is:

```python
fake = [
    {"reviewId": "a", "stars": 5, "text": "...", "publishedAtDate": "2026-05-01T10:00:00Z", "name": "A"},
    {"reviewId": "b", "stars": 1, "text": "...", "publishedAtDate": "2026-06-01", "name": "B"},
    {"review_id": "c", "rating": "2", "review_text": "...", "date": "May 3, 2025", "reviewer_name": "C"},
]
rows = [r for r in (normalize("google", "url", f) for f in fake) if r]
```

Two problems, both invisible until real data arrived:

1. All three fake items use `publishedAtDate` or `date` — both of which are already in `first()`'s candidate list. The test data was written to match the code's expectations rather than to match a real actor's actual output, so it could never have exposed a missing candidate key.
2. All three fake items are normalized with `source="google"` — the `selfcheck()` function never calls `normalize("yelp", ...)` at all. Even if the fake data had used `reviewDate`, nothing in the offline test exercises the Yelp code path specifically (both sources share the same `normalize()` function and candidate lists, so this matters less than point 1, but it means the test suite has zero data-shape coverage of what Yelp's actor actually returns).

In short: the selfcheck validates the *upsert/idempotency/analysis* logic correctly (and did — it caught a real bug earlier in this build, the `selfcheck.db` file-lock issue), but it was never designed to validate *field-name mappings against real actor output* — that class of bug only surfaces by inspecting real scraped JSON, which is exactly how this was found.

### The fix — applied and verified

**Status: fixed.** All three mapping gaps (date, owner reply, author) were corrected in `normalize()` in the same pass, since they share the same root cause and were found together. Diffs:

```python
# date: added "reviewDate" as a candidate (first() tries candidates in order,
# so this is additive and doesn't touch Google's already-working publishedAtDate match)
date = parse_date(first(item, "publishedAtDate", "reviewDate", "review_date", "date", "created_at", "localizedDate"))

# owner reply: publicReply is a nested object ({"text": "...", "role": "OWNER", ...}),
# not a flat string, so it needs its own extraction step rather than a first() candidate
owner = first(item, "responseFromOwnerText", "owner_response", "business_owner_replies", "ownerResponse")
if owner is None and isinstance(item.get("publicReply"), dict):
    owner = item["publicReply"].get("text")

# author: made source-aware. Yelp's top-level "name" is the business, not the reviewer,
# and its nested author.name is empty for every item this actor returns in practice --
# "anonymous" is the honest value, not a bug, given what this actor exposes.
if source == "yelp":
    author = (item.get("author") or {}).get("name") or "anonymous"
else:
    author = first(item, "name", "reviewer_name", "user_name", "author") or "anonymous"
```

No change to `parse_date()` itself was needed: its regex `\d{4}-\d{2}-\d{2}` matches the leading `2026-05-20` inside Yelp's full timestamp string `"2026-05-20T09:57:17-07:00"` correctly (regex search, not full-string match, so the trailing `T09:57:17-07:00` timezone-offset portion is simply ignored) — the extraction logic already handled this exact format, it just never received the string to extract from.

A regression test was added to `selfcheck()` using this exact real shape (`reviewDate`, nested `author`, nested `publicReply`) — the precise gap that let the original bug through undetected, now permanently covered:

```python
yelp_fake = {
    "reviewId": "y1", "rating": 5, "text": "Great cakes",
    "reviewDate": "2026-05-20T09:57:17-07:00",
    "name": "Some Business",  # business name -- must NOT be used as author
    "author": {"name": None},
    "publicReply": {"text": "Thank you for your review!", "role": "OWNER"},
}
yrow = normalize("yelp", "url", yelp_fake)
assert yrow[3] == "anonymous"
assert yrow[6] == "2026-05-20"
assert yrow[7] == "Thank you for your review!"
```

`python pipeline.py selfcheck` passes with this test included.

### Verification against the real data

Applied without any additional Apify cost, exactly per the plan: the existing `data/raw/yelp-20260716-233325.json` was re-normalized with the fixed `normalize()` and the corrected rows were upserted into `reviews.db` — no re-scrape.

| Check | Before fix | After fix |
|---|---|---|
| Total rows in `reviews.db` | 960 | 960 *(unchanged — upsert replaced rows in place, no duplicates)* |
| Yelp rows with `review_date IS NULL` | 500 | **0** |
| Yelp `review_date` range | `NULL, NULL` | `2013-05-24` .. `2026-05-20` |
| Yelp rows with a real `owner_response` | 0 | **165** |
| Distinct Yelp `author` values | 1 (the business's own name — wrong) | 1 (`"anonymous"` — honest) |
| Google rows (untouched by this fix) | 460, dates 2014–2026, 459 distinct authors | unchanged — confirmed identical |

The `author` fix does **not** recover real reviewer names — this actor doesn't expose them (confirmed: `author.name` is `null` for all 500 raw items). What it fixes is *attribution correctness*: reviews are no longer misattributed to the business itself, which would have been actively misleading in a dashboard quote (e.g. "[business] says: 'the service here is terrible'"). "anonymous" is now an honest gap rather than a wrong answer presented with false confidence.

With Yelp dates now populated, combined month-by-month coverage for 2026 looks like:

```
2026-01: google 2, yelp 3      2026-05: google 2, yelp 1
2026-02: google 6, yelp 1      2026-06: google 3, yelp 0
2026-03: google 4, yelp 3      2026-07: google 4, yelp 0
2026-04: google 5, yelp 1
```

Both sources now contribute to trend and deterioration-signal analysis, and the response-gap metric reflects Yelp's real reply rate instead of reporting 100% unanswered. This table is from direct SQL queries against `reviews.db`, taken at the moment the fix was verified — see [Output structure: analysis.json](reference.md#output-structure-analysisjson) for what `analyze` produced from this same corrected data afterward.
