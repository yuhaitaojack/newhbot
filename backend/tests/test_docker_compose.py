from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _docker_executable() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    user_install = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
    if user_install.is_file():
        return str(user_install)
    return None


def test_docker_compose_config() -> None:
    docker = _docker_executable()
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
    assert result.returncode == 0, combined
    assert "backend:" in combined
    assert "execution-worker:" in combined
    assert "frontend:" in combined
