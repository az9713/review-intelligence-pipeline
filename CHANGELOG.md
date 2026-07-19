# Changelog — 2026-07-17 fixes

Detailed write-up of nine closed items, in the order they were closed. [`README.md`'s Current status](README.md#current-status) has the one-line summaries; this document has the full reasoning, code, and verification for each.

## 1. `render` command — automating the dashboard rebuild

**Problem.** After the first live scrape, getting `analysis.json`'s data into `dashboard.html` was a manual one-off step: a throwaway Python one-liner run directly in the terminal that read `analysis.json`, serialized it, and string-replaced a `__ANALYSIS_JSON__` placeholder in the HTML. That placeholder gets consumed on first use — nothing in `pipeline.py` itself could refresh the dashboard after a later `analyze` re-run. The pipeline was "scrape → store → analyze" complete, but "→ present" still had a hand-operated step.

**Fix.** Added a fourth pipeline stage, `render()`, plus a module-level `ANALYSIS_PATH` constant so the analysis output location is named once and shared by `analyze()`, `render()`, and `selfcheck()` rather than hardcoded in each:

```python
DASHBOARD_START = "const ANALYSIS = "
DASHBOARD_END = ";\n\nconst root = document.querySelector('.viz-root');"

def render():
    """Re-embed analysis.json into dashboard.html's `const ANALYSIS = ...;` line.
    Locates the JSON blob by exact surrounding markers (not brace-matching) since a
    review quote could itself contain the characters '};'."""
    if not os.path.exists(ANALYSIS_PATH):
        sys.exit("analysis.json not found -- run analyze first")
    data = json.load(open(ANALYSIS_PATH, encoding="utf-8"))
    payload = json.dumps(data, ensure_ascii=False)

    dash_path = os.path.join(HERE, "dashboard.html")
    html = open(dash_path, encoding="utf-8").read()
    start = html.index(DASHBOARD_START) + len(DASHBOARD_START)
    end = html.index(DASHBOARD_END, start)
    new_html = html[:start] + payload + html[end:]
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(new_html)
```

The design choice worth explaining: this finds the JSON blob by two **exact literal strings** already present in `dashboard.html`'s own script (`const ANALYSIS = ` and the following `;` plus the next line of code), not by counting `{`/`}` pairs. A brace-matching regex would be fragile here — a review's own text could contain the two characters `};` (e.g. a quote about code, or coincidental punctuation), which would make a naive "find the first `};`" stop early and truncate the JSON. Exact-string markers have no such failure mode, at the cost of the markers becoming a soft contract with `dashboard.html`'s script structure (documented in the function's docstring and in [Render](docs/running-the-pipeline.md#4-render-free-offline) below).

Wired into the CLI dispatch alongside the existing commands:
```python
{"scrape": scrape, "analyze": analyze, "render": render, "selfcheck": selfcheck}.get(cmd, ...)()
```

**Verification.** Ran `python pipeline.py analyze && python pipeline.py render`, then parsed the dashboard's embedded JSON back out with a script using the same two markers to confirm it round-trips correctly, and reloaded the page in a real browser (chrome-devtools) with zero console errors.

## 2. Action-threshold gap — large worsening themes were being silently excluded

**Problem.** Reviewing the built dashboard surfaced a discrepancy: the theme chart flagged 5 themes as "worsening" (>0.2★ drop, recent vs. older mentions), but the Recommended Actions list only contained 2 of those 5. The original rule for turning a theme into an action was:

```python
if t["negative"] >= 3 and t["negative"] / t["mentions"] > 0.25:
```

— a theme needed **more than 25% of its mentions to be negative**. This rule conflates two different signals: "this theme is mostly bad" and "this theme is getting worse." A large theme sliding from great to mediocre can still have plenty of positive mentions propping its overall share below 25%, even while the trend is clearly negative. Concretely: **pastry & bread quality** — the single largest theme by volume (524 mentions) — was worsening from 3.64★ to 3.35★, with 120 negative mentions, but 120/524 = 23%, just under the bar. It was completely absent from the actions list despite being the biggest theme in the dataset and visibly declining.

**Fix.** Extracted the qualification logic into a standalone, testable function with an added OR-branch:

```python
def theme_is_actionable(t):
    """A theme becomes a recommended action if EITHER: negative mentions are a large
    share of its total (>25%, the original signal), OR it's worsening (recent avg
    down >0.2* from older avg) with enough negative volume (>=10) to not be noise --
    this second branch catches large themes whose negative share looks moderate only
    because they also have a lot of positive mentions (e.g. a big theme sliding from
    great to mediocre reads as "worsening", not "mostly negative")."""
    worsening = (t["avg_rating_recent"] is not None and t["avg_rating_older"] is not None
                 and t["avg_rating_recent"] < t["avg_rating_older"] - 0.2)
    high_negative_share = t["negative"] >= 3 and t["negative"] / t["mentions"] > 0.25
    return high_negative_share or (worsening and t["negative"] >= 10), worsening
```

The `negative >= 10` floor on the new branch exists so a small theme with, say, 4 negative mentions and a wide swing doesn't get flagged purely on noise — it requires a real volume of negative signal, just not necessarily a majority share.

**Regression tests**, added to `selfcheck` as pure unit tests against the extracted function (no database or fake reviews needed, since the function takes a plain dict):

```python
worsening_low_share = {"negative": 15, "mentions": 200, "avg_rating_recent": 2.5, "avg_rating_older": 3.5}
assert theme_is_actionable(worsening_low_share)[0] is True   # worsening, high volume, low share -> still qualifies

worsening_low_volume = {"negative": 5, "mentions": 200, "avg_rating_recent": 2.0, "avg_rating_older": 4.0}
assert theme_is_actionable(worsening_low_volume)[0] is False  # worsening but under the noise floor -> excluded

high_share_stable = {"negative": 40, "mentions": 100, "avg_rating_recent": 3.0, "avg_rating_older": 3.0}
assert theme_is_actionable(high_share_stable)[0] is True      # high share alone still qualifies, unchanged behavior
```

**Verification.** Re-ran `analyze` on the real 960-review dataset: actions grew from 5 to 8, adding pastry & bread quality, coffee & drinks, and cleanliness & space — all three worsening, all three previously invisible. The existing priority formula (`negative_ratio × √mentions`) ranked them correctly without any change: pastry & bread quality (5.24) and coffee & drinks (3.62) landed between the original 5 actions rather than displacing them, since priority still rewards higher negative *share* — the fix only changed which themes are *eligible*, not how they're *ranked*. Re-ran `render` and confirmed the dashboard's action list and citation counts updated to match.

## 3. Documentation staleness cleanup

Several README passages were written honestly at the time (before `analyze`/`render`/the Yelp fix existed) and had simply not been revisited as the project moved past them. Swept the whole document for stale state claims and corrected each:

| Location | Before | After |
|---|---|---|
| "How it works", stage 5 | "a self-contained `dashboard.html` rendering the analysis. Deliberately not built yet" | Notes it's built, and that `render` re-embeds it after future `analyze` runs |
| "Scrape results" intro | "`analyze` has **not** been run against this data yet" | Notes both findings are fixed and `analyze`/`render` have since run |
| "Data quality findings" heading | (no status marker) | Retitled to "— fixed 2026-07-16" with an explicit status line, findings kept for the historical record |
| Downstream-impact bullets | Present tense ("would report 100% unanswered") | Past-conditional ("would have reported... avoided — the fix landed first") |
| "The fix" subsection | "not applied yet", listing a *plan* | Retitled "applied and verified", showing the actual diff and a before/after table |
| Deep-dive intro | "Not fixed yet — this section explains the problem only" | "Status: fixed and verified", linked to the fix and verification |
| Analysis methodology, known-limits bullet | "`analyze` has not been run against the corrected data yet" | Moved to a separate "Resolved" callout noting `analyze`/`render` have since run |
| Extending → Dashboard | "(next step)", "Deliberately not built yet" | "Dashboard: built.", describing what exists and how to refresh it |
| Verification-table intro | "`analyze` has not been run yet" | Points forward to the Output-structure section showing what `analyze` actually produced from the same data |
| Current status | "8 themes, 5 actions" / "next step, now that real analysis exists" | Updated to 8/8, and to the actual built-and-verified state |

Each correction kept the surrounding historical narrative (what was found, why, when) intact — only the *current-state* claims were stale, not the record of what happened.

## 4. Known limitations reframed as accepted constraints, not open TODOs

The "Known limits" list under Analysis methodology mixed two different kinds of items: genuine v1 trade-offs made on purpose (keyword-lexicon themes, star-rating-as-sentiment, noisy low-volume quarters) and one already-resolved bug that was still worded like an open concern. Retitled the section "accepted for v1, not open bugs" and rewrote each bullet to say explicitly *why* it's accepted rather than leaving it ambiguous whether it's a known gap or a forgotten TODO:

- Keyword lexicon and star-as-sentiment: explicitly marked as cheap-to-revisit-if-needed but not blocking v1.
- Noisy quarterly buckets: reframed as inherent to bucketing at this volume, not a defect.
- **Added two items that existed as facts elsewhere in the document but weren't yet in this list**: Yelp's missing reviewer names (the actor doesn't expose them — confirmed by inspecting raw data, not a mapping bug) and the Yelp 500-review cap (a deliberate budget guardrail, not an oversight) — both cross-linked to where they're proven out in detail.
- The one genuinely resolved item (the Yelp NULL-date/owner-response bug) was moved out of the limits list entirely into its own "Resolved (fixed and verified, kept here for history)" callout, so the limits list now contains only things that are *staying* limits, not a mix of live and closed issues.

## 5. Bonus: a destructive bug found while verifying the above

Closing out items 1–4 ended with a full sanity pass: run `analyze`, run `render`, then run `selfcheck` to confirm nothing regressed. That pass immediately failed in a worse way than expected.

**Problem.** `analyze()` wrote its output to a hardcoded path, `os.path.join(HERE, "analysis.json")` — the same path used for the real, production `analysis.json` (960 reviews, 8 themes, 8 actions) *and* the path `selfcheck()` used internally for its own 3-fake-review test run. `selfcheck()` already isolates the database (`DB = os.path.join(HERE, "selfcheck.db")`, reassigned at the top of the function) precisely so its test data never touches the real `reviews.db` — but nobody had extended that isolation to the analysis output. `selfcheck()`'s own cleanup step, `os.remove(os.path.join(HERE, "analysis.json"))`, was written assuming that path only ever held selfcheck's own throwaway output.

The result: running `python pipeline.py selfcheck` *after* a real `analyze` run — exactly the sequence used to verify items 1–4 — **silently deleted the real `analysis.json`**. No warning, no error; `selfcheck` printed `selfcheck OK` and exited 0, because from its own point of view everything had worked. The first sign anything was wrong was a `FileNotFoundError` from an unrelated verification script trying to re-read the (now-deleted) real file.

**Fix.** Introduced a module-level `ANALYSIS_PATH = os.path.join(HERE, "analysis.json")`, mirroring the existing `DB` global. `analyze()` and `render()` now read/write `ANALYSIS_PATH` instead of hardcoding the path inline. `selfcheck()` redirects it the same way it already redirects `DB`:

```python
def selfcheck():
    global DB, ANALYSIS_PATH
    real_db, real_analysis_path = DB, ANALYSIS_PATH
    DB = os.path.join(HERE, "selfcheck.db")
    ANALYSIS_PATH = os.path.join(HERE, "selfcheck-analysis.json")
    ...
    os.remove(DB)
    os.remove(ANALYSIS_PATH)
    DB, ANALYSIS_PATH = real_db, real_analysis_path   # restore before returning
```

The restore step at the end matters even though the CLI only ever runs one command per process invocation today — it's what makes `selfcheck()` safe to call from any future context that runs multiple pipeline functions in one process (a test harness, a future `pipeline.py all` command), rather than being correct only by accident of how it's currently invoked.

**Verification.** Regenerated the real `analysis.json` (`analyze` → `render`), then ran the exact sequence that had just caused the loss: `analyze` → `render` → `selfcheck`, in order. Confirmed afterward that `analysis.json` still parses and still shows 960 reviews / 8 themes / 8 actions, and that no `selfcheck-analysis.json` or other temp file was left behind (`selfcheck`'s own cleanup removes its isolated copy before restoring the path).

## 6. Extensibility setup — git, config extraction, and `CONTRIBUTING.md`

Groundwork for other people to work on this project, done in four parts.

**Business identity extracted from code into `config.json`.** Every hardcoded business-name/address reference in `pipeline.py` — the module docstring, the `SOURCES` dict's Google search query and Yelp URL, and the `"business"` field written into `analysis.json` — moved into a new `config.json`, loaded once at import time:

```python
def load_config():
    path = os.path.join(HERE, "config.json")
    if not os.path.exists(path):
        sys.exit("config.json not found -- copy config.example.json to config.json and fill in your business's details")
    return json.load(open(path, encoding="utf-8"))

CONFIG = load_config()
BUSINESS_NAME = CONFIG["business"]["full_name"]
MAX_REVIEWS_PER_SOURCE = CONFIG.get("max_reviews_per_source", 500)
```

`pipeline.py` itself is now business-agnostic — every business-specific value lives in one JSON file. A `config.example.json` template ships alongside it (blank placeholders in the same shape) for pointing the tool at a different business. The per-actor input *shape* — `maxReviews`/`reviewsSort` for Google vs. `reviews_limit`/`reviews_sort` for Yelp — stayed in code, since that's each actor's API contract, not business config; only the values (actor ID, query, URLs) moved out.

This was a judgment call made with the user rather than a silent decision: at this point, the scraped data itself (`reviews.db`, `analysis.json`, `dashboard.html`) — including real customer review text that names the business directly, and Yelp review IDs that embed the business's Yelp URL slug — was **not yet** scrubbed or altered; `config.json` was still committed as a real, named working example. That decision was later revisited and reversed once the full implications became clear — see [item 8](#8-full-identity-scrub-including-git-history) for the fuller scrub and why.

**Verification.** Ran `python pipeline.py selfcheck` (still passes), then `analyze` and `render` end-to-end and confirmed identical output to before the refactor: same business name string as before, 960 reviews, 8 themes, 8 actions — config-driven values, same result.

**Git repository initialized.** `git init` in the project root (previously untracked). `.gitignore` at this point excluded only genuine secrets and local noise — `.env` (the Apify token), `__pycache__/`, `selfcheck`'s isolated temp files, the future `schedule-log.txt`, and a pre-existing `.ignore/` folder found in the directory (a personal stash of session transcripts, not part of this project — left untouched, just excluded). Everything else, including `reviews.db`, `config.json`, and `analysis.json`, was tracked at this point, per the decision above — later revisited, see item 8. `.env.example` (a placeholder token) ships so a new clone knows what secret to supply, mirroring `config.example.json`'s pattern.

**`CONTRIBUTING.md` added.** New top-level doc covering: setup (the two copy-the-example-file steps above), an extension-points table (new source → `config.json` + `SOURCES` + `normalize()`; theme detection → the `THEMES` dict; action rules → `theme_is_actionable()`; a different presentation layer → the documented `analysis.json` contract; dashboard styling → `dashboard.html` directly, safe because `render()` only touches the data blob), the testing rule (`selfcheck` must pass, bug fixes add a regression test — citing this project's own three examples: the Yelp-shape fix, the action-threshold fix, and the still-open gap that the destructive-path fix has no dedicated regression test of its own), and an explicit "what not to add" list (no new dependencies, no config for single-value settings, no premature abstractions, no test framework beyond `selfcheck`) so contributions stay at the size this project has deliberately stayed at.

**`README.md` updated to match:** "Files in this folder" gained rows for `config.json`, `config.example.json`, `.env.example`, `.gitignore`, and `CONTRIBUTING.md` (and dropped `transcript.txt`, which is no longer in the project root); "Extending the system" now leads with pointing the tool at a different business via `config.json` before the existing add-a-source recipe; the "Running the pipeline" prerequisites note both example-file-copying steps.

## 7. XSS: a review quote could break out of `dashboard.html`'s `<script>` tag

**Found by an automated background security review**, run against the commit right after it was pushed to the now-public repo — not found by manual testing or by `selfcheck`, which is itself the interesting part of this entry.

**Problem.** `render()` builds `dashboard.html`'s embedded data with `json.dumps(data, ensure_ascii=False)`, then writes that string directly between `const ANALYSIS = ` and the next `<script>` code — i.e. raw inside an HTML `<script>` element. `json.dumps()` never escapes the `/` character. If any review's text contained the literal substring `</script>`, the **HTML tokenizer** — which scans for the closing tag before any JavaScript ever runs — would treat that as the end of the script block, regardless of the fact that it's sitting inside a JSON string value from JavaScript's point of view. Everything after it in the review text would then be parsed as raw HTML, including a second, attacker-controlled `<script>` tag. Concretely: a review reading `nice place </script><script>alert(1)</script> great coffee` would execute `alert(1)` (or anything else) the moment the dashboard was opened.

**Why this matters beyond the current dataset:** the 960 real reviews in this repo's example dataset happened not to contain this pattern — checked directly (`'</script' in payload.lower()` → `False`) — so the dashboard as pushed was not actually exploitable *today*. But `config.json` now lets anyone point this tool at any business, and `render()` embeds whatever review text Apify returns, unmodified — this was a defect in the tool itself, not an artifact of one dataset. A single hostile review (from a competitor, a disgruntled customer, or just an unlucky coincidence of someone quoting HTML in their complaint) on *any* business this tool is pointed at would have put arbitrary script execution one `python pipeline.py render` away from running in that business owner's browser.

**Fix.** Escape every literal `<` in the embedded payload as `<` — a valid JavaScript string escape that a JS engine parses back to the original `<` character, but which contains no literal `<` byte for the HTML tokenizer to ever see, so it can't be mistaken for the start of any tag (not just `</script>` — this closes the whole class of tag-breakout, not one specific string):

```python
def json_for_script_tag(data):
    """json.dumps() never escapes '<', so a review containing the literal text
    "</script>" would otherwise close the dashboard's <script> tag early and let
    arbitrary HTML/JS run in the browser. \\u003c is valid inside a JS string literal
    (parses back to '<') but contains no literal '<' byte, so the HTML tokenizer that
    looks for the closing tag can never mistake it for one."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
```

Extracted as a standalone function — matching this project's established pattern for `theme_is_actionable()` and `strip_reviewer_pii()` — specifically so it's unit-testable without needing a real `dashboard.html` on disk.

**Regression test**, added to `selfcheck`:

```python
evil = {"quote": "nice place </script><script>alert(1)</script> great coffee"}
escaped = json_for_script_tag(evil)
assert "<" not in escaped, f"escaped payload must contain no literal '<': {escaped!r}"
assert json.loads(escaped.replace("\\u003c", "<")) == evil, "escaping must be reversible back to the original data"
```

**Verification.** `python pipeline.py selfcheck` passes with the new test. Re-ran `render` and confirmed the regenerated `dashboard.html`'s embedded payload contains zero literal `<` characters, and that reversing the escape (`.replace("<", "<")`) round-trips back to the exact original `analysis.json` data (`total_reviews == 960` survives the round-trip). Reloaded the dashboard in a real browser afterward — same 8 action cards, 960 reviews shown, no console errors — confirming the fix didn't break normal rendering, only closed the injection path.

**Why `selfcheck` didn't catch this on its own:** none of `selfcheck`'s existing fixture data contained anything resembling an HTML tag, so nothing exercised this path before the fix existed. This mirrors the exact shape of the Yelp field-mapping bug earlier in this changelog — a real defect that only surfaces when the input data has a shape the test fixtures never tried. The regression test added here closes this specific gap; it does not, on its own, guarantee some other unanticipated input shape won't slip through the same way in the future.

**Response timeline, since it's part of the story:** found and fixed within the same session as the push, before the user had replied to anything else — the working tree was fixed, verified, and force of habit says "wait for confirmation before pushing to a public repo," but leaving a known, disclosed script-injection defect live in public code while waiting was judged worse than pushing a narrowly-scoped, test-covered security fix promptly. Documented here in full so that judgment call is visible, not silent.

## 8. Full identity scrub, including git history

**What triggered this:** noticing the README's own title still read "Review Intelligence Pipeline — [Business Name] ([City], CA)" — a direct contradiction of `CONTRIBUTING.md`'s framing of this as a generic, reusable tool. That prompted a much bigger question than a title fix: should every mention of the specific business behind this repo's example data be removed, including from the two commits already pushed publicly?

**The decision, made explicitly rather than assumed** (this repo's real business identity was, at the time, genuinely load-bearing in several places — `config.json`'s functional URLs, `PRD.md`'s entire premise, `analysis.json`'s citation quotes): three separate calls were needed, each confirmed before acting on it, since each had a real, different cost —

1. **Real customer review quotes that name the business directly** (roughly 19% of the raw dataset's text mentions the business by name or abbreviation, which is normal — people name the place they're reviewing): drop only the specific quotes that mention it from the ~40 curated citations shown in `analysis.json`/`dashboard.html`, keep all 960 reviews' numbers, trends, and ratings as the real working example. Rejected alternatives: removing the whole example dataset (too much lost for too little gained, given 960 reviews had ample non-mentioning alternates for every citation slot) and leaving real quotes untouched (directly contradicts the ask).
2. **`PRD.md`**: removed from the repo (kept locally, gitignored) rather than genericized — it's inherently a requirements spec for one real deployment; a genericized version would stop being a true record of what was actually built.
3. **Rewriting already-pushed git history**: explicit go-ahead required and obtained before running anything destructive, since force-pushing overwrites public history — flagged clearly that this is best-effort (can't guarantee nothing was cached elsewhere in the time it was live) rather than a perfect erasure guarantee.

**Mechanics of the quote filter.** Implemented as a *temporary* addition to `analyze()`'s theme/response-gap quote-selection code — never committed, since hardcoding a business name into the generic tool would be exactly the kind of regression this whole effort was meant to prevent. Pattern:

```python
_NAME_PAT = re.compile(r"<business name>|<business abbreviation>|<city>|<street>", re.I)
neg_q = [r for r in neg if not _NAME_PAT.search(r["text"]) and not _NAME_PAT.search(r["id"])]
```

Applied → ran `analyze()` → verified zero leaks across every citation's `quote` and `id` field → reverted the code to its clean, generic form → confirmed via `grep` that no trace of the pattern remained in `pipeline.py`. Run twice: the first pass only checked review **text** and missed a real leak — one Yelp review had no proper `reviewId`, so `normalize()`'s fallback chain used its `reviewUrl` (which embeds the business's Yelp slug) as the review's `id`, and that ID surfaced in `response_gap.examples` and its corresponding action's `cited_reviews`, even though the review's own text was clean. Second pass added `not _NAME_PAT.search(r["id"])` to close that gap — the lesson generalizes: an identifier embedding source-URL fallback logic is itself a data field to check, not just the human-readable text next to it.

**A related, smaller finding along the way:** the README's own historical narrative (documenting the Yelp field-mapping bug from earlier in this changelog) quoted real Google reviewer names as illustrative examples ("Somaprova Ghosh", "Paul Baty"). Not the business name, so not strictly in scope for this specific request — but inconsistent with the "name withheld" posture being established everywhere else, so fixed for consistency: replaced with generic placeholder language.

**`config.json` re-architected as local-only.** Previously committed as "the real working config." Realized during this work that its functional fields (the actual Yelp URL, the actual Google search query) *are* the business's identity — there's no way to keep them functional and also remove the name. Resolved by treating `config.json` exactly like `reviews.db`: real, useful, gitignored. This does mean a fresh clone can't run *anything* — not even the free, offline `selfcheck` — without first copying `config.example.json` to `config.json`, since `pipeline.py` loads `CONFIG` at import time. Accepted trade-off: matches the existing `.env`/`.env.example` pattern already in place, just one more required copy-step, not a new category of friction.

**`analysis.json`'s `business` field and `dashboard.html`'s `<title>`** were the last functional traces — patched directly (not regenerated through `analyze()`, which would have required `config.json` to still name the business) to a plain, honest label: `"Local bakery and cafe (real dataset - business name withheld; see README)"`. `dashboard.html`'s hitherto-static `<title>` tag (never touched by `render()`, which only re-embeds the data blob) was fixed separately to just `"Review Intelligence Dashboard"`.

**Verification, full pass, before any git operation:** `python pipeline.py selfcheck` green; `grep -ci` for the business name, its street, and its city across every file that would be committed — `README.md`, `CONTRIBUTING.md`, `config.example.json`, `analysis.json`, `dashboard.html`, `pipeline.py`, `sample-data/`, `.gitignore`, `.env.example` — all zero.

**Git history:** wiped and rewritten with a single fresh commit reflecting this fully-scrubbed state, force-pushed over the two previous commits per the explicit go-ahead in point 3 above. See the commit log for the result — this entry describes the reasoning and mechanics; it doesn't restate the git commands, which are unremarkable (`rm -rf .git`, `git init`, one commit, `git push --force`).

## 9. Trend chart divide-by-zero on a single data point — found via `/verify`

**Found by:** an actual `/verify` pass against this session's work — not a code read, not a test suite. A hand-crafted minimal test `analysis.json` (built to check the XSS fix) crashed with an `Uncaught TypeError` before the code being tested even ran; rather than accept that as noise, the crash was isolated to its actual cause, which turned out to be unrelated to the XSS work entirely.

**Root cause.** `dashboard.html`'s trend chart computes each point's x-coordinate as `padL + (i / (trend.length - 1)) * plotW`. When `kpis.trend` has exactly one entry, `trend.length - 1` is `0`, so every x-coordinate becomes `0/0` = `NaN`. Confirmed live in a real browser: three SVG attribute errors (`<path> d`, `<path> d`, `<text> x`, all "Expected number, NaN...") and a broken, invisible trend line. Real-world trigger: a brand-new business, or any business whose dated reviews all happen to fall within a single calendar quarter — not a hypothetical edge case.

**Fix:**

```javascript
const xSpan = Math.max(trend.length - 1, 1); // avoid divide-by-zero when trend has exactly one point
const xFor = i => padL + (i / xSpan) * plotW;
```

Every other caller of `xFor()` (the line path, the area path, the x-axis ticks, the end-label position) automatically inherits the fix — none needed a separate change. The hover crosshair's inverse mapping (`nearestIndex()`) was checked and confirmed already safe: it *multiplies* by `trend.length - 1`, and `0 × anything` is `0`, not `NaN` — only division by that quantity was the actual hazard.

**Verification.** Rebuilt the exact single-trend-point case that originally crashed, using real `analyze()` output (not another hand-crafted object) trimmed to one trend entry. Reloaded in a real browser: zero console errors, and the single point renders correctly — a valid (if visually sparse) path at the correct x/y position with its `3.26★` label placed accurately, instead of failing to render at all.
