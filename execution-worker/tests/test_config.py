from __future__ import annotations

import pytest

from app.config import (
    HYPERLIQUID_MAINNET_DOMAIN,
    HYPERLIQUID_TESTNET_DOMAIN,
    load_config,
)


def test_hyperliquid_domain_defaults_to_testnet(monkeypatch) -> None:
    monkeypatch.delenv("HYPERLIQUID_DOMAIN", raising=False)
    assert load_config().hyperliquid_domain == HYPERLIQUID_TESTNET_DOMAIN


def test_hyperliquid_domain_requires_explicit_supported_value(monkeypatch) -> None:
    monkeypatch.setenv("HYPERLIQUID_DOMAIN", "not-a-hyperliquid-domain")
    with pytest.raises(RuntimeError, match="HYPERLIQUID_DOMAIN"):
        load_config()


def test_mainnet_domain_is_only_selected_by_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("HYPERLIQUID_DOMAIN", HYPERLIQUID_MAINNET_DOMAIN)
    assert load_config().hyperliquid_domain == HYPERLIQUID_MAINNET_DOMAIN
