# Final Submission Runbook

This runbook is intentionally approval-gated. No step below creates a public
repository, deploys a service, publishes a post, submits a form, or sends an
Alpaca order unless the user explicitly approves that exact step immediately
before it runs.

## 1. Local verification

From the project directory:

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m options_alpha_agent.cli doctor
.venv\Scripts\python -m options_alpha_agent.cli ai-doctor
.venv\Scripts\python -m options_alpha_agent.cli capture-bars --underlying SPY --output data/underlying.capture.csv
.venv\Scripts\python -m options_alpha_agent.cli capture-option-snapshot --underlying SPY --expiration 2026-09-04 --output data/options/spy.indicative.next.csv
.venv\Scripts\python -m options_alpha_agent.cli demo
.venv\Scripts\python -m options_alpha_agent.cli shadow-performance --horizon-hours 24
.venv\Scripts\python -m options_alpha_agent.cli short-shadow --minimum-cohorts 10
.venv\Scripts\python -m options_alpha_agent.cli option-snapshot-check --csv data/options/spy.indicative.2026-08-28T1948Z.csv
.venv\Scripts\python -m options_alpha_agent.cli option-snapshot-compare --entry data/options/spy.indicative.2026-08-28T1948Z.csv --exit data/options/spy.indicative.2026-08-28T1957Z.csv
.venv\Scripts\python -m options_alpha_agent.cli replay --csv data/replay.sample.csv
.venv\Scripts\python -m options_alpha_agent.cli walk-forward --csv data/underlying.sample.csv
.venv\Scripts\python -m options_alpha_agent.cli robustness --paths 1000
.venv\Scripts\python -m options_alpha_agent.cli submission-check
```

The organizer-facing one-page artifact is
`output/pdf/options-alpha-one-page.pdf`; rebuild it with
`python scripts/build-one-page-pdf.py` after any material architecture or metric
change, then visually inspect the rendered page.

The non-network portion can also be reproduced with
`powershell -ExecutionPolicy Bypass -File scripts/verify-offline.ps1`.
That script deliberately excludes `doctor`, `market-evidence`, `monitor`, and
`ai-smoke`; the first three use live read-only services and the last one may
consume a Featherless inference credit.

`doctor` and `ai-doctor` must not print credentials or raw account IDs. The
default remains `TRADE_EXECUTION_ENABLED=false`, `PAPER_ORDER_APPROVED=false`,
and `TRADING_KILL_SWITCH=true`.

## 2. Optional provider smoke test

After confirming that spending one Featherless request credit is acceptable:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli ai-smoke
```

This is a non-trading `NO_TRADE` test. It must not be replaced by a live trade
test.

## 3. MP4 artifact

The verified narrated 1080p H.264/AAC video already exists at
`submission/demo.mp4`. Follow `docs/demo-video-export.md` to rebuild it or
replace it with an optional live-dashboard cut. Run
`scripts/verify-demo-video.mjs --require-audio` and `submission-check` after any
replacement. Do not show `.env`, API keys, account IDs, or private browser tabs.

## 4. Git commit

Configure the repository-only identity and inspect the staged diff using
`docs/local-git-setup.md`, then run
`powershell -ExecutionPolicy Bypass -File scripts/release-preflight.ps1 -RequireStaged`.
A local commit may be created before a release push. This project already has
an approved public repository and a passing remote CI run; future pushes remain
approval-gated.

## 5. Public release and final form

Only after explicit approval, deploy the read-only dashboard/worker, publish the
selected build-in-public posts, and submit the final form. The public GitHub
repository already exists and its latest CI run passed. Use the paper account ID
only in the organizer's final submission field; never place it in source,
screenshots, logs, or public docs.
