# Live Shadow-Cycle Evidence

This record contains no account ID or credential. It documents a read-only
closed-market run against the dedicated Alpaca paper account.

## 2026-08-29 KST

Command:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli shadow-cycle --underlying SPY
```

Observed, sanitized result:

- Alpaca paper account equity and cash: `$100,000`
- Orders, filled orders, open orders, and positions: `0`
- Alpaca market clock: closed
- Next open returned by Alpaca: `2026-08-31 09:30:00-04:00`
- Option market-data collection: skipped by the market-clock gate
- AI provider call: skipped (`provider_called=false`)
- Decision: `NO_TRADE`
- Deterministic risk result: not allowed (`ai_no_trade`)
- Execution adapter: disabled
- Order sent: `false`

The last three events formed one contiguous hash-chain segment:

| Event | Previous hash | Event hash |
|---|---|---|
| `market_closed` | `5ff4c21e…e41e` | `5c5dcdde…f2f2` |
| `shadow_risk_decision` | `5c5dcdde…f2f2` | `7b40ed68…be1c` |
| `order_blocked` | `7b40ed68…be1c` | `1516c269…0311` |

This proves the live account-reconciliation → market-clock → decision → risk →
execution-gate path while making no provider inference and no broker mutation.
It does **not** prove the open-market market-evidence/AI path; that remains a
separate, explicitly approval-gated shadow test.
