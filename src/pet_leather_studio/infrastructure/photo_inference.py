"""隔离推理进程调用、模型清单校验与深度修订组装。

- 不在本模块导入时下载或加载权重；正常产品路径零网络访问。
- worker 运行于 .venv-photo 独立环境（scripts/photo_inference_worker.py）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pet_leather_studio.domain.errors import ResourceMissingError, ToolUnavailableError
from pet_leather_studio.domain.photo_relief import (
    MIN_DEPTH_VALID_COVERAGE,
    DepthSemantics,
)
from pet_leather_studio.infrastructure.photo_io import MASK_BINARY_THRESHOLD

KNOWN_MODEL_ID = "depth-anything-v2-small-hf"
SETUP_COMMAND = "scripts/setup_photo_models.py bootstrap && scripts/setup_photo_models.py download"


class ModelRegistry:
    """models/<provider>/<model>/<revision>/ 本地清单与 SHA-256 校验。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _manifest(self, revision_dir: Path) -> dict[str, Any] | None:
        path = revision_dir / "manifest.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _selected(self, model_id: str) -> str | None:
        """download 时写入的显式选中版本；缺失/损坏视为未选择。"""
        path = self.root / "hf" / model_id / "selected.json"
        if not path.is_file():
            return None
        try:
            return str(json.loads(path.read_text(encoding="utf-8"))["revision"])
        except (OSError, ValueError, KeyError):
            return None

    def locate(self, model_id: str | None) -> Path:
        model = model_id or KNOWN_MODEL_ID
        parent = self.root / "hf" / model
        if not parent.is_dir():
            raise ResourceMissingError(
                f"模型 {model} 未安装；请先运行：{SETUP_COMMAND}（显式下载，产品路径不联网）"
            )
        entries: list[tuple[str, Path]] = []
        for path in parent.iterdir():
            if not path.is_dir():
                continue
            manifest = self._manifest(path)
            if manifest is not None:
                entries.append((str(manifest.get("downloaded_at") or ""), path))
        if not entries:
            raise ResourceMissingError(
                f"模型 {model} 没有带清单的修订目录；请先运行：{SETUP_COMMAND}"
            )
        selected = self._selected(model)
        if selected is not None:
            # 显式选择失效必须报错，不得静默换版本（明确选择失败 ≠ 可回退）
            chosen = next((path for _, path in entries if path.name == selected), None)
            if chosen is None:
                raise ResourceMissingError(
                    f"selected.json 指向修订 {selected}，但该目录缺失或无有效清单；"
                    "请重新 download 该版本，或人工确认后删除 selected.json 以回退最新下载"
                )
        else:
            # 无显式选择文件：按 manifest 的 downloaded_at 取最新；提交 hash 字典序不代表时间
            entries.sort()
            chosen = entries[-1][1]
        self.verify(chosen)
        return chosen

    def verify(self, model_dir: Path) -> dict[str, Any]:
        manifest_path = model_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ResourceMissingError(f"模型清单缺失：{manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files", {})
        if not files:
            raise ResourceMissingError("模型清单文件列表为空，拒绝使用（下载可能不完整）")
        if not any(name.endswith(".safetensors") for name in files):
            raise ResourceMissingError("模型清单不含 .safetensors 权重，拒绝使用")
        for name, expected in files.items():
            if name in ("", ".", "..") or "/" in name or "\\" in name:
                raise ResourceMissingError(f"模型清单包含非顶层路径 {name!r}，拒绝使用")
            path = model_dir / name
            if not path.is_file():
                raise ResourceMissingError(f"模型文件缺失：{name}（目录 {model_dir}）")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != expected.get("sha256"):
                raise ResourceMissingError(
                    f"模型文件损坏（hash 不匹配）：{name}；请重新运行下载或校验命令"
                )
        return manifest


def _group_has_live_process(pgid: int) -> bool:
    """进程组内是否仍有存活进程；先收割已退出的直接子进程，避免僵尸让组假活。"""
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    try:
        os.waitpid(pgid, os.WNOHANG)
    except ChildProcessError:
        pass  # 已被收割或非本进程子进程；继续按组探测
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _wait_group_exit(pgid: int, timeout_s: float) -> bool:
    """等待进程组退出；返回 True 表示超时前整组已退出。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _group_has_live_process(pgid):
            return True
        time.sleep(0.05)
    return not _group_has_live_process(pgid)


class DepthWorker:
    """以参数列表启动隔离进程执行真实推理；不拼 shell、不加载权重到本进程。

    取消语义（POSIX）：worker 以独立进程组启动；本进程收到 SIGTERM 时
    对整组先 TERM、等待后仍存活再 KILL（应对忽略 TERM 的 worker），
    全部回收后才退出，保证 GUI 取消后不残留推理子进程。
    """

    def __init__(self, venv_python: Path, worker_script: Path) -> None:
        self.venv_python = venv_python
        self.worker_script = worker_script

    def run(self, image: Path, mask: Path, model_dir: Path, out_dir: Path) -> dict[str, Any]:
        if not self.venv_python.is_file():
            raise ToolUnavailableError(
                f"推理环境未创建（{self.venv_python}）；请先运行：{SETUP_COMMAND}"
            )
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.venv_python),
            str(self.worker_script),
            "infer",
            "--image",
            str(image),
            "--mask",
            str(mask),
            "--model",
            str(model_dir),
            "--out",
            str(out_dir),
        ]
        popen_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True  # worker 独立进程组，便于整组回收
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **popen_kwargs,
        )
        previous_handler = None
        if os.name == "posix" and threading.current_thread() is threading.main_thread():

            def _terminate_worker(signum: int, _frame: object) -> None:
                # 整组 TERM → 短暂等待 → 仍存活则整组 KILL：对忽略 TERM 的
                # worker 也能回收，保证取消后不残留推理进程。
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    if not _wait_group_exit(process.pid, 2.0):
                        os.killpg(process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                raise SystemExit(128 + signum)

            previous_handler = signal.signal(signal.SIGTERM, _terminate_worker)
        try:
            stdout_text, stderr_text = process.communicate()
            returncode = process.returncode
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGTERM, previous_handler)
        if returncode != 0:
            tail = (stderr_text or stdout_text or "").strip().splitlines()[-8:]
            raise RuntimeError(f"推理进程失败（exit {returncode}）：\n" + "\n".join(tail))
        metadata_path = out_dir / "metadata.json"
        if not metadata_path.is_file() or not (out_dir / "depth_raw.npy").is_file():
            raise RuntimeError("推理进程未产出 metadata.json / depth_raw.npy")
        return json.loads(metadata_path.read_text(encoding="utf-8"))


class PhotoInference:
    """DepthInferencePort 实现：worker 输出 → 校验 → 组装 depth.npz 到 staging。"""

    def __init__(self, venv_python: Path, worker_script: Path) -> None:
        self.worker = DepthWorker(venv_python, worker_script)

    def run_and_stage(
        self, image: Path, mask: Path, model_dir: Path, stage: Path
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="photo-depth-") as tmp:
            out_dir = Path(tmp)
            worker_metadata = self.worker.run(image, mask, model_dir, out_dir)
            return assemble_depth_revision(out_dir, mask, stage, worker_metadata)


def assemble_depth_revision(
    worker_out: Path, mask_png: Path, stage: Path, worker_metadata: dict[str, Any]
) -> dict[str, Any]:
    """校验 worker 输出并把 depth.npz（数据+有效域）写入 staging。

    主体域内的 NaN/Inf 与过小有效覆盖在发布前拒绝（PH04），不把坏预测
    静默改成背景；depth_raw.npy 原样入修订以保留未置零的浮点输出。
    """
    depth = np.load(worker_out / "depth_raw.npy")
    arr = np.asarray(depth, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"深度输出必须为二维，收到 shape={arr.shape}")
    with Image.open(mask_png) as image:
        mask = np.asarray(image.convert("L"))
    if arr.shape != mask.shape:
        raise ValueError(f"深度输出形状 {arr.shape} 与蒙版 {mask.shape} 不一致")
    subject = mask > MASK_BINARY_THRESHOLD
    nonfinite = int(np.count_nonzero(~np.isfinite(arr[subject])))
    if nonfinite:
        raise ValueError(
            f"主体内深度含 {nonfinite} 个 NaN/Inf 像素，拒绝发布（PH04：有效域不得有非有限值）"
        )
    valid = subject
    if int(valid.sum()) == 0:
        raise ValueError("有效区域为空（蒙版为空或深度输出全无效）")
    coverage = float(valid.mean())
    if coverage < MIN_DEPTH_VALID_COVERAGE:
        raise ValueError(
            f"有效覆盖 {coverage:.2%} 低于工程下限 {MIN_DEPTH_VALID_COVERAGE:.0%}，拒绝发布"
        )
    region = arr[valid].astype(np.float64)
    if float(region.max()) <= float(region.min()):
        raise ValueError("有效区域深度恒定，拒绝发布")
    arr = arr.copy()
    arr[~valid] = 0.0
    np.savez_compressed(stage / "depth.npz", depth=arr, valid=valid)
    shutil.copyfile(worker_out / "depth_raw.npy", stage / "depth_raw.npy")
    semantics = DepthSemantics(worker_metadata.get("semantics"))
    model_info = dict(worker_metadata.get("model", {}))
    return {
        "schema_version": 2,
        "depth_shape": list(arr.shape),
        "depth_dtype": "float32",
        "depth_semantics": semantics.value,
        "valid_coverage": coverage,
        "mask_used_for_inference": bool(worker_metadata.get("mask_used_for_inference", False)),
        "model": model_info,
        "runtime": {
            "device": worker_metadata.get("device"),
            "elapsed_s": worker_metadata.get("elapsed_s"),
            "torch": worker_metadata.get("torch"),
            "implementation": worker_metadata.get("implementation"),
        },
        "input_size": worker_metadata.get("input_size"),
        "output_shape": worker_metadata.get("output_shape"),
        "postprocess": worker_metadata.get("postprocess"),
        "warnings": [],
    }
