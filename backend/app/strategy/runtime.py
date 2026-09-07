from __future__ import annotations

"""Strategy runtime stub. PHASE 2: interface only, no live plugin execution."""

import asyncio
import base64
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.enums import SignalType


@dataclass(frozen=True)
class StrategySnapshot:
    symbol: str
    mid_price: str
    position_side: str


class StrategyRuntime:
    """Evaluate an uploaded strategy in a restricted one-shot subprocess."""

    _runner = r'''
import base64, json, sys
payload = json.loads(sys.stdin.read())
source = base64.b64decode(payload["source"]).decode("utf-8")
snapshot = payload["snapshot"]
_real_import = __import__
def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    # Python executes a future import at module load. No strategy dependency
    # imports are allowed; this narrow exception only supports annotations.
    if name == "__future__":
        return _real_import(name, globals, locals, fromlist, level)
    raise ImportError("strategy imports are disabled")
safe_builtins = {"None": None, "True": True, "False": False, "abs": abs, "all": all,
"any": any, "bool": bool, "callable": callable, "dict": dict, "enumerate": enumerate, "float": float,
"frozenset": frozenset, "int": int, "isinstance": isinstance, "len": len, "list": list, "max": max, "min": min, "range": range,
"round": round, "str": str, "sum": sum, "tuple": tuple, "zip": zip, "__import__": _safe_import}
namespace = {"__builtins__": safe_builtins}
exec(compile(source, "strategy.py", "exec"), namespace, namespace)
fn = namespace.get("on_bar") or namespace.get("evaluate")
if not callable(fn):
    raise ValueError("strategy must define on_bar(snapshot) or evaluate(snapshot)")
result = fn(snapshot)
signal, reason = (result.get("signal"), result.get("reason")) if isinstance(result, dict) else (result, None)
if signal not in {"LONG", "SHORT", "CLOSE", "HOLD"}:
    raise ValueError("strategy returned an invalid signal")
print(json.dumps({"signal": signal, "reason": reason}, separators=(",", ":")))
'''

    def __init__(self, *, timeout_seconds: float = 2.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def evaluate(self, source_path: str | Path, snapshot: dict) -> dict:
        path = Path(source_path).resolve()
        if path.is_dir():
            path = path / "strategy.py"
        if path.name != "strategy.py" or not path.is_file():
            raise ValueError("active strategy.py is unavailable")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", "-c", self._runner,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1"},
        )
        request = json.dumps({"source": base64.b64encode(path.read_bytes()).decode("ascii"), "snapshot": snapshot}).encode()
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(request), self._timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError("strategy evaluation timed out")
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-500:]
            raise ValueError(detail or "strategy evaluation failed")
        try:
            return json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("strategy returned invalid JSON") from exc
