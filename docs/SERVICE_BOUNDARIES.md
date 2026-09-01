# Service boundaries

```
Web UI
  REST/WS
    Trading Service / API
      SQLite | Strategy Runtime (in-process stub) | Recovery Manager | Audit/Event
        Trading Controller   <-- sole trading entry
          Position Guard     <-- pure function on snapshots
            Execution Worker RPC (HTTP)
              WorkerRuntime (pair gate, READY, DRY_RUN)
                ExecutionAdapter (Mock | Hyperliquid)
                  Mock exchange  OR  Fake/Hummingbot Hyperliquid connector
```

Hummingbot objects stay inside the worker. Backend never imports them. Default `EXECUTION_ENABLED=false`.

Future strategy sandbox: `StrategyRuntime.evaluate()` is the reserved process boundary. Do **not** add a strategy Docker service in PHASE 2.

## Who may call whom

| Actor | May call Execution Worker? | May write orders? |
| --- | --- | --- |
| TradingController | Yes (only business module) | Yes, via repositories |
| PositionGuard | No | No |
| API `/api/trading/*` | No (must go through Controller) | No |
| Frontend | No | No |
| Strategy / StrategyRuntime | No | No |
| RecoveryManager | Read/health/sync via same ExecutionClient | No live opens |
| Execution Worker | Talks to adapter only | Must not store strategy or SQLite business state |

## Process / Docker map (PHASE 2)

| Compose service | Code | Persistence |
| --- | --- | --- |
| `backend` | FastAPI control plane | `./data`, `./logs`, `./strategies` |
| `execution-worker` | Mock adapter + RPC | `./logs` only (no business DB) |
| `frontend` | nginx + static UI | none |

Strategy Runtime remains inside `backend`. A later sandbox container must speak `evaluate(snapshot) -> LONG|SHORT|CLOSE|HOLD` and still go through TradingController.

PHASE 2 worker is Mock only. No Hyperliquid keys, no live orders.
