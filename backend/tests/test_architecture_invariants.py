from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_EXECUTION_METHODS = {"place_order", "cancel_order", "set_leverage"}


def _forbidden_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in FORBIDDEN_EXECUTION_METHODS:
            violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.func.attr}")
    return violations


def test_api_and_strategy_have_no_direct_execution_calls() -> None:
    roots = [ROOT / "app" / "api", ROOT / "app" / "strategy"]
    violations = [
        violation
        for root in roots
        for path in root.rglob("*.py")
        for violation in _forbidden_calls(path)
    ]
    assert violations == []


def test_trading_controller_owns_backend_execution_calls() -> None:
    app_root = ROOT / "app"
    controller = ROOT / "app" / "controllers" / "trading_controller.py"
    violations = [
        violation
        for path in app_root.rglob("*.py")
        if path not in {controller, ROOT / "app" / "execution" / "client.py"}
        for violation in _forbidden_calls(path)
    ]
    assert violations == []
