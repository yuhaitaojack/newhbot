from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docker_compose_config() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("BLOCKED: Docker未安装")
    result = subprocess.run(
        [docker, "compose", "config"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 and (
        "not recognized" in combined.lower()
        or "cannot find" in combined.lower()
        or "is not running" in combined.lower()
        or "docker desktop" in combined.lower()
    ):
        pytest.skip("BLOCKED: Docker未安装")
    assert result.returncode == 0, combined
