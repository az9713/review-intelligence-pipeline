---
name: verify
description: Project-specific launch/drive recipe for review-intelligence-pipeline
---

# Verifying this project

Zero dependencies. `python pipeline.py <command>` is the whole CLI surface; `dashboard.html` (opened as a `file://` URL, or the live GitHub Pages copy) is the whole GUI surface.

## Setup required before ANYTHING runs

`config.json` is loaded at **module import time** (`CONFIG = load_config()` at the top of `pipeline.py`), gitignored, not in the repo. Without it, even `selfcheck` fails immediately: `config.json not found -- copy config.example.json to config.json and fill in your business's details`. Copy `config.example.json` → `config.json` first if it's missing — a placeholder works fine for anything that doesn't need real business data (`selfcheck`, most of `analyze`/`render` on an existing `reviews.db`).

## Commands (the CLI surface)

- `python pipeline.py selfcheck` — offline, free, ~1s. Real regression tests, not a rerun of anything.
- `python pipeline.py analyze` — needs `reviews.db` (real one is gitignored/local-only). Deterministic given the db.
- `python pipeline.py render` — needs `analysis.json`. Re-embeds it into `dashboard.html` via exact string markers (`const ANALYSIS = ` ... `;\n\nconst root = ...`), not brace-matching.
- `python pipeline.py scrape` — **spends real Apify money** (~$0.40/run). Don't run live for verification; the guardrails and cost math are covered by reading the code + `selfcheck`, not by spending money to re-prove it.

## Driving `dashboard.html` for real (not just reading the JS)

To test with custom/malicious `analysis.json` data without touching the real committed files:

```python
import pipeline as p
p.DB = "<isolated test db path>"           # never point this at the real reviews.db
p.ANALYSIS_PATH = "<isolated test json path>"
p.analyze()                                 # produces fully-valid, complete output --
                                             # hand-crafting a minimal analysis.json WILL
                                             # miss required fields and crash the dashboard
                                             # JS in ways unrelated to what you're testing
                                             # (confirmed: empty/short `trend` arrays throw
                                             # or produce NaN SVG geometry -- a real found
                                             # edge case, not a hand-crafted-data artifact,
                                             # but don't let it mask what you're actually
                                             # verifying -- use real analyze() output and
                                             # surgically substitute only what you need).
```

Then build a test `dashboard.html` by copying the real one and replacing only the `DASHBOARD_START`/`DASHBOARD_END`-delimited payload (same markers `render()` uses) — never call the real `render()` against a test payload, since it writes straight to the committed `dashboard.html`.

**Load test files via Chrome DevTools MCP by absolute Windows path**, not Git Bash's `/tmp` — Python's own file I/O on Windows resolves a leading `/tmp/...` to `C:\tmp\...`, a *different* location from Git Bash's `/tmp` alias (`C:\Users\...\AppData\Local\Temp`). Both are silently "valid" paths that point to different places — this caused multiple false "file not found" errors. Use the session's scratchpad directory (an absolute `C:\...` path) for anything that needs to be visible to both a Python script and the browser.

**`sqlite3`'s `.backup()` API, not a raw file copy**, when cloning `reviews.db` for a test — a plain `cp`/`shutil.copy` intermittently produced a file that opens but reports `no such table: reviews` on this Windows setup. `.backup()` was reliable every time.

## Known-safe finding (confirmed 2026-07-18, live browser, not just static analysis)

The XSS fix (`json_for_script_tag()` escaping `<` → `<`) has **two independent layers**: the server-side escape prevents the HTML tokenizer from ever seeing a literal `<` in the `<script>` tag, and `dashboard.html`'s own action-citation rendering *separately* does `.replace(/</g,'&lt;')` before any quote text goes through `innerHTML`. Confirmed live: a review containing a full `</script><script>...</script>` payload renders as inert visible text (`document.scripts.length` stays `1`, no injected code runs) even when tested end-to-end through real `analyze()` output.

## ⚠️ Handling real business data during verification

`config.json` (if present locally) holds the **real** business name/address. Any `analyze()` call using the ambient `p.DB`/`p.ANALYSIS_PATH` still pulls `BUSINESS_NAME` from whatever `config.json` was loaded at import time — a test `analysis.json`/`dashboard.html` built this way **will contain the real business name in its header**, even if the test only cares about unrelated data. This project's public repo has zero mentions of the real business by design (see README's Privacy design section) — **never screenshot, paste, or otherwise surface a locally-generated test artifact without checking it for the real business name first.** Delete test artifacts from the scratchpad after use rather than leaving them around.
