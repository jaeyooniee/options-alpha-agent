# Local Submission Check

Run:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli submission-check
```

The command performs local checks only. It verifies the required documents,
MIT license, worker/demo artifacts, the polished one-page PDF, the cover PNG's
actual 1600×900 dimensions, the slide PDF, title and description length limits, the maximum five
build-in-public drafts, an MP4 `ftyp` container signature and 300 MB size limit,
and secret-like values outside `.env` across source, data, scripts, and CI
files. It never uploads, creates a repository, deploys a service, publishes a
post, or reads the contents of `.env`.

An absent `submission/demo.mp4` blocks the check because the hackathon requires
an MP4. The current generated file passes the local container, size, and secret
checks; `scripts/verify-demo-video.mjs` additionally verifies browser decoding,
duration, resolution, and sampled frames. A public demo URL, GitHub repository,
paper account ID, and external submission form are intentionally outside this
local check and remain approval-gated.
