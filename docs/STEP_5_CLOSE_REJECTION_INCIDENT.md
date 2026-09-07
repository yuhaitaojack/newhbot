# STEP 5 — Close Rejection Incident and Remediation

Date: 2026-09-03

## Current state

- The live worker reported `EXECUTION_ENABLED=true`, `READY`, and `LIVE`.
- The backend mirror reported one BTC-USD LONG position of approximately `0.00013`.
- The one-shot flow submitted a reduce-only SELL close request.
- The close was rejected before exchange submission because the normalized notional was `9.67707`, below the entry minimum `10`.
- The position remained open. No retry was issued by this review.

## Root cause

The worker applied the normal entry minimum-notional rule to reduce-only orders. A partially filled or otherwise small existing position can legitimately have a remaining notional below the entry threshold and still needs a reduce-only close path.

The backend also treated a rejected close as successful after synchronizing the mirror, which could report `ok=true` while the exchange position remained open.

## Remediation applied

- `execution-worker/app/quantization.py`: entry minimum-notional rejection is skipped for `reduce_only` requests.
- `execution-worker/app/hyperliquid_adapter.py`: the live adapter follows the same reduce-only rule.
- `backend/app/controllers/trading_controller.py`: a rejected close now returns `ok=false` and enters Recovery.
- Added regression tests for both worker quantization and live-adapter close handling.

## Verification

- execution-worker targeted tests: **21 passed**.
- The prior backend suite: **53 passed** when run with a writable temporary directory.
- The currently running processes have not been restarted, so this remediation has not been applied to the live process.

## Required next action

Restart the worker/backend with the patched code, re-read the authenticated position and open orders, and obtain explicit authorization before submitting one reduce-only close. After the close is confirmed FLAT, set execution disabled and stop the one-shot process.

Do not retry the old rejected intent, do not increase size to satisfy the entry minimum, and do not open a reverse position.
