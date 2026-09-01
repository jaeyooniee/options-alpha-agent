# Official Requirements Verification

Verified against the official pages on 2026-08-29 KST.

## Event-specific requirements

Source: [Alpaca AI Trading Agents Hackathon](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)

- Event: 28 August–4 September 2026.
- Submission deadline shown to this project: 5 September 2026, 00:00 KST.
- Build an autonomous AI trading agent using Alpaca's Trading API.
- Use Alpaca's MCP server or Alpaca CLI.
- Every strategy must incorporate options.
- Develop and test in Alpaca paper trading only.
- Final judging account must be brand new, dedicated to the hackathon, and start at
  exactly $100,000.
- Include the paper account ID in the private hackathon submission field.
- Include a one-page write-up covering AI logic, risk gates, and Alpaca infrastructure.
- Submit title, short and long descriptions, technology/category tags, cover image,
  video presentation, slide presentation, public GitHub repository, demo platform,
  and working application URL.
- Up to five X or LinkedIn build-in-public links may be submitted. Posts should tag
  both lablab.ai and Alpaca.
- The public event page lists four judging criteria: **P&L Performance**,
  **Technology Implementation**, **Creativity & Originality**, and
  **Presentation & Execution**. It does not publish numeric weights. P&L is an
  explicit judging axis, so a zero-activity account is compliant but not yet
  competitive evidence.
- Submissions must be original and MIT-compatible.

## General lablab submission guidance

Source: [lablab Hackathon Guidelines](https://lablab.ai/ai-articles/hackathon-guidelines)

- Title: maximum 50 characters.
- Short description: maximum 255 characters.
- Long description: minimum 100 words.
- Cover image: 16:9 is recommended.
- Video: provide a link, keep it under 300 MB and no longer than five minutes.
- The event page requires a slide presentation. This repository will produce PDF,
  but the final submission form must be checked before upload for its accepted format.

## Alpaca technical facts used by this project

- [Basic market-data plan](https://docs.alpaca.markets/us/docs/about-market-data-api):
  free for paper and live accounts; options use the Indicative Pricing Feed, with
  200 historical API calls per minute and a 15-minute historical-data restriction.
- [Option chain endpoint](https://docs.alpaca.markets/us/reference/optionchain):
  returns latest trade, latest quote, implied volatility, and Greeks; `indicative`
  is the free feed.
- [Historical option data](https://docs.alpaca.markets/us/docs/historical-option-data):
  is available from February 2024; indicative quotes are modified derivatives and
  indicative trades are delayed by 15 minutes.
- [Paper trading](https://docs.alpaca.markets/us/docs/paper-trading): fills are
  simulated and omit market impact, latency slippage, queue position, regulatory
  fees, and other live-market effects. Backtests and paper P&L must disclose this.
- [Level 3 options](https://docs.alpaca.markets/us/v1.1/changelog/multi-leg-level-3-options-trading-in-paper):
  multi-leg spreads are supported in paper trading.
- [Official Alpaca MCP server](https://github.com/alpacahq/alpaca-mcp-server): v2
  exposes account, trading, asset, and options-data toolsets and defaults to paper
  trading when `ALPACA_PAPER_TRADE` is not changed.
