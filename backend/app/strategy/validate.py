from __future__ import annotations

import ast
import re

NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
VERSION_RE = re.compile(r"^[0-9]+([.][0-9]+){0,2}([a-zA-Z0-9_-]*)?$")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,16}-[A-Z0-9]{2,16}$")
INTERVAL_RE = re.compile(r"^[0-9]+[smhd]$")

MAX_STRATEGY_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 64 * 1024

FORBIDDEN_MODULES = frozenset(
    {
        "subprocess",
        "socket",
        "ctypes",
        "hummingbot",
        "http",
        "http.client",
        "http.server",
        "urllib",
        "urllib.request",
        "urllib.parse",
        "urllib.error",
        "requests",
        "aiohttp",
        "httpx",
        "ssl",
        "pickle",
        "marshal",
        "importlib",
        "multiprocessing",
        "shutil",
        "pty",
        "webbrowser",
        "ftplib",
        "smtplib",
    }
)
FORBIDDEN_MODULE_PREFIXES = ("hummingbot", "urllib", "http")
FORBIDDEN_OS_NAMES = frozenset({"system", "popen", "exec", "execl", "execv", "spawn", "spawnl", "spawnv"})
FORBIDDEN_CALLS = frozenset(
    {
        "buy",
        "sell",
        "place_order",
        "cancel",
        "cancel_order",
        "set_leverage",
        "open_long",
        "open_short",
        "close_position",
        "__import__",
        "eval",
        "exec",
        "compile",
    }
)


class StrategyValidationError(ValueError):
    pass


def assert_expected_filename(filename: str | None, expected: str) -> None:
    if not filename:
        return
    if "\x00" in filename:
        raise StrategyValidationError("invalid filename")
    normalized = filename.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise StrategyValidationError("path traversal is not allowed")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise StrategyValidationError("absolute paths are not allowed")
    if normalized != expected:
        raise StrategyValidationError(f"only {expected} is allowed")


def validate_name_version(name: str, version: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise StrategyValidationError("strategy name is invalid")
    if not VERSION_RE.fullmatch(version):
        raise StrategyValidationError("strategy version is invalid")


def validate_manifest(data: object) -> dict:
    if not isinstance(data, dict):
        raise StrategyValidationError("manifest must be a YAML mapping")
    name = data.get("name")
    version_raw = data.get("version")
    if isinstance(version_raw, int):
        version = str(version_raw)
    elif isinstance(version_raw, str):
        version = version_raw
    else:
        version = None
    symbol = data.get("symbol") or data.get("trading_pair")
    interval = data.get("interval") or data.get("period") or data.get("timeframe")
    if not isinstance(name, str) or version is None:
        raise StrategyValidationError("manifest must include string name and version")
    validate_name_version(name, version)
    if not isinstance(symbol, str) or not SYMBOL_RE.fullmatch(symbol):
        raise StrategyValidationError("manifest must include a valid trading pair")
    if not isinstance(interval, str) or not INTERVAL_RE.fullmatch(interval):
        raise StrategyValidationError("manifest must include a valid interval")
    return {
        "name": name,
        "version": str(version),
        "symbol": symbol,
        "interval": interval,
        "raw": data,
    }


def validate_strategy_source(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise StrategyValidationError(f"strategy.py is not valid Python: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _reject_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            _reject_module(module)
            if module == "os" or module.startswith("os."):
                for alias in node.names:
                    if alias.name in FORBIDDEN_OS_NAMES or alias.name == "*":
                        raise StrategyValidationError("dangerous import is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise StrategyValidationError("dunder access is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise StrategyValidationError("dunder access is not allowed")
        elif isinstance(node, ast.Call):
            _reject_call(node)


def _reject_module(name: str) -> None:
    if name in FORBIDDEN_MODULES or name.split(".")[0] in FORBIDDEN_MODULES:
        raise StrategyValidationError(f"dangerous import is not allowed: {name}")
    if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES):
        raise StrategyValidationError(f"dangerous import is not allowed: {name}")
    if name == "os" or name.startswith("os."):
        raise StrategyValidationError("dangerous import is not allowed: os")


def _reject_call(node: ast.Call) -> None:
    func = node.func
    if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
        raise StrategyValidationError(f"direct trading call is not allowed: {func.id}")
    if isinstance(func, ast.Attribute):
        if func.attr in FORBIDDEN_CALLS or func.attr in FORBIDDEN_OS_NAMES:
            raise StrategyValidationError(f"direct trading or dangerous call is not allowed: {func.attr}")
