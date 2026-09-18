"""本地路径与环境变量单元测试（PRD 5.1/5.2）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pet_leather_studio.bootstrap import environment


def test_app_root_is_repo_root() -> None:
    root = environment.app_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "pet_leather_studio").is_dir()


def test_app_root_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert environment.app_root() == environment.app_root()


def test_local_env_all_paths_inside_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PET_LEATHER_STUDIO_DATA_ROOT", str(tmp_path))
    env = environment.local_env()
    for key, value in env.items():
        if key in {"QT_API", "UV_PYTHON_DOWNLOADS"}:
            continue
        assert value.startswith(str(tmp_path)), f"{key} 不在 DATA_ROOT 内: {value}"
    assert env["QT_API"] == "pyside6"


def test_apply_local_env_does_not_override_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UV_CACHE_DIR", "/tmp/already-set")
    environment.apply_local_env()
    assert os.environ["UV_CACHE_DIR"] == "/tmp/already-set"


def test_no_hardcoded_user_paths_in_source() -> None:
    """源码不得写死用户绝对路径（PRD 5.1）。"""
    src_root = Path(__file__).resolve().parents[2] / "src"
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, f"{path} 含写死的用户路径"
        assert "/home/" not in text, f"{path} 含写死的用户路径"
