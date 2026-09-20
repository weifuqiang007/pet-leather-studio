"""照片链集成测试共用桩（仅 tests/ 内使用）：确定性梯度深度，不联网不加载权重。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def make_photo_png(path: Path, width: int = 80, height: int = 60) -> Path:
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[height // 6 : height * 5 // 6, width // 5 : width * 4 // 5] = (120, 90, 60)
    Image.fromarray(arr).save(path, format="PNG")
    return path


def make_mask_png(path: Path, width: int = 80, height: int = 60) -> Path:
    arr = np.zeros((height, width), dtype=np.uint8)
    arr[height // 5 : height * 4 // 5, width // 5 : width * 4 // 5] = 255
    Image.fromarray(arr, mode="L").save(path)
    return path


class StubInference:
    """DepthInferencePort 测试桩：行号越大值越大（relative_larger_nearer）。

    mode="fail" 抛异常；mode="crash" 写入半成品后崩溃——验证失败不留修订。
    """

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.calls: list[dict[str, str]] = []

    def run_and_stage(
        self, image: Path, mask: Path, model_dir: Path, stage: Path
    ) -> dict[str, Any]:
        self.calls.append({"image": str(image), "mask": str(mask), "model_dir": str(model_dir)})
        if self.mode == "fail":
            raise ValueError("测试桩：推理故意失败")
        if self.mode == "crash":
            (stage / "depth.npz").write_text("partial")
            raise RuntimeError("测试桩：推理中途崩溃")
        with Image.open(mask) as image_file:
            valid = np.asarray(image_file.convert("L")) > 127
        height, width = valid.shape
        rows = np.linspace(0.2, 0.8, height, dtype=np.float32)[:, None]
        depth = np.repeat(rows, width, axis=1)
        depth[~valid] = 0.0
        np.savez_compressed(stage / "depth.npz", depth=depth, valid=valid)
        return {
            "schema_version": 2,
            "depth_shape": [height, width],
            "depth_dtype": "float32",
            "depth_semantics": "relative_larger_nearer",
            "valid_coverage": float(valid.mean()),
            "mask_used_for_inference": False,
            "model": {"model_id": "stub-test", "revision": "stub"},
            "runtime": {
                "device": "stub",
                "elapsed_s": 0.01,
                "torch": "stub",
                "implementation": "stub",
            },
            "warnings": [],
        }


class StubRegistry:
    """ModelRegistryPort 测试桩：locate 恒成功（真注册表见 test_photo_inference.py）。"""

    def __init__(self) -> None:
        self.located: list[str | None] = []

    def locate(self, model_id: str | None) -> Path:
        self.located.append(model_id)
        return Path("/stub-model-dir")
