from __future__ import annotations

from collections.abc import Callable
from typing import Any


FORBIDDEN_CONNECTOR_METHODS = frozenset(
    {
        "buy",
        "sell",
        "_place_order",
        "place_order",
        "cancel",
        "_place_cancel",
        "updateLeverage",
        "set_leverage",
        "_set_trading_pair_leverage",
    }
)


class ReadOnlyViolation(RuntimeError):
    """PHASE 4 forbids any trading-side connector call."""


class ReadOnlyGuard:
    """Proxy that records and blocks trading methods on a Hummingbot connector."""

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "violations", [])
        object.__setattr__(self, "read_only", True)

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN_CONNECTOR_METHODS:
            def blocked(*_args: Any, **_kwargs: Any) -> None:
                self.violations.append(name)
                raise ReadOnlyViolation(f"PHASE 4 read-only forbids {name}")

            return blocked
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_inner", "violations", "read_only"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._inner, name, value)


def assert_not_called(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        raise ReadOnlyViolation(f"PHASE 4 read-only forbids {name}")

    return wrapped
