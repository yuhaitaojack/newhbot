# PHASE 149 Report — ema5break live round-trip monitor

## Status

**BLOCKED / STOPPED_RECOVERY**

The requested target of five completed LONG and five completed SHORT round trips was not reached. No further live orders are being submitted in this phase.

## Scope and controls

- Market: Hyperliquid perpetual, BTC-USD
- Strategy: `ema5break`
- Signal input: real closed Hyperliquid 5-minute candles
- Strategy checks: only after each 5-minute boundary, with no intermediate strategy polling
- Execution path: Strategy Runtime → Trading Controller → Execution Worker → Hyperliquid
- Position policy: one-way, one position maximum, no automatic reversal
- Final stable read-only verification: FLAT, no BTC-USD open orders

## Results

| Item | Result |
| --- | --- |
| Completed LONG round trips | 0 / 5 |
| Completed SHORT round trips | 0 / 5 |
| Real strategy SHORT opens | 1 |
| Real strategy round trips completed | 0 |
| Final exchange position | FLAT |
| Final BTC-USD open orders | 0 |

The one real SHORT was later closed through a separate reduce-only safety cleanup after the monitor entered Recovery. It is not counted as a completed EMA5Break round trip because the monitor did not receive and process its strategy CLOSE signal.

## Issues recorded

1. **IOC open below exchange minimum after quantity rounding.** The first SHORT attempt was rejected with `notional 9.83450 below minimum 10`; the controller had calculated a 70% notional before the Worker rounded quantity down. The monitor now uses a 75% buffer and records rejected opens immediately instead of waiting for a position confirmation.
2. **Worker 503 during a scheduled position query.** The second monitor run entered Recovery at the 5-minute check when `/rpc/position?symbol=BTC-USD` returned HTTP 503. No new order was submitted after the failure.
3. **Delayed/inconsistent account synchronization after Worker restart.** A single read reported FLAT, while stable repeated reads later recovered the existing SHORT. A stable reconciliation/cleanup flow was added and used before any further strategy start.
4. **Close acknowledgement/fill audit gap.** A reduce-only close returned local `OPEN` even after the exchange position was confirmed FLAT and the Worker returned no matching fill record. This can leave a stale local OPEN order and must be fixed before attempting ten continuous round trips on one persistent audit database.

## Safety actions

- Entered Recovery on confirmation timeout, Worker 503, and non-clean preflight.
- Did not auto-reverse or resubmit an unconfirmed open.
- Used only a Controller reduce-only close for the residual SHORT.
- Performed stable read-only final verification and stopped all phase containers.

## Verification

- Backend: `160 passed, 1 warning`
- Execution Worker: `96 passed, 13 skipped`
- `git diff --check`: passed

Relevant run artifacts:

- [phase146 live monitor report](/C:/Users/Admin/.codex/worktrees/61ba/newhbot/data/phase146_live_monitor_report.json)
- [phase147 live monitor report](/C:/Users/Admin/.codex/worktrees/61ba/newhbot/data/phase147_live_monitor_report.json)
- [phase149 live monitor report](/C:/Users/Admin/.codex/worktrees/61ba/newhbot/data/phase149_live_monitor_report.json)

