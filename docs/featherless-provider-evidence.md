# Featherless Provider Evidence

## Read-only verification

On 2026-09-02 KST, the configured Featherless API key was used for authenticated
plan/model metadata and one synthetic, non-trading inference. The key itself is
never printed, stored in this document, or committed to Git.

- Provider plan: `Request Pricing` (`feather_request_pricing`)
- Selected model: `mistralai/Mistral-Large-Instruct-2411`
- Model status: active
- Availability: warm tier
- Context length: 32,768 tokens
- Observed pricing: `$0.125` input and `$1.15` output per million tokens
- Inference calls during this verification: `1` synthetic smoke call
- Smoke result: valid decision contract, `NO_TRADE`, `error_type=null`,
  `order_sent=false`, estimated cost `$0.00010934`

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
