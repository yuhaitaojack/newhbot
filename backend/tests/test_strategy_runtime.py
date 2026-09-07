from __future__ import annotations

import asyncio

from app.strategy.runtime import StrategyRuntime


def test_runtime_evaluates_strategy_in_subprocess(tmp_path) -> None:
    path = tmp_path / "strategy.py"
    path.write_text("def on_bar(snapshot):\n    return {'signal': 'HOLD', 'reason': snapshot['symbol']}\n", encoding="utf-8")

    result = asyncio.run(StrategyRuntime().evaluate(path, {"symbol": "BTC-USD"}))

    assert result == {"signal": "HOLD", "reason": "BTC-USD"}


def test_runtime_supports_future_annotations_but_rejects_strategy_imports(tmp_path) -> None:
    path = tmp_path / "strategy.py"
    path.write_text(
        "from __future__ import annotations\n"
        "def on_bar(snapshot: dict) -> str:\n"
        "    return 'HOLD'\n",
        encoding="utf-8",
    )
    assert asyncio.run(StrategyRuntime().evaluate(path, {})) == {"signal": "HOLD", "reason": None}

    path.write_text("import os\ndef on_bar(snapshot):\n    return 'HOLD'\n", encoding="utf-8")
    try:
        asyncio.run(StrategyRuntime().evaluate(path, {}))
    except ValueError as exc:
        assert "imports are disabled" in str(exc)
    else:
        raise AssertionError("strategy import was accepted")


def test_runtime_rejects_invalid_signal(tmp_path) -> None:
    path = tmp_path / "strategy.py"
    path.write_text("def on_bar(snapshot):\n    return 'BUY'\n", encoding="utf-8")

    try:
        asyncio.run(StrategyRuntime().evaluate(path, {}))
    except ValueError as exc:
        assert "invalid signal" in str(exc)
    else:
        raise AssertionError("invalid signal was accepted")


def test_runtime_rejects_file_access_from_strategy(tmp_path) -> None:
    path = tmp_path / "strategy.py"
    path.write_text(
        "def on_bar(snapshot):\n"
        "    open('should-not-exist', 'w')\n"
        "    return 'HOLD'\n",
        encoding="utf-8",
    )
    try:
        asyncio.run(StrategyRuntime().evaluate(path, {}))
    except ValueError as exc:
        assert "open" in str(exc)
    else:
        raise AssertionError("strategy file access was accepted")


def test_runtime_times_out(tmp_path) -> None:
    path = tmp_path / "strategy.py"
    path.write_text("def on_bar(snapshot):\n    while True: pass\n", encoding="utf-8")

    try:
        asyncio.run(StrategyRuntime(timeout_seconds=0.05).evaluate(path, {}))
    except TimeoutError:
        pass
    else:
        raise AssertionError("hung strategy was not terminated")
