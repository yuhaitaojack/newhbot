from __future__ import annotations

import uuid


def new_id() -> str:
    return str(uuid.uuid4())


def new_cloid() -> str:
    """128-bit hex client order id, Hyperliquid-shaped. Never regenerated on retry."""
    return "0x" + uuid.uuid4().hex
