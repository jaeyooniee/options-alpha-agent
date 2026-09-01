# Alpaca MCP / Codex Plugin Evidence

## Verified connection

On 2026-08-29 KST, the installed `Alpaca` Codex plugin exposed read-only market-data
tools including:

- `alpaca_get_option_chain`
- `alpaca_get_option_latest_quote`
- `alpaca_get_option_snapshot`
- stock, option-contract, calendar, and market-clock lookups

The connection is therefore installed and callable; it is no longer merely requested.
Its current Codex scope exposes market data, not account or order tools. Account checks
are performed separately through the official `alpaca-py` SDK against the hard-coded
paper client.

## Sanitized verification transcript

Actual read-only calls made during repository verification:

1. Requested the SPY option chain with `feed=indicative` and a bounded expiration
   range. The response included contract symbols, latest trades, latest bid/ask,
   implied volatility, and Greeks.
2. Requested one SPY option quote with `feed=indicative`. One quote record returned
   with bid/ask prices, sizes, exchanges, and a UTC timestamp.
3. Requested the same option snapshot with `feed=indicative`. One snapshot returned
   with IV and delta, gamma, rho, theta, and vega.
4. Captured a bounded 22-contract SPY chain slice for one expiration and versioned
   the normalized quote/IV/Greeks rows with a SHA-256 checksum in
   `docs/option-snapshot-provenance.md`.

No order, cancellation, position mutation, credential transmission, or live endpoint
was used. Exact prices are intentionally omitted because they are time-dependent.

## Judge-facing evidence design

- Keep this text record in the public repository.
- Show the MCP tool name, sanitized request, and returned schema in the demo video.
- Show `options-alpha doctor` separately for paper account health and free-data access.
- Show `options-alpha market-evidence` for the read-only contract-master plus
  indicative-quote normalization and the four candidate catalog.
- Store tool-call timestamp, feed, parameters, response count, and a payload hash in
  the future audit log; never store API keys or the raw paper account ID.
- Put the actual paper account ID only in the required private submission field.

Official references:

- [Alpaca MCP Server](https://github.com/alpacahq/alpaca-mcp-server)
- [Alpaca multi-platform agent/plugin repository](https://github.com/alpacahq/agentic)
- [Option chain API](https://docs.alpaca.markets/us/reference/optionchain)
- [Get option contracts API](https://docs.alpaca.markets/us/v1.1/reference/get-options-contracts)
