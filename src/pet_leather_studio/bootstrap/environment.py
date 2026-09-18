"""项目本地路径与环境变量管理（PRD 5.1/5.2）。

约定：
- APP_ROOT 由本文件位置解析，不依赖启动时 cwd。
- 默认 DATA_ROOT = APP_ROOT；可用环境变量 PET_LEATHER_STUDIO_DATA_ROOT 覆盖
  （M3 交付设置界面中的正式更换与迁移校验）。
- 所有为本项目下载的包、Python、缓存必须落在 DATA_ROOT 下的本地目录。
- 不修改 HOME 等系统目录变量（PRD 5.2）。

注意：本模块在 editable 安装（uv sync 默认）下工作；若未来改为打包安装，
路径解析策略需在 ADR 中另行记录。
"""

from __future__ import annotations

import os
from pathlib import Path

# 相对 DATA_ROOT 的本地目录（均不提交，见 .gitignore）
_LOCAL_DIR_NAMES: tuple[str, ...] = (
    ".venv",
    ".tools",
    ".cache",
    ".cache/uv",
    ".cache/pip",
    ".cache/huggingface",
    ".cache/torch",
    "models",
    "vendor",
    "runtime",
    "runtime/logs",
    "runtime/tmp",
    "workspace",
)


def app_root() -> Path:
    """源码仓库根目录（APP_ROOT）。

    src/pet_leather_studio/bootstrap/environment.py -> 上溯 3 级为仓库根。
    """
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    """数据根目录（DATA_ROOT），默认等于 APP_ROOT。"""
    override = os.environ.get("PET_LEATHER_STUDIO_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return app_root()


def local_dirs() -> dict[str, Path]:
    """按 PRD 5.2 约定列出全部本地目录。"""
    root = data_root()
    return {name: root / name for name in _LOCAL_DIR_NAMES}


def ensure_local_dirs() -> list[Path]:
    """创建缺失的本地目录，返回本次新建的目录列表。"""
    created: list[Path] = []
    for path in local_dirs().values():
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def local_env() -> dict[str, str]:
    """需要在导入第三方依赖前注入的环境变量（PRD 5.2）。

    HF_*/TORCH_* 变量在本项目引入相应库之前是惰性的；先行设置可保证
    未来下载物不会散落到用户全局缓存。
    """
    root = data_root()
    env = {
        "QT_API": "pyside6",
        "UV_CACHE_DIR": str(root / ".cache/uv"),
        "UV_PROJECT_ENVIRONMENT": str(root / ".venv"),
        "UV_PYTHON_INSTALL_DIR": str(root / ".tools/python"),
        "PIP_CACHE_DIR": str(root / ".cache/pip"),
        "HF_HOME": str(root / ".cache/huggingface"),
        "HF_HUB_CACHE": str(root / ".cache/huggingface/hub"),
        "TORCH_HOME": str(root / ".cache/torch"),
        "XDG_CACHE_HOME": str(root / ".cache"),
    }
    return env


def apply_local_env() -> None:
    """将本地路径环境变量注入当前进程（不覆盖已有显式设置，便于排查）。"""
    for key, value in local_env().items():
        os.environ.setdefault(key, value)
