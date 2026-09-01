# Win-Risk Audit

Evidence-based audit, last reviewed 2026-09-01 KST. This is a prioritised
competition-readiness assessment, not a prediction of the competition result.
It intentionally distinguishes local implementation proof from evidence a judge
can actually inspect.

## Verdict today

The project is technically credible as a **safety-first options research
prototype**, but it is not yet competitive for the P&L criterion and cannot
yet satisfy all externally verifiable submission requirements. The immediate
ranking threats are real, not cosmetic: there is no live paper P&L, the
underlying-signal holdouts are negative, the autonomous worker is not deployed,
and there is no working public demo URL.

No change in this audit authorizes an order, public release, deployment, or
paid AI call.

## P0 — can prevent a competitive submission

| Risk | Evidence | Why it can lose | Repair / owner | Status |
|---|---|---|---|---|
| No realised competition P&L | Fresh account remains $100,000 with zero orders, fills, and positions | P&L Performance is an explicit official criterion | Finish research gates, then use only explicitly approved, bounded paper trades and record every lifecycle event | Blocked by strategy validation and user approval |
| Public GitHub repository | Public `main` repository is live at `https://github.com/jaeyooniee/options-alpha-agent`; latest remote CI run `33503335237` passed | This risk is resolved; future changes must preserve public-safe history and green CI | Keep release preflight mandatory before every approved push | Resolved 2026-09-01 |
| No working public demo URL | Dashboard exists only locally; no cloud resource exists | The submission form requests a direct live demo URL | Deploy read-only dashboard plus scheduled worker only on explicit approval | Awaiting user approval and cloud account |
| Worker is not autonomous in production | `shadow-cycle` is one-shot; no Scheduler/Cloud Run deployment exists | A local command is not a continuously autonomous agent | Deploy one-shot worker on a one-minute schedule with durable state, lock, and health proof | Awaiting deployment approval |
| An opened position has no automated close-order path | Existing positions now block every new AI entry for an auditable exit review, but `evaluate_exit` still makes only an `EXIT_REVIEW` and no worker resolves a real position to an audited close preview/order | A paper agent that can open but cannot safely close is not operationally autonomous and can damage P&L | Build and test a paper-only position ledger, exit preview, reconciliation, and separately approval-gated close adapter before enabling entries | Local implementation work required |

## P0 — strategy and P&L credibility

| Risk | Evidence | Why it can lose | Repair / owner | Status |
|---|---|---|---|---|
| Primary directional signal has negative holdouts | SPY: 33.3% directional holdout hit rate and -0.3236% mean signed return; QQQ: 25.0% and -0.8205% | Safety does not compensate for a signal with negative out-of-sample evidence | Do not call it alpha; collect/replay real option observations and require a predeclared evidence threshold before entry enablement | Required |
| The only robustness sweep is synthetic | It is explicitly `not_a_backtest`; call debit spread has positive mean in 1 of 6 scenarios | Assumed drift/volatility cannot select a live strategy | Keep it as payoff-risk testing only; add multi-date, signal-linked exact-leg observations | Required |
| AI can choose long calls/puts despite no selection evidence | The former signal gate accepted both a debit spread and a long option in each direction | Adds unvalidated convexity and makes live behavior less reproducible | Restrict the production path to the deterministic signal-recommended debit spread; retain long options only as research fixtures | Fix in progress |
| Contract selection does not yet make IV a deterministic entry rule | The short-horizon selector now prefers 2--10 DTE and target deltas when supplied, but IV is not yet a predeclared hard gate | Claims richer data than the live entry rule actually uses | Add a predeclared IV rule only after its effect is evaluated; never tune it from a favourable live outcome | Research required |
| No fill-quality evidence | Only free indicative quotes and conservative synthetic/exact-symbol marks exist | Indicative quotes can differ from paper order fill behavior | Record broker order/fill lifecycle and compare conservative pre-trade marks to fills | Required after approved paper execution |

## P1 — implementation and reliability risks

| Risk | Evidence | Why it can lose | Repair / owner | Status |
|---|---|---|---|---|
| No open-market end-to-end AI shadow proof | Existing live evidence is a closed-market `NO_TRADE`; Featherless live inference is intentionally not run | Technology Implementation is not fully demonstrated under live market data | Run one explicitly approved, non-executing open-market shadow cycle and capture sanitized evidence | Awaiting market session and paid-call approval |
| No durable production audit proof | GCS code and preflight exist but no bucket/deployed worker is configured | A disposable worker cannot provide a reliable audit trail | Deploy GCS-backed audit and verify hash-chain continuity from the public-safe dashboard | Awaiting deployment approval |
| CI has never run remotely | GitHub Actions run `33503335237` completed successfully, including tests, submission check, worker build/smoke, and dashboard smoke | This risk is resolved for the current commit; later changes can regress it | Require a green remote run after every release push | Resolved 2026-09-01 |
| Container runtime is not locally verified | Docker is unavailable locally; worker/dashboard image smoke tests passed in the public GitHub Actions run | Deployment can fail despite Python tests | Validate the deployed health endpoint after approved cloud deployment | Awaiting deployment |
| Minute scheduling documentation conflicts with prior five-minute architecture text | `docs/minute-operations.md` says one minute while cloud options previously said five minutes | Judges may question what actually runs | Make the worker contract and cloud instructions consistently one minute, including retry/lock behavior | Local documentation fix required |

## P1 — presentation and judging evidence risks

| Risk | Evidence | Why it can lose | Repair / owner | Status |
|---|---|---|---|---|
| Demo video is a polished deck, not an open-market dashboard trace | MP4 is locally validated, but no deployed/live dashboard is captured | Presentation score suffers if the agent only appears conceptual | Replace or append a concise live dashboard/evidence-to-risk trace after an approved deployment/shadow run | Awaiting live evidence |
| Current dashboard has no public performance narrative | It shows safety/audit cards but no realised P&L or real completed cohorts | It cannot persuade on P&L today | Add truthful paper P&L, trade timeline, accepted/rejected reasons, and limitations once real data exists | Required after observations |
| Differentiator is safety, a crowded agent theme | “AI proposes; deterministic gates decide” is clear but not enough by itself | Creativity requires the control layer to visibly change agent behavior | Demonstrate counterfactual failures: stale quote, malformed AI, overlap lock, and risk veto; explain the auditable capital firewall | Local demo improvement required |
| Build-in-public evidence is unpublished | Five drafts exist but no approved posts | Optional social visibility/prize opportunities are unused | Select up to five and publish only with explicit user approval | Awaiting user approval |

## P2 — procedural and credibility risks

| Risk | Evidence | Why it can lose | Repair / owner | Status |
|---|---|---|---|---|
| Enrollment/team/profile/Discord state is not stored in the repository | No local evidence confirms these organizer-account steps | A non-code submission prerequisite can block final upload | User confirms the LabLab enrollment, solo team, and Discord connection in the event UI | User action |
| Final form fields remain unverified | Account ID is deliberately excluded; no live form entry exists | Title, URL, media, and account ID could be omitted at the deadline | Execute the final runbook with a human form checklist near submission | User action at final submission |
| No independent review or reproducible release tag | No commit exists | Last-minute changes can be hard for judges to reproduce | Create a signed-off local commit and release tag after final checks; publish only on approval | Local work, then approval |

## Repair order

1. Make the live strategy narrower and deterministic: signal direction must map
   to one debit-spread structure; no unvalidated long-option selection.
2. Implement the missing exit-management/position-ledger path while retaining
   all execution switches off.
3. Define a precommitted, real-data research gate for strategy promotion;
   collect minute-by-minute read-only observations as soon as the market opens.
4. Run an approved open-market shadow inference, then capture reproducible
   evidence and refresh the dashboard/video.
5. With separate approvals: deploy the read-only dashboard and worker, refresh
   live evidence and presentation assets, then submit the final form. Keep the
   existing public source and green CI as release baselines.

## What is already strong

- Paper-only configuration is enforced and tested; execution is off and the
  kill switch is on.
- Alpaca Trading API, MCP read path, indicative option chain, IV, Greeks,
  account freshness, and options level are documented without exposing secrets.
- The deterministic risk engine, strict AI schema, audit chain, quote freshness,
  stale-data fail-closed behavior, and MLeg dry run are unusually reviewable.
- Local quality gates pass: Ruff formatting/lint, submission check, and 140
  tests as of this audit.

These strengths are the foundation for a good submission, but they do not erase
the P0 gaps above.
