from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_SECRET_KEYS = {"private_key", "api_secret", "secret", "wallet", "mnemonic", "password"}


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        for key in _SECRET_KEYS:
            if key in message and len(message) > 40:
                record.msg = "[redacted log line containing secret-like key]"
                record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in ("request_id", "signal_id", "order_id", "cloid", "symbol", "side"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_SecretFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    log_dir = Path("logs")
    if log_dir.is_dir():
        file_handler = logging.FileHandler(log_dir / "backend.jsonl", encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(_SecretFilter())
        root.addHandler(file_handler)
    root.setLevel(level.upper())


def log_extra(
    *,
    request_id: str | None = None,
    signal_id: str | None = None,
    order_id: str | None = None,
    cloid: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
) -> dict[str, str]:
    extra: dict[str, str] = {}
    if request_id:
        extra["request_id"] = request_id
    if signal_id:
        extra["signal_id"] = signal_id
    if order_id:
        extra["order_id"] = order_id
    if cloid:
        extra["cloid"] = cloid
    if symbol:
        extra["symbol"] = symbol
    if side:
        extra["side"] = side
    return extra
