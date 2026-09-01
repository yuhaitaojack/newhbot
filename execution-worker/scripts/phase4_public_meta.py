"""Fetch public Hyperliquid metaAndAssetCtxs. No account, no keys."""

from __future__ import annotations

import json
import sys
import urllib.request


def main() -> int:
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps({"type": "metaAndAssetCtxs"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    universe = payload[0]["universe"]
    ctxs = payload[1]
    btc = None
    for coin, ctx in zip(universe, ctxs):
        if coin.get("name") == "BTC":
            mark = str(ctx.get("markPx", ""))
            tick = None
            if "." in mark:
                tick = 10 ** -len(mark.split(".")[1])
            btc = {
                "name": "BTC",
                "szDecimals": coin.get("szDecimals"),
                "markPx": mark,
                "tick_from_markPx": tick,
                "step": 10 ** -int(coin.get("szDecimals", 0)),
                "min_notional_hb_constant": 10,
            }
            break
    print(json.dumps({"ok": True, "universe_len": len(universe), "btc": btc}, indent=2))
    return 0 if btc else 2


if __name__ == "__main__":
    raise SystemExit(main())
