# Demo Video Export

The required local MP4 exists at `submission/demo.mp4`. It was generated from
the six visually checked 16:9 slide renders by
`scripts/build-demo-video.mjs`, with a Windows SAPI narration track, then
independently decoded and sampled by `scripts/verify-demo-video.mjs`.

Validated metadata:

- H.264/AAC MP4 (`video/mp4;codecs=avc1.42E01E,mp4a.40.2`)
- 1920×1080
- 158.9901 seconds
- 22,468,750 bytes
- SHA-256 `B8E0C8B4288B55A342B3204A276C8C461E9526420DBDAAD5430B7CC4DEE8A134`
- Audio decoded by Chrome; six sampled video frames visually checked
- Six sampled frames visually checked with no clipping, black frames, or decode errors

To rebuild it on Windows with the installed SAPI voice, Node.js, Playwright, and
Chrome available:

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File scripts/build-demo-narration.ps1 -Overwrite
node scripts/build-demo-video.mjs --slides artifacts/deck-render --audio artifacts/demo-narration.wav --fit-audio --output submission/demo.mp4 --seconds-per-slide 6 --transition-seconds 0.6 --overwrite
node scripts/verify-demo-video.mjs --video submission/demo.mp4 --frames artifacts/video-qa --require-audio --frame-count 6
.venv\Scripts\python -m options_alpha_agent.cli submission-check
```

The current file is a narrated architecture demo and satisfies the local MP4
artifact checks. It still does not show a live dashboard or live broker action;
those should be added only if recorded without exposing secrets. Re-run both
verification commands afterward. Never show `.env`, API keys, account IDs, or
private browser tabs in the recording.

PowerPoint remains a manual fallback: open
`artifacts/Options-Alpha-Guarded-Agent.pptx`, choose **File → Export → Create a
Video**, select **Full HD (1080p)**, and export to `submission/demo.mp4`.
