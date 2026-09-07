"""Print only whether untracked credentials exist. Never prints values."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env_path = ROOT / ".env"
keys: set[str] = set()
execution_enabled = None
if env_path.is_file():
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "EXECUTION_ENABLED":
            execution_enabled = value.lower()
        if key in {"HYPERLIQUID_PERPETUAL_SECRET_KEY", "HYPERLIQUID_PERPETUAL_ADDRESS"} and value:
            keys.add(key)
print("env_file", env_path.is_file())
print("execution_enabled_env", execution_enabled)
print("address_present", "HYPERLIQUID_PERPETUAL_ADDRESS" in keys)
print("secret_present", "HYPERLIQUID_PERPETUAL_SECRET_KEY" in keys)
