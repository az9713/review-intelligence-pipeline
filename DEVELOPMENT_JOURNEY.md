# Development journey

The story of how this project was built, in order, from a YouTube video to a live, verified, public dashboard. [`CHANGELOG.md`](CHANGELOG.md#changelog--2026-07-17-fixes) is the itemized technical reference for each fix; this document is the narrative — what happened, why, in what order, and what was learned along the way.

**A note on what's named here.** This project's example dataset is real: 960 real reviews for a real local bakery and cafe, scraped from Google Maps and Yelp. That business's name, address, and listing URLs are intentionally withheld from this entire repository — see [Privacy design](docs/privacy-design.md) for the full reasoning. This document follows the same rule. Every number, date, cost, and technical decision below is real and unaltered; only the business's identity is not.

---

## Contents

1. [Origin](#1-origin)
2. [Requirements and architecture](#2-requirements-and-architecture)
3. [Building the pipeline](#3-building-the-pipeline)
4. [The first live scrape](#4-the-first-live-scrape)
5. [The Yelp data quality bug](#5-the-yelp-data-quality-bug)
6. [Building the dashboard](#6-building-the-dashboard)
7. [Two more bugs, found by looking closely](#7-two-more-bugs-found-by-looking-closely)
8. [Making the tool reusable](#8-making-the-tool-reusable)
9. [The privacy redesign](#9-the-privacy-redesign)
10. [Going public](#10-going-public)
11. [The XSS vulnerability](#11-the-xss-vulnerability)
12. [The full identity scrub](#12-the-full-identity-scrub)
13. [Live on GitHub Pages](#13-live-on-github-pages)
14. [The /verify pass](#14-the-verify-pass)
15. [The /code-review pass](#15-the-code-review-pass)
16. [The /security-review pass](#16-the-security-review-pass)
17. [Turning the review into a reusable skill](#17-turning-the-review-into-a-reusable-skill)
18. [What the journey shows](#18-what-the-journey-shows)

---

## 1. Origin

The project started from a YouTube video, ["Claude Code + MCP = 24/7 AI Business Intelligence Agent"](https://www.youtube.com/watch?v=rvApCZNxUXU&t=426s) by Mansel Scheffel — a walkthrough of turning scattered customer reviews into a decision-making tool for a business owner. The video's own worked example was a different restaurant entirely (a London restaurant used as an illustration partway through); it wasn't the source of this project's data, just the inspiration for the pipeline shape.

The video's pitch, in short: most businesses sit on a goldmine of review data and do nothing with it beyond an occasional "thanks for the review" reply. The fix — find every place a business is reviewed, scrape it, store it, analyze it for evidence (not vibes), and present it as something a business owner can act on. The video also framed this as a consulting lead magnet: scrape a prospect's reviews, show them their pain points, pitch the fix.

That five-stage shape — **discover → scrape → store → analyze → present** — became this project's architecture from the start, along with the video's core discipline: back every insight with a citation to a real review, never assert a pattern without evidence.

## 2. Requirements and architecture

Before writing code, a PRD (`PRD.md`, kept local to this repo, not published — see section 9) captured the actual requirements for building this against one real business: which review sources to use, a budget ceiling, and explicit acceptance criteria.

**Source decisions**, made deliberately rather than scraping everything available:
- **Google Maps** and **Yelp** — v1, chosen as the two platforms carrying the most review volume for a local bakery/cafe.
- **TripAdvisor** — deferred; the business had a listing, but TripAdvisor skews toward tourist traffic, marginal value for this business type unless Google+Yelp volume proved thin (it didn't).
- **Trustpilot** — excluded entirely. Its pages are per-brand, not per-location, so its reviews couldn't be attributed to one specific store.

**Budget guardrails**, since this pipeline spends real money via a paid scraping service: cap each source at 500 of the newest reviews, hard-abort if cumulative cost ever exceeds $2, against a $5 total account credit.

**The non-negotiable design principle**, carried through everything that followed: every insight the pipeline produces must be evidence-based — a computation plus a citation to specific review IDs, never an unsupported claim.

## 3. Building the pipeline

`pipeline.py` was built as a single, dependency-free Python script (standard library only) with four commands, added in this order over the course of the project: `scrape`, `analyze`, `render`, `selfcheck`.

**Scraping** uses [Apify](https://apify.com), a marketplace of pre-built web scrapers ("actors"), accessed via its plain REST API rather than Apify's own MCP connector (the approach the source video used) — chosen specifically so the pipeline could eventually run on an unattended schedule without an AI in the loop. Two actors were selected by usage volume, rating, and price: a Google Maps reviews actor (47,000+ users, 4.8★, 137M runs) and a Yelp reviews actor (99.9% success rate over 549K recent runs).

Starting an actor run and finishing one are two separate events — Apify's API is asynchronous by design, since a 500-review scrape can take minutes and an HTTP request isn't built to stay open that long. The pipeline polls every 10 seconds (up to 15 minutes) rather than using Apify's synchronous endpoint (which caps its wait at 60 seconds — far short of a real scrape) or webhooks (which need a public callback URL a local script doesn't have).

**Storage** is a single SQLite table. The two actors name identical concepts differently — `stars` vs. `rating`, `publishedAtDate` vs. `date` — so `normalize()` tries an ordered list of candidate field names per column rather than assuming one schema. Review IDs are source-prefixed (`google:...` / `yelp:...`) and every write is an upsert, so re-running a scrape never creates duplicates.

**Analysis** is pure local computation — no AI, no network call, fully deterministic given the database contents: rating KPIs, a quarterly trend, keyword-matched themes (a lexicon covering eight categories — pastry/bread, coffee, service, wait time, price, freshness, cleanliness, parking), star-rating-as-sentiment, an owner-response gap, and a ranked action list. Every theme and action carries citations — real review IDs, ratings, dates, and quoted text — satisfying the PRD's evidence-based principle by construction, not by convention.

**`selfcheck`** was built alongside the pipeline from day one: a fast, free, offline regression suite using small fabricated fixtures, meant to be run before trusting any change. It would go on to catch — and fail to catch, instructively — several real bugs over the course of the project (sections 5, 7, 11, 14).

## 4. The first live scrape

With the pipeline built and `selfcheck` passing, the first live run went ahead: 460 reviews from Google Maps, 500 from Yelp (hitting the cap — more history existed), 960 total, for **$0.40** of the $5.00 budget. Google's reviews averaged 4.17★; Yelp's averaged 3.35★ — a near-full-star gap between the two platforms, a real pattern rather than a data error (the two platforms attract different reviewer populations). The dataset spanned twelve years, back to 2013.

## 5. The Yelp data quality bug

The first and most significant bug wasn't caught by any test — it was found by manually auditing the freshly-scraped database while writing documentation about the results. A summary query —

```sql
SELECT source, MIN(review_date), MAX(review_date), COUNT(*) FROM reviews GROUP BY source;
```

— returned real dates for Google, and `NULL, NULL` for Yelp. Every one of Yelp's 500 reviews had a null date. A follow-up count confirmed the scope (exactly 500, not a handful), and reading the raw scraped JSON directly revealed why: Yelp's actor returned the date under the key `reviewDate`, a field `normalize()`'s candidate list never checked. Because only a missing review ID or rating caused a row to be dropped and flagged, this failure was completely silent — the scrape reported success, `selfcheck` was green, and the database quietly held 500 reviews the pipeline could never place on a timeline.

The same technique — query, notice something that shouldn't be possible, cross-check the raw JSON — surfaced two more mapping failures in the same pass: owner replies used a nested `publicReply` object the pipeline never looked inside (165 real replies were sitting unread), and Yelp's `name` field held the *business's own name*, not the reviewer's, because it was checked before the correct (but usually empty) `author` field — meaning every single Yelp review had been misattributed to the business itself.

All three were fixed together, and — critically — a regression test was added to `selfcheck` using Yelp's *exact* real field shape, since the original bug existed specifically because the test fixtures never matched real actor output. Verified against the live database: Yelp's dates went from `NULL` to a real `2013–2026` range, 165 real replies appeared, and misattribution was replaced with an honest `"anonymous"` (this actor, it turned out, doesn't expose Yelp reviewer names at all — a genuine limitation of the data source, not a bug to fix further).

## 6. Building the dashboard

With real, clean data in hand, the presentation layer came next: a single self-contained `dashboard.html` — no server, no build step, no external requests, opens by double-click. Built using a structured data-visualization methodology (form before color, a validated colorblind-safe palette, mandatory table-view twins for every chart, dark mode as a first-class target, not an afterthought): a KPI row, an interactive rating-trend line chart, a diverging bar chart of theme sentiment, and a ranked action list with expandable citations.

Verification happened in a real browser (via Chrome DevTools automation), not just by reading the code — which caught a real bug immediately: the dashboard's CSS defined its color variables scoped to an inner `.viz-root` element, but `<body>`'s own color rules referenced those same variables from *outside* that scope. CSS custom properties don't inherit upward to ancestors, so `body`'s reference silently failed and fell back to black — meaning most text was rendering black-on-black in dark mode, regardless of theme. Fixed by moving the variable definitions up to `:root`, where both `body` and `.viz-root` could see them.

## 7. Two more bugs, found by looking closely

**A destructive test.** Closing out a batch of fixes ended with a full sanity pass: `analyze` → `render` → `selfcheck`, in sequence — the same order used to verify everything. That pass destroyed the real, 960-review `analysis.json`. `analyze()` and `selfcheck()`'s own internal test run shared the same hardcoded output path; `selfcheck()` deletes that file as cleanup, on the assumption it only ever held its own throwaway data. Running `selfcheck` *after* a real `analyze` silently deleted the real file — `selfcheck` printed `selfcheck OK` and exited cleanly, because from its own point of view, nothing had gone wrong. Fixed by giving the analysis output path the same isolation `selfcheck` already gave its test database, and verified by deliberately re-running the exact sequence that had just caused the loss.

**A conflated signal.** Reviewing the built dashboard surfaced a discrepancy: the theme chart flagged five themes as "worsening" (a real ratings decline over time), but the ranked-actions list contained only two of them. The rule for turning a theme into an action required negative mentions to exceed 25% of that theme's total — which conflates "mostly negative" with "getting worse." The single largest theme in the dataset, over 500 mentions, was worsening from roughly 3.6★ to 3.4★ but sat at 23% negative — just under the bar, and completely invisible to the ranked list despite being the biggest, most clearly declining theme in the data. Fixed by adding a second qualifying condition (worsening trend, with a minimum volume floor to filter out noise), verified with three targeted unit tests, and confirmed against the real dataset: the ranked actions grew from five to eight, correctly ranked by the existing priority formula without any change to how ranking itself worked.

## 8. Making the tool reusable

Up to this point, the business's identity was hardcoded throughout `pipeline.py` — its name, address, and the actual scraper URLs baked directly into the source. Turning this into something reusable meant extracting all of it into a `config.json` file, loaded once at startup, with a blank `config.example.json` template for pointing the tool at any other business. `pipeline.py` itself became fully business-agnostic — nothing in the code names any specific business.

A `git` repository was initialized (the project had lived un-versioned on disk up to this point), and `CONTRIBUTING.md` was written: setup steps, an explicit table of the codebase's extension points (adding a new review source, customizing theme detection, changing which themes become actions, building an alternative presentation layer), the one testing rule (`selfcheck` must pass; any bug fix adds a regression test to it — citing the project's own history from sections 5 and 7 as precedent), and an explicit "what not to add" list to keep future contributions at the size the project had deliberately stayed at.

## 9. The privacy redesign

The original plan was to publish the scraped data as-is — a real, named example alongside the reusable tool. Preparing for that surfaced a problem: the *raw* scraped data from Google's actor carried far more than review text. Alongside each reviewer's real name, it included a direct link to that person's live Google Maps profile, their profile photo, and an internal reviewer ID — none of which the pipeline ever used, all of which had been captured and stored anyway.

One finding reframed the whole problem: `analysis.json` and the dashboard were *already* anonymous, purely as a side effect of being aggregate- and theme-based rather than per-reviewer. Checking the output-building code confirmed no reviewer name ever appeared in any citation object. The actual exposure was confined to two files that existed purely for the pipeline's own bookkeeping — the SQLite database and the raw scraped JSON — never meant to be read directly by anyone.

The fix, in three parts: stop publishing the database and raw JSON entirely (kept local only, gitignored — the dashboard and analysis output already delivered on "a real, named example" without them); strip the two fields that pointed directly at a specific person (the profile link and photo) at scrape time, before they ever touched disk, going forward for any future scrape of any business; and add a small, unmistakably-labeled *synthetic* (fabricated) sample dataset, so a new contributor could see the database's shape without needing to spend money on a real scrape first.

## 10. Going public

With the tool genericized and the privacy design in place, the repository was pushed to GitHub as a public repo — an initial commit, then a remote created via the GitHub CLI, then the push itself. This is the point where "a project on one machine" became "a project anyone could find."

## 11. The XSS vulnerability

Within the same session as that first public push, an automated background security review flagged a real, unnoticed defect: the dashboard embeds review text directly inside an HTML `<script>` tag using a JSON serializer that never escapes the `/` character. A review containing the literal text `</script>` would close that tag early, and everything after it in the review would be parsed as raw HTML — including a second, attacker-controlled script tag. The real dataset didn't happen to contain that pattern, so the live dashboard hadn't actually been exploitable — but `config.json` now let anyone point this tool at any business, and nothing stopped a future review, anywhere, from containing it.

The decision to fix and re-push immediately, before any further conversation, was deliberate and is worth naming: leaving a disclosed, known injection vulnerability live in public code while waiting felt worse than shipping a narrow, fully-tested fix promptly. The fix escapes every `<` character as a JavaScript unicode escape — closing the entire class of tag-breakout, not just the one specific string — with a regression test added using the actual attack payload.

## 12. The full identity scrub

Some time later, a small inconsistency surfaced: the README's own title still named the business directly, directly contradicting `CONTRIBUTING.md`'s framing of the project as a generic, reusable tool. That question — should every mention of the business be removed, including from git history already pushed publicly — turned out to be much larger than a one-line title fix.

**Three separate decisions were needed**, each made explicitly rather than assumed, because each had a real cost:

1. **Real review quotes that name the business.** Roughly one in five of the raw reviews mentioned the business by name or abbreviation — unremarkable, since customers naturally name the place they're reviewing. The decision: drop only the specific quotes that mention it from the roughly forty curated citations the dashboard actually shows, and keep all 960 reviews' real numbers, trends, and ratings as the working example. A temporary filter (never committed — hardcoding a business name into the generic tool would have been exactly the regression this effort existed to prevent) excluded matching reviews from citation selection, `analyze()` was re-run, the filter reverted, and the result verified clean. The first pass checked review text only and missed a real leak: one Yelp review had no proper ID, so the pipeline's own fallback logic had used that review's URL — which embedded the business's Yelp address — as its identifier. A second pass closed that gap.
2. **The original requirements document.** Removed from the published repo entirely (kept locally) — it's inherently a specification for one real business; a genericized version would stop being a true record of what was actually built.
3. **Rewriting already-public git history.** The most consequential decision, requiring an explicit go-ahead before running anything: force-pushing overwrites public history, and while the two prior commits become unreachable, there's no guarantee something wasn't already cached elsewhere in the time they were live. Confirmed and accepted as best-effort, not a perfect erasure guarantee.

`config.json` itself needed rearchitecting: its functional fields — the actual Yelp URL, the actual Google search query — *are* the business's identity; there's no way to keep them working and also remove the name. It was moved to the same local-only, gitignored treatment as the database, meaning a fresh clone now requires one explicit setup step (copying a blank template) before anything runs at all, including the free offline self-test.

A verification pass swept every file that would be published — the README, the contributing guide, the example config, the analysis output, the dashboard, the pipeline script itself, the sample data — confirming zero remaining mentions before anything was pushed. One near-miss during that very pass is worth recording honestly: while documenting the fix, a code example illustrating the exclusion pattern was initially written using the *real* business name as a literal string, directly inside the document meant to describe how the name had been removed. Caught during the same verification sweep, before it was published.

With everything scrubbed, git history was rewritten from scratch — a single new commit reflecting the fully anonymized state, force-pushed over the two prior commits.

## 13. Live on GitHub Pages

The dashboard was already a self-contained static file; making it a live, clickable page rather than something to download and open locally meant enabling GitHub Pages against the repository (serving straight from the main branch), adding a marker file so GitHub's static-site generator wouldn't try to process the plain HTML/JSON as something else, and linking it prominently from the README — since GitHub's own markdown renderer strips scripts and frames from README content for security, a live link is the closest thing to "embedded" that's actually achievable there.

## 14. The /verify pass

**What `/verify` is.** A Claude Code skill built around one rule: verification means *observing the running system*, not reading code and not running the existing test suite. Running `selfcheck` proves the code does what its own author believed it should do — it can't catch a defect nobody thought to write a fixture for. `/verify` instead finds the change's real-world surface (here: a CLI you run, a file you open in an actual browser), drives it the way a real user would, and then deliberately pushes past the happy path — malformed input, edge-of-range data, the sequence a careless user might actually run — to see what breaks. Anything it finds is backed by captured, real output: a terminal pane, a browser console, a rendered screenshot — not a description of what the code "should" do.

The final phase of the original build was exactly this: a deliberate, adversarial verification pass — not re-reading the code, not re-running the existing test suite, but actually driving the running application and trying to break it.

**The fresh-clone experience**, never actually tested end-to-end before this: with `config.json` now required-but-gitignored, would a truly fresh clone fail gracefully, and would the documented fix actually work? Simulated by moving the local config aside — the pipeline failed immediately with exactly the documented error message; copying the blank template into place immediately unblocked it, exactly as documented.

**The XSS fix, live, not just in a string check.** Earlier verification of the fix (section 11) had confirmed no literal `<` character survived serialization — a real check, but not a live one. This pass went further: real `analyze()` output, from a real copy of the actual database with one deliberately malicious review inserted, run through the actual escaping code and actual embedding logic, then loaded in a real browser. The injected script did not execute. More interestingly, the malicious text — displayed to a user as a citation quote — turned out to be protected by **two independent layers**: the server-side escape that prevents the browser's HTML parser from ever seeing a raw `<`, and a second, previously-unnoticed client-side escape in the dashboard's own citation-rendering code. Neither layer alone was the whole story; discovering the second one required actually looking at what the rendered page showed a user, not just what the embedded data contained.

That same live test process caught its own procedural gap along the way, twice. First: an early, hand-crafted test payload crashed with an unrelated error *before* the code being verified ever ran — a shallow pass would have logged "no script executed" and called it proof of safety, when really nothing had executed at all. Chasing that crash down to its actual cause — rather than dismissing it as noise — led to a second, real, previously-unknown bug (below). Second, smaller but worth recording: a locally-built test artifact briefly rendered the *real* business name in its output, because test scripts inherit whichever `config.json` happens to be active locally, independent of what they're actually testing. Caught before it was shown to anyone, cleaned up immediately, and written down as a standing caution for next time.

**A real, previously unknown bug**, found only because that crash was chased rather than dismissed: the dashboard's trend chart divides by `(number of data points − 1)` to place each point on its x-axis. For a business with reviews spanning exactly one calendar quarter — a brand-new business, most obviously — that denominator is zero, and the entire chart silently breaks. Fixed by flooring the denominator at one; every place that had been computing a broken coordinate inherited the fix automatically, without needing separate changes. Verified by rebuilding the exact scenario that broke it and confirming a real browser now rendered it cleanly.

The recipe learned while running this pass — how to build an isolated test payload without touching real committed files, a couple of environment-specific gotchas encountered along the way, and the standing caution about locally-active config data — was written down as a persisted project skill, so the next verification pass starts from what this one learned rather than from zero.

**What `/verify` found here, in one place:** a divide-by-zero crash in the trend chart on a single-data-point business (a genuine bug, only visible once the app actually ran with that exact data shape), a second, previously-unknown defense layer in the citation-rendering code (only visible by looking at what the browser actually showed, not what the data contained), and — just as valuable — two negative results worth naming: the fresh-clone failure-then-recovery behaved exactly as documented, and a hand-built malicious payload's `Uncaught TypeError` turned out, on inspection, to be an unrelated real bug rather than noise to wave away. **What it teaches:** the highest-value `/verify` findings tend to come from the moment something looks like it *might* just be test-harness noise — the instinct to dismiss a weird error as "not my bug" is exactly the instinct `/verify`'s discipline exists to override.

## 15. The /code-review pass

**What `/code-review` is.** A Claude Code skill for general code-quality review — correctness bugs, duplicated logic, dead code, maintainability gaps — distinct from `/security-review`'s narrow security focus. By default it reviews only the diff since the last push, same as a normal PR review. At higher effort levels (`high`/`xhigh`), it runs differently: instead of one inline pass, it launches a background `Workflow` — multiple sub-agents, each looking at the change from a different angle (e.g. correctness, simplification, test coverage), followed by an adversarial verification pass that tries to refute each candidate finding before it's reported. Critically, at these higher effort levels it also accepts a free-text scope override, so instead of "review what changed," it can be told **"review the entire codebase from scratch, not just recent changes"** — which is what made a true whole-codebase review possible here, something `/security-review` (below) turned out not to support.

**Running it.** Invoked as `/code-review` with `high review the entire codebase from scratch, not just recent changes` — dispatching a real background `Workflow` run rather than an inline review. The run hit a partial failure along the way: its 12th sub-agent exceeded a structured-output retry cap and errored out, but the other 11 had already completed and recorded their results in the workflow's own run journal. Rather than treating the whole run as lost, the journal was read directly and its five already-verified findings were synthesized and ranked from that record — a workflow partially failing mid-run doesn't have to mean losing the work that did complete, provided its intermediate state is actually inspected rather than assumed gone.

**The five findings, and the fixes:**

1. **Trend chart crashed the entire page on an empty `kpis.trend` array** — a step beyond the single-point crash `/verify` had already caught and fixed (section 14): a business with *zero* dated reviews broke the whole dashboard, not just the trend chart. Fixed with an explicit empty-array guard that renders an honest "no data yet" state and lets the rest of the page render normally.
2. **The "by source" KPI tile hardcoded `google`/`yelp` as the only two keys** — it would have crashed outright for a business with only one review source configured, and would have silently dropped a third source if one were ever added, with no error to signal the gap. Fixed by iterating `by_source` generically, sorted by name, rather than naming the two sources explicitly.
3. **The 0.2★ "worsening" threshold was computed twice, once in Python (`theme_is_actionable()`) and once again in the dashboard's JavaScript, with no shared source of truth** — the same class of bug this project had already shipped once before, in a different form (Changelog item 2's action-threshold gap: two pieces of logic that were supposed to agree, silently drifting apart). Fixed by computing it once, in `analyze()`, and exposing the result as `theme.worsening` in `analysis.json`; the dashboard now just reads that field instead of recomputing its own copy of the rule.
4. **Dark-mode CSS values were duplicated verbatim** across the `prefers-color-scheme` media query and the `data-theme="dark"` attribute selector — two places that needed to always agree, kept in sync only by remembering to edit both. Consolidated into a single set of `--dark-*` custom-property tokens that both blocks reference via `var()`, so there's exactly one place to change a dark-mode color going forward.
5. **Two dead CSS rules** (an unused `.stat-tile .value small` selector and an unused `.sr-only` utility class) — removed.

**A near-miss found while shipping the fix, worth naming honestly.** Picking up finding 3's new `theme.worsening` field required re-running `analyze()` locally to regenerate `analysis.json` — and, exactly as the project's own privacy-design doc warns (see [Privacy design's maintenance warning](docs/privacy-design.md#%EF%B8%8F-maintenance-warning-re-running-analyze-locally-can-silently-reintroduce-the-leak)), that regeneration used the real, unfiltered local `config.json` and came within one `git add` of leaking the business's identity back into the repo a second time. Caught before staging anything, by the same `grep -ci` discipline established after the original scrub — and it's the concrete incident that prompted turning that discipline into a permanent, prominent README warning rather than trusting memory alone to prevent a third occurrence.

**Verification.** All five fixes were confirmed live in a real browser, not just read back — including deliberately rebuilding the two specific edge cases that used to crash (an empty trend array, a single-source dataset) to watch them render cleanly instead of erroring.

**What it teaches:** `/code-review` catches a different class of defect than `/verify` — not "does this crash when I run it," but "does this codebase contain the same bug in two places that will eventually drift," or "is there code left over that nothing calls anymore." Both are real; neither substitutes for the other. And a workflow-backed review's value survives a partial run failure, provided the underlying journal is treated as real, recoverable data rather than the run being written off entirely.

## 16. The /security-review pass

**What `/security-review` is.** A Claude Code skill purpose-built for one category: exploitable security vulnerabilities — injection, XSS, auth bypass, hardcoded secrets, unsafe deserialization, sensitive-data exposure — not general code quality. Its process runs in three phases: **(1) find** candidate vulnerabilities by tracing data flow from untrusted input to sensitive sinks, **(2) filter**, running a dedicated sub-agent *per candidate finding in parallel* against a long, explicit list of hard exclusions (denial-of-service, secrets-on-disk, rate-limiting, and a dozen more categories the process considers out of scope by design) and precedents (e.g. "URLs in logs are safe," "environment variables are trusted," "React/Angular are safe from XSS unless using `dangerouslySetInnerHTML`"), and **(3) keep only findings scored 8 or higher out of 10 confidence** by that filtering pass. The filtering phase is arguably the more important half: it exists specifically to stop a security review from turning into a wall of theoretical, unactionable noise.

Unlike `/code-review`, its scope is hardcoded rather than overridable: it always runs `git diff` against `origin/HEAD`, i.e. "whatever changed since the remote's default branch" — there's no built-in equivalent to `/code-review`'s free-text "review the whole codebase" override.

**Why it failed to run at all, the first time.** The command errored immediately with `ambiguous argument 'origin/HEAD...HEAD': unknown revision`. The root cause was specific to how this repository came to exist: `origin/HEAD` is a symbolic ref — a pointer recording "which branch does the remote consider its default" — and it's created automatically only by `git clone`. This repository was never cloned; it was built with `git init`, followed by `git remote add`, followed by `git push`, so nothing had ever created that pointer locally. **The fix:** `git remote set-head origin -a`, which explicitly asks the remote which branch is its default and creates the missing local `origin/HEAD` reference to match — confirmed working via `git rev-parse --verify origin/HEAD` resolving cleanly afterward.

**Why it still found nothing, the second time.** With the ref fixed, the command ran successfully — and reported an empty diff, because nothing had changed locally since the last push. `origin/HEAD...HEAD` was comparing a commit against itself. This wasn't a bug in the command; it's exactly what "diff-scoped by design" means. But it meant the codebase had, at this point, never actually been through a security review of its *existing* code — every prior security fix in this project (the XSS defect, section 11) had been caught by a review of a *recent change*, not a review of everything already sitting in the repo.

**Getting a whole-codebase result anyway.** Since the command itself has no scope override, its exact methodology was replicated by hand instead: the same trick already used to get a whole-codebase `/code-review` run (section 15) — diffing against git's **empty-tree hash** (`4b825dc642cb6eb9a060e54bf8d69288fbee4904`, the fixed SHA representing an empty tree that every git repository shares) instead of `origin/HEAD`, which makes the entire current codebase read as "newly added," and therefore in-scope. The command's own three-phase process was then followed exactly, using real parallel sub-agents rather than one pass of manual reading:

- **Phase 1 — find, in parallel, by attack surface.** Two independent finder agents, each blind to the other's work: one scoped to `pipeline.py` (the Python side — SQL/command injection, path traversal, how the Apify token is handled, whether scraped/untrusted review data ever reaches an unsafe sink), one scoped to `dashboard.html` (the client-side side — every place data from the embedded `ANALYSIS` object reaches the DOM, whether the existing `<` → `<` escaping is actually sufficient everywhere it's relied on, whether the `<script>`-tag embedding itself could still be broken out of). Between them, five candidate findings came back.
- **Phase 2 — filter, in parallel, one verifier per candidate.** Each of the five candidates got its own dedicated agent, applying the command's exact false-positive-filtering rubric — the same hard-exclusions list, the same precedents, the same 1–10 confidence scale — and, critically, re-reading the actual code itself rather than trusting the finder's claim at face value.
- **Phase 3 — the confidence-8 cutoff.**

**The five candidates, and why every one of them was rejected:**

| # | Candidate | Confidence | Why it didn't hold up |
|---|---|---|---|
| 1 | Apify API token sent as a URL query parameter (`?token=...`) instead of an `Authorization` header | 3/10 | The leak paths that make this a real risk elsewhere (shared proxy logs, CDN logs, `Referer` leakage) don't exist for a single-operator local CLI making direct HTTPS calls to `api.apify.com`. A real hardening suggestion; not an exploitable path here. |
| 2 | The XSS-safe JSON embedding doesn't escape Unicode line-separator characters (U+2028/U+2029) | 2/10 | Those characters have been valid inside JavaScript string literals in every major browser engine since 2019 (ES2019) — there is no longer any engine where this could break out of the string, so no exploit path exists in any current browser. |
| 3 | The review-quote escaping in the dashboard only handles `<`, not `&`, `"`, or `>` | 2/10 | True, but the quote is inserted as element *text content*, where `<` is the only character capable of opening a tag in the first place — the missing escaping is real fragility for some *future* change, not a hole in the code as it stands today. |
| 4 | Review date/rating/source metadata is inserted into the page without escaping, and could carry attacker-controlled HTML | 2/10 | Tracing the actual data path in `pipeline.py` showed each field is pipeline-normalized before it ever reaches the dashboard: rating is coerced through `float()` (rows that fail are dropped, never passed through as text), date is constrained to a strict machine-generated format, and "source" is always one of two literal strings (`"google"`/`"yelp"`) the pipeline's own code chooses — never text a reviewer wrote. |
| 5 | Theme and action labels are inserted into the page without escaping | 2/10 | Theme names are always one of eight fixed dictionary keys the pipeline defines; action text is always a pipeline-authored template. The finding was explicitly framed as a risk only "if the pipeline ever changes to embed raw review text here" — a hypothetical about future code, which the process's own rules exclude from being reported as a present vulnerability. |

**Result: zero findings survived.** Every candidate scored well below the 8/10 confidence bar the process requires, for reasons that trace back to actually reading the code's real data flow rather than assuming the worst from a surface pattern match. This also served as an independent re-confirmation that the two real fixes from earlier in the project — the XSS defense (section 11) and the PII-stripping at scrape time (section 9 of the privacy design) — are still in place and still doing their job, with no new gap introduced since.

**What it teaches:** the discipline that makes `/security-review` useful isn't the finding step — pattern-matching "unescaped data near `innerHTML`" is easy, and produces plenty of candidates. It's the filtering step, done adversarially and independently per finding, that turns a list of "looks suspicious" into a short, trustworthy list of "is actually exploitable." Finding 4 above is the clearest example: on its face it reads like a real stored-XSS bug, and only tracing exactly where `date`, `rating`, and `source` come from in the pipeline's own code — rather than trusting the label "review-derived" — showed it wasn't one. And separately: a command with a hardcoded scope (unlike `/code-review`'s overridable one) can still be extended to cover a whole codebase, as long as its *methodology* — not just its literal invocation — is understood well enough to replicate by hand.

## 17. Turning the review into a reusable skill

The whole-codebase security review in section 16 was hand-orchestrated: the built-in `/security-review` couldn't be pointed at anything but a diff, so its three-phase methodology was replicated manually with a team of sub-agents. That worked once, but "understand the methodology well enough to rebuild it by hand each time" is not a durable capability. So the manual process was captured as a project-scoped Claude Code skill, [`.claude/skills/security-review-codebase/SKILL.md`](.claude/skills/security-review-codebase/SKILL.md) — committed to the repo alongside the existing `verify` skill, so it ships with the project and runs as a single `/security-review-codebase` invocation.

**What the skill encodes**, distilled from the manual run: scope every tracked file as if newly added (the empty-tree-hash reframing, which also sidesteps the `origin/HEAD` problem that stopped the native command from running at all); one parallel finder agent per attack surface; one parallel false-positive-filter agent per candidate, applying the native command's verbatim exclusion/precedent rubric and re-reading the actual code rather than trusting the finder; and a confidence-≥8 cutoff, with everything below it listed as a traced-and-rejected candidate rather than hidden.

**Two lessons from the manual run were written into the skill as explicit rules**, because they were mistakes worth not repeating. First, the orchestration must use plain agent calls that return their results — the manual attempt used named background "teammates" with fork-relay chains and message-polling, which stalled, spawned duplicate finders, and left fifteen idle agents alive that had to be shut down one by one afterward. Second, a finding only counts if it's exploitable in the code *as it stands today*; "would become a bug if the code later changed" is excluded — two of the five candidates in the manual run were rejected on exactly that basis, and baking the rule in keeps the filter honest.

A standalone reference — origin, what it is, how it works, how to use it — lives in [`docs/security-review-codebase.md`](docs/security-review-codebase.md). The throughline worth naming: the most reusable output of a QA pass isn't the findings, it's the *process*, once it's captured somewhere a future session can invoke instead of reconstruct.

## 18. What the journey shows

A few things held true across the whole arc, worth naming explicitly:

- **Nearly every real bug was found by running something, not by reading code.** The Yelp mapping failure surfaced from an ad hoc SQL query while writing documentation. The dark-mode bug surfaced from loading the dashboard in an actual browser. The destructive test bug surfaced from running the exact sequence a real user would run. The XSS fix's second defense layer, and the trend-chart bug, both surfaced from a deliberately adversarial live-verification pass. `selfcheck` caught real regressions once they were known — but discovering the unknown ones took actually driving the application.
- **Every fix added a test, every time.** Not as ceremony — each regression test added is a specific, concrete answer to "how do we know this exact bug can't come back silently."
- **Consequential, hard-to-reverse decisions were made explicitly, not assumed** — spending real money on a scrape, pushing to a public repository, rewriting already-public git history, choosing what real customer data would and wouldn't be published. Each of those got a clear moment of explicit confirmation before it happened, not a quiet default.
- **`/verify`, `/code-review`, and `/security-review` are complementary, not redundant — each one caught something the other two structurally couldn't.** `/verify` found a divide-by-zero crash that only exists once real data actually flows through a real browser — no amount of reading the code would have surfaced it. `/code-review` found the *same class* of duplicated-logic bug the project had already shipped once before, in a completely different place (a threshold recomputed in two languages, silently able to drift) — the kind of thing a single adversarial verification pass isn't shaped to look for. `/security-review` found nothing real in this codebase, and that result is exactly as valuable as a real finding would have been: five plausible-looking candidates were traced all the way back to their actual data origin and definitively ruled out, rather than left as unresolved "maybe." None of the three is a substitute for the others.
- **The dataset stayed real throughout.** Every number in this document, in the README, and in the live dashboard — 960 reviews, a $0.40 total scrape cost, an eight-year-old bug pattern, a near-full-star gap between two review platforms — is real, unaltered data. Only the one identifying fact anyone would need to find the actual business was ever withheld.
