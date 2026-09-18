"""环境引导：创建本地目录、注入环境变量并用项目本地 uv 同步依赖。

需联网下载 Python 3.11 与依赖 wheel 到项目本地目录（PRD 5.2/5.3），
之后日常开发命令使用 scripts/dev.sh（frozen，不静默升级）。

用法：python3 scripts/bootstrap.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pet_leather_studio.bootstrap import environment  # noqa: E402


def find_uv() -> Path:
    """优先使用项目本地 .tools/uv/uv，其次系统 uv。"""
    local_uv = REPO_ROOT / ".tools" / "uv" / "uv"
    if local_uv.is_file() and os.access(local_uv, os.X_OK):
        return local_uv
    system_uv = shutil.which("uv")
    if system_uv:
        return Path(system_uv)
    raise SystemExit(
        "未找到 uv。请将 uv 可执行文件放入 .tools/uv/uv（项目本地），"
        "或安装到系统 PATH 后重试。不自动安装到系统目录。"
    )


def main() -> int:
    environment.apply_local_env()
    # 引导阶段允许临时目录就绪
    (environment.data_root() / "runtime" / "tmp").mkdir(parents=True, exist_ok=True)
    created = environment.ensure_local_dirs()
    if created:
        print(f"已创建本地目录 {len(created)} 个（均在 DATA_ROOT 内，不入 git）")

    uv = find_uv()
    print(f"使用 uv: {uv}")
    env = dict(os.environ)
    env.update(environment.local_env())
    result = subprocess.run(  # noqa: S603 - 参数数组，shell=False
        [str(uv), "sync", "--python", "3.11", "--extra", "dev"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        print("uv sync 失败，请检查上方错误输出。", file=sys.stderr)
        return result.returncode

    print("依赖同步完成。日常开发命令示例：")
    print("  scripts/dev.sh run --frozen ruff check .")
    print("  scripts/dev.sh run --frozen pytest tests/unit tests/architecture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
