"""隔离推理进程调用、模型清单校验与深度修订组装。

- 不在本模块导入时下载或加载权重；正常产品路径零网络访问。
- worker 运行于 .venv-photo 独立环境（scripts/photo_inference_worker.py）。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pet_leather_studio.domain.errors import ResourceMissingError, ToolUnavailableError
from pet_leather_studio.domain.photo_relief import DepthSemantics
from pet_leather_studio.infrastructure.photo_io import MASK_BINARY_THRESHOLD

KNOWN_MODEL_ID = "depth-anything-v2-small-hf"
SETUP_COMMAND = "scripts/setup_photo_models.py bootstrap && scripts/setup_photo_models.py download"


class ModelRegistry:
    """models/<provider>/<model>/<revision>/ 本地清单与 SHA-256 校验。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _revisions(self, model_id: str) -> list[Path]:
        parent = self.root / "hf" / model_id
        if not parent.is_dir():
            return []
        return sorted((p for p in parent.iterdir() if p.is_dir()), key=lambda p: p.name)

    def locate(self, model_id: str | None) -> Path:
        model = model_id or KNOWN_MODEL_ID
        revisions = self._revisions(model)
        if not revisions:
            raise ResourceMissingError(
                f"模型 {model} 未安装；请先运行：{SETUP_COMMAND}（显式下载，产品路径不联网）"
            )
        latest = revisions[-1]
        self.verify(latest)
        return latest

    def verify(self, model_dir: Path) -> dict[str, Any]:
        manifest_path = model_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ResourceMissingError(f"模型清单缺失：{manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest.get("files", {}).items():
            path = model_dir / name
            if not path.is_file():
                raise ResourceMissingError(f"模型文件缺失：{name}（目录 {model_dir}）")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != expected.get("sha256"):
                raise ResourceMissingError(
                    f"模型文件损坏（hash 不匹配）：{name}；请重新运行下载或校验命令"
                )
        return manifest


class DepthWorker:
    """以参数列表启动隔离进程执行真实推理；不拼 shell、不加载权重到本进程。"""

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
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
            raise RuntimeError(f"推理进程失败（exit {result.returncode}）：\n" + "\n".join(tail))
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
    """校验 worker 输出并把 depth.npz（数据+有效域）写入 staging。"""
    depth = np.load(worker_out / "depth_raw.npy")
    arr = np.asarray(depth, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"深度输出必须为二维，收到 shape={arr.shape}")
    with Image.open(mask_png) as image:
        mask = np.asarray(image.convert("L"))
    if arr.shape != mask.shape:
        raise ValueError(f"深度输出形状 {arr.shape} 与蒙版 {mask.shape} 不一致")
    valid = (mask > MASK_BINARY_THRESHOLD) & np.isfinite(arr)
    if int(valid.sum()) == 0:
        raise ValueError("有效区域为空（蒙版为空或深度输出全无效）")
    region = arr[valid].astype(np.float64)
    if float(region.max()) <= float(region.min()):
        raise ValueError("有效区域深度恒定，拒绝发布")
    arr = arr.copy()
    arr[~valid] = 0.0
    np.savez_compressed(stage / "depth.npz", depth=arr, valid=valid)
    semantics = DepthSemantics(worker_metadata.get("semantics"))
    model_info = dict(worker_metadata.get("model", {}))
    return {
        "schema_version": 2,
        "depth_shape": list(arr.shape),
        "depth_dtype": "float32",
        "depth_semantics": semantics.value,
        "valid_coverage": float(valid.mean()),
        "mask_used_for_inference": bool(worker_metadata.get("mask_used_for_inference", False)),
        "model": model_info,
        "runtime": {
            "device": worker_metadata.get("device"),
            "elapsed_s": worker_metadata.get("elapsed_s"),
            "torch": worker_metadata.get("torch"),
            "implementation": worker_metadata.get("implementation"),
        },
        "warnings": [],
    }
