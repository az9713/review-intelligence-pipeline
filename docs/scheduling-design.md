# Scheduling design — weekly or any user-specified interval

See [`README.md`](../README.md) for the project overview.

**Not yet implemented — this section documents the plan only. No files have been created, no `schtasks` command has been run.**

### Mechanism: Windows Task Scheduler, not a cloud schedule

`pipeline.py`'s three run-time steps (`scrape`, `analyze`, `render`) are fully deterministic Python with no AI reasoning involved at run time — Task Scheduler is the native OS mechanism for "run this on a timer," so this needs no new dependency and no cloud sync of the local `.env` token, `reviews.db`, or `dashboard.html`.

The alternative — a Claude Code cloud-hosted scheduled agent (the approach the source video uses, running the whole workflow conversationally inside co-work) — is worth naming explicitly rather than dismissing: it would let the refresh happen even with this PC powered off, which Task Scheduler cannot do. That's the one real advantage it has here. It costs meaningfully more complexity for this project specifically, since the pipeline's state (the Apify token in `.env`, the growing `reviews.db`, the `dashboard.html` a person opens locally by double-click) all lives on this machine — a cloud schedule would need that state to either live in the cloud instead, or for the cloud agent to somehow write back to this machine, neither of which is a small change. Recommendation: Task Scheduler, unless "must run even when my PC is off" turns out to matter more than it appears to right now.

### The wrapper script

Task Scheduler's "Action" is one program + arguments, not a shell pipeline — so a small wrapper script chains the three steps:

```bat
@echo off
cd /d "C:\Users\simon\Downloads\claude_code_for_business_mansel_scheffel"
python pipeline.py scrape && python pipeline.py analyze && python pipeline.py render >> schedule-log.txt 2>&1
```

The `&&` chaining is load-bearing, not cosmetic: every pipeline command already `sys.exit()`s with a non-zero code on failure (missing token, an actor run ending `FAILED`, the $2 budget-abort guardrail tripping). If `scrape` fails, `&&` means `analyze` and `render` correctly never run — `dashboard.html` keeps showing last week's good data instead of being silently overwritten with a stale-but-technically-successful re-analysis of an incomplete scrape, or a render of an analysis that doesn't match what's actually in `reviews.db`.

This script is **cadence-agnostic** — it doesn't know or care whether it's invoked daily, weekly, or monthly. Cadence lives entirely in how the script is registered with Task Scheduler, not in the script itself.

### Registering it: generalizing to any cadence

One-time setup, via `schtasks /create`. The cadence is controlled by `/sc` (schedule type) and its modifiers — this is the part that generalizes to whatever interval is wanted:

| Desired cadence | Command |
|---|---|
| Weekly, Monday 9am (the default plan) | `schtasks /create /tn "ReviewIntelligencePipeline" /tr "...\run_schedule.bat" /sc weekly /d MON /st 09:00` |
| Daily, 6am | `schtasks /create /tn "..." /tr "..." /sc daily /st 06:00` |
| Every 2 weeks | `schtasks /create /tn "..." /tr "..." /sc weekly /mo 2 /d MON /st 09:00` |
| Monthly, on the 1st | `schtasks /create /tn "..." /tr "..." /sc monthly /d 1 /st 09:00` |
| Custom one-off (e.g. "run this once at 3pm tomorrow") | `/sc once /st 15:00 /sd MM/DD/YYYY` |

`/sc` accepts `MINUTE`, `HOURLY`, `DAILY`, `WEEKLY`, `MONTHLY`, `ONCE`, `ONLOGON`, `ONSTART`, `ONIDLE`; `/mo` is the "every N units" modifier (e.g. `/mo 2` with `/sc weekly` means every 2 weeks); `/d` picks the day (day-of-week for weekly, day-of-month for monthly). So "any user-specified scheduling" reduces to picking the right combination of these four flags — the wrapper script and `pipeline.py` itself never change.

### Cost by cadence — why this isn't cadence-free

Each run re-scrapes up to 500 *newest* reviews per source from scratch (no incremental date filter is currently wired up), at the measured ≈$0.40/run:

| Cadence | Runs/month | Approx. cost/month | Fits $5 free tier? |
|---|---|---|---|
| Monthly | 1 | $0.40 | Yes, trivially |
| Every 2 weeks | ~2.17 | $0.87 | Yes |
| **Weekly (the plan)** | ~4.33 | **$1.73** | Yes, comfortably |
| Daily | 30 | $12.00 | **No** — exceeds the free tier |

Weekly and anything less frequent are safe as-is. **Daily or more frequent would need the incremental-scrape optimization first** (Google's actor supports a `reviewsStartDate` parameter, already paired with the `reviewsSort: newest` this build uses — I'd default it to `MAX(scraped_at)` from `reviews.db`, i.e. "since the last successful scrape") — otherwise it would silently exceed the free tier and start spending real money without an explicit decision to do so. This is why the recommended default stays weekly unless a specific reason calls for something tighter.

### Logging

`schedule-log.txt` (append mode, stdout+stderr combined via `>> ... 2>&1`) — Task Scheduler runs silently with no visible console, so this is the only way to check whether last week's run actually succeeded, how much it cost, and what it found, without opening Task Scheduler's own history viewer.

### Caveats

- The machine needs to be on and awake at the scheduled time, or Task Scheduler's "wake the computer to run this task" option needs to be enabled on the trigger.
- Nothing here regenerates the dashboard's *narrative* — `render` just re-embeds the numbers. If a future version wants fresh AI-written commentary alongside the numbers each week, that specific piece would need an actual AI call in the loop (Claude Code scheduled task, or an API call added to `pipeline.py`), unlike everything else in this design, which is deliberately AI-free at run time.
