"""Example strategy. Emits HOLD only. Must never place orders."""

SIGNAL = "HOLD"


def on_bar(_snapshot: dict) -> str:
    return SIGNAL
