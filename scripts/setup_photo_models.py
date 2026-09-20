#!/usr/bin/env python3
"""显式安装/下载/校验照片推理环境与模型；不进入应用启动路径。

子命令：
- bootstrap：创建项目本地 .venv-photo 并按 requirements/photo-inference.txt 安装
  （macOS arm64 默认 CPU 版 torch，不装 CUDA）。安装前检查磁盘余量并打印估算。
- download：经 .venv-photo 内的 worker 显式下载 DA2-Small 权重（此时才联网）。
- verify：按清单校验模型文件 hash。
- freeze-lock：把实际安装版本冻结到 requirements/photo-inference.lock。
- info：环境/权重/缓存体积与磁盘余量。

全部下载物固定在项目内：.venv-photo/、models/、.cache/（见 .gitignore）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv-photo"
VENV_PYTHON = VENV / "bin" / "python"
WORKER = ROOT / "scripts" / "photo_inference_worker.py"
REQUIREMENTS = ROOT / "requirements" / "photo-inference.txt"
LOCK = ROOT / "requirements" / "photo-inference.lock"
MODELS = ROOT / "models"
HF_CACHE = ROOT / ".cache" / "hf-photo"
MIN_FREE_BYTES = 8_000_000_000  # 8GB 磁盘余量预警线（估算而非保证）


def _uv() -> str:
    local = ROOT / ".tools" / "uv" / "uv"
    if local.is_file():
        return str(local)
    found = shutil.which("uv")
    if found:
        return found
    print("未找到 uv：请先运行 scripts/bootstrap.py", file=sys.stderr)
    raise SystemExit(2)


def _uv_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "UV_CACHE_DIR": str(ROOT / ".cache" / "uv"),
            "UV_PYTHON_INSTALL_DIR": str(ROOT / ".tools" / "python"),
        }
    )
    return env


def _du(path: Path) -> str:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return f"{total / 1e6:.1f} MB"


def _free_bytes() -> int:
    return shutil.disk_usage(ROOT).free


def cmd_bootstrap(args: argparse.Namespace) -> int:
    free = _free_bytes()
    print(f"磁盘余量：{free / 1e9:.1f} GB")
    if free < MIN_FREE_BYTES:
        print(
            f"余量低于预警线 {MIN_FREE_BYTES / 1e9:.0f} GB；torch+transformers 环境与权重"
            "可能需要数 GB，请确认后自行继续（本命令不据此中止）",
            file=sys.stderr,
        )
    uv = _uv()
    subprocess.run(
        [uv, "venv", str(VENV), "--python", args.python],
        env=_uv_env(),
        check=False,
    )
    if not VENV_PYTHON.is_file():
        print(f".venv-photo 创建失败：{VENV_PYTHON}", file=sys.stderr)
        return 1
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(VENV_PYTHON),
            "-r",
            str(REQUIREMENTS),
        ],
        env=_uv_env(),
        check=True,
    )
    if args.freeze:
        cmd_freeze_lock(args)
    print(f"环境体积：{_du(VENV)}（不含权重与缓存）")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    if not VENV_PYTHON.is_file():
        print(f"推理环境未创建（{VENV_PYTHON}）；先运行 bootstrap", file=sys.stderr)
        return 1
    command = [
        str(VENV_PYTHON),
        str(WORKER),
        "download",
        "--out",
        str(MODELS / "hf" / args.model_id),
        "--cache",
        str(HF_CACHE),
    ]
    if args.revision:
        command.extend(["--revision", args.revision])
    return subprocess.run(command, check=False).returncode


def _latest_model_dir() -> Path | None:
    """按 manifest.json 定位最新已下载模型（models/hf/<model_id>/<revision>/）。"""
    base = MODELS / "hf"
    if not base.is_dir():
        return None
    # revision 目录下可能有 hub 的 .cache 子目录：以 manifest.json 为准，避免误选
    candidates = sorted(path.parent for path in base.glob("*/*/manifest.json"))
    return candidates[-1] if candidates else None


def cmd_verify(args: argparse.Namespace) -> int:
    model = Path(args.model) if args.model else _latest_model_dir()
    if model is None:
        print("未找到已安装模型（models/hf/…）；先运行 download", file=sys.stderr)
        return 1
    print(f"校验：{model}")
    return subprocess.run(
        [
            str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable,
            str(WORKER),
            "verify",
            "--model",
            str(model),
        ],
        check=False,
    ).returncode


def cmd_freeze_lock(args: argparse.Namespace) -> int:
    uv = _uv()
    result = subprocess.run(
        [uv, "pip", "freeze", "--python", str(VENV_PYTHON)],
        env=_uv_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(
        "# 由 scripts/setup_photo_models.py freeze-lock 生成（实际安装版本）\n"
        "# 安装命令：uv pip install --python .venv-photo/bin/python "
        "-r requirements/photo-inference.txt\n" + result.stdout,
        encoding="utf-8",
    )
    print(f"已写入 {LOCK}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    print(f"磁盘余量：{_free_bytes() / 1e9:.1f} GB")
    for name, path in (
        (".venv-photo", VENV),
        ("models", MODELS),
        ("hf-photo 缓存", HF_CACHE),
    ):
        print(f"{name}：{_du(path) if path.exists() else '（不存在）'}")
    model = _latest_model_dir()
    print(f"最新模型：{model or '（未安装）'}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = result.add_subparsers(dest="command", required=True)
    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--python", default="3.11")
    bootstrap.add_argument("--freeze", action="store_true")
    download = sub.add_parser("download")
    download.add_argument("--model-id", default="depth-anything-v2-small-hf")
    download.add_argument("--revision", default=None)
    verify = sub.add_parser("verify")
    verify.add_argument("--model", default=None)
    sub.add_parser("freeze-lock")
    sub.add_parser("info")
    return result


def main() -> int:
    args = parser().parse_args()
    handlers = {
        "bootstrap": cmd_bootstrap,
        "download": cmd_download,
        "verify": cmd_verify,
        "freeze-lock": cmd_freeze_lock,
        "info": cmd_info,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
