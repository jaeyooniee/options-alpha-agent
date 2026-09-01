# Cloud Worker Options

Verified against provider documentation on 2026-08-29.

Implementation references: [Cloud Run Jobs](https://cloud.google.com/run/docs/create-jobs),
[scheduled Cloud Run Jobs](https://cloud.google.com/run/docs/execute/jobs-on-schedule), and
[Cloud Storage generation preconditions](https://cloud.google.com/storage/docs/request-preconditions).

| Option | Strengths | Risks | Decision |
|---|---|---|---|
| Google Cloud Run Job + Cloud Scheduler | Containerized, scale-to-zero, scheduled runs, managed retries, secret integration, low expected cost | Billing account and cloud setup required; each job has a one-minute billing minimum | Recommended for the trading worker |
| Cloud Run service | Good for dashboard/API and webhook health checks; scales to zero | Local filesystem is disposable; persistent audit data needs external storage | Recommended for API/dashboard backend |
| GitHub Actions schedule | Standard runners are free for public repositories and setup is simple | Scheduled jobs can be delayed or dropped during high load; poor choice for time-sensitive trade management | CI and emergency fallback only |
| Always-on Cloud Run worker pool | Simple continuous loop | Official example estimates a continuously running 1 vCPU/512 MiB worker at about $11.61/month after free tier | Unnecessary for this one-week event |

Recommended architecture:

1. Cloud Scheduler triggers a Cloud Run Job every minute during US market hours.
2. The job runs the one-shot `options-alpha shadow-cycle --underlying SPY` worker,
   acquires its distributed run lock, checks the Alpaca market clock, reconciles
   account/orders/positions, records the deterministic entry decision, writes an
   immutable audit event, and terminates. An automated exit manager is a separate
   pre-execution requirement; it must not be implied by this currently non-executing worker.
3. Credentials live in Secret Manager. The image and repository contain no secrets.
4. Audit events and snapshots persist in managed storage; never rely on the disposable
   Cloud Run filesystem. Set `DURABLE_STATE_BACKEND=gcs` and `GCS_STATE_BUCKET`:
   `GCSAuditLog` uses Cloud Storage generation-match writes, verifies the complete
   hash chain before every append, and fails the worker closed on a conflict. The
   matching `GCSRunLock` uses create/delete generation preconditions with a 15-minute
   expiry, so overlapping jobs cannot silently share a local lock.
5. A separate scale-to-zero web service exposes the read-only dashboard and health.
6. Execution remains disabled in every deployed revision until the go/no-go checklist
   passes and the user approves the final configuration change; the kill switch stays
   on until that same release decision.

Both Dockerfiles bake in the fail-closed defaults (`ALPACA_PAPER=true`, both
execution approvals false, and the kill switch true). CI is configured to build
both images and run the worker's dependency-free end-to-end demo inside the exact
worker image. The dashboard image also declares a `/api/healthz` container health
check. These checks require no credentials and send no network or broker request.

Before any deployment, configure only the bucket/object names in a private
environment or Secret Manager and run `options-alpha cloud-preflight`. It makes
no external call and returns `ready` only when GCS durability is selected while
paper execution remains disabled, approval remains false, and the kill switch
remains enabled. Cloud Run service identity should provide Application Default
Credentials; never mount or commit a service-account JSON key. The worker needs
only the audited prefix's object read/write/create/delete permissions, while the
dashboard should receive read-only access to the same prefix.

The current `shadow-cycle` command is deliberately conservative: it uses the
sanitized account probe and treats any existing position risk as the full portfolio
risk budget. The local lock prevents overlapping processes on one worker instance;
the GCS backend replaces it with a distributed lock. Read-only reconciliation now
records individual order lifecycle/fill snapshots with hash-redacted broker IDs and
position-level P&L. Exact position-to-order P&L attribution still needs real paper
fill evidence before the worker can be considered complete. That is a blocker, not
an implementation detail to hide behind a scheduler.

Cost notes from official documentation:

- [Cloud Run pricing](https://cloud.google.com/run/pricing) includes a free tier and
  gives a one-minute hourly job example at an estimated $0/month after free tier.
- [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing) gives each
  billing account three jobs per month free, then charges $0.10/job/month.
- [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage)
  says standard GitHub-hosted runners are free for public repositories.
- [GitHub schedule troubleshooting](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
  warns that scheduled events can be delayed and, under sufficiently high load,
  dropped.

No cloud resource has been created. Deployment and any possible charge require user
approval immediately before execution.
