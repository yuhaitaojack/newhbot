from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.strategy.validate import StrategyValidationError


def content_hash(strategy_py: bytes, manifest_yaml: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(strategy_py)
    digest.update(b"\n---\n")
    digest.update(manifest_yaml)
    return digest.hexdigest()


def write_version_dir(root: Path, file_hash: str, strategy_py: bytes, manifest_yaml: bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    dest = (root / file_hash).resolve()
    try:
        dest.relative_to(root.resolve())
    except ValueError as exc:
        raise StrategyValidationError("invalid version path") from exc
    if dest.exists():
        return dest
    tmp = root / f".tmp-{uuid4().hex}"
    try:
        tmp.mkdir(parents=True)
        (tmp / "strategy.py").write_bytes(strategy_py)
        (tmp / "manifest.yaml").write_bytes(manifest_yaml)
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            _rmtree(tmp)
        if dest.exists():
            return dest
        raise
    return dest


def _rmtree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


def manifest_to_json(manifest: dict) -> str:
    return json.dumps(manifest, default=str, sort_keys=True)
