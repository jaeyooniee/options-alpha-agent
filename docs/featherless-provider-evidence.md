# Featherless Provider Evidence

## Read-only verification

On 2026-08-29 KST, the configured Featherless API key was used only for
authenticated plan and model metadata requests. The key itself is never printed,
stored in this document, or committed to Git.

- Provider plan: `Request Pricing` (`feather_request_pricing`)
- Selected model: `deepseek-ai/DeepSeek-V4-Flash`
- Model status: active
- Availability: live warm/hot tier
- Context length: 262,144 tokens
- Observed pricing: `$0.14` input and `$0.28` output per million tokens
- Inference calls during this verification: `0`

The application uses Featherless through its OpenAI-compatible API. The model
can only return the exact decision contract in `src/options_alpha_agent/ai.py`.
It cannot call Alpaca, send an order, change risk limits, or enable execution.
The application estimates input/output cost before each call, enforces daily
call and cost caps, and records a hash-chained local audit event. A provider
failure, malformed response, stale/synthetic evidence, or audit-write failure
becomes `NO_TRADE`.

## Reproducible commands

```powershell
.venv\Scripts\python -m options_alpha_agent.cli ai-doctor
.venv\Scripts\python -m options_alpha_agent.cli ai-smoke
```

`ai-doctor` performs plan/model metadata checks without inference. `ai-smoke`
uses synthetic evidence and expects a fail-closed `NO_TRADE`; it is not an order
test and cannot reach the Alpaca broker adapter.

## Cost control

The local defaults are 200 provider calls and `$2.50` estimated provider cost per
UTC day. The configured model prices are kept as local estimates for the budget
gate; actual provider usage is read from the response when available. These
limits are independent of the Featherless subscription balance.

Official references:

- [Featherless API documentation](https://featherless.ai/docs)
- [Featherless pricing](https://featherless.ai/pricing)
- [Alpaca AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)
