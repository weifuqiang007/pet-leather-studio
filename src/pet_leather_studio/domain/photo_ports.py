"""照片管线端口：以路径与可序列化元数据跨进程/层传递，不传 GPU 对象。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from pet_leather_studio.domain.photo_relief import MaskMethod


class PhotoIOPort(Protocol):
    def prepare_import(self, source: Path, stage: Path) -> dict[str, Any]: ...

    def prepare_mask(
        self,
        stage: Path,
        mask_png: Path,
        photo_metadata: Mapping[str, Any],
        method: MaskMethod,
        threshold_level: int | None,
        notes: str | None,
    ) -> dict[str, Any]: ...


class DepthInferencePort(Protocol):
    def run_and_stage(
        self, image: Path, mask: Path, model_dir: Path, stage: Path
    ) -> dict[str, Any]:
        """执行真实推理并把 depth.npz 与元数据写入 staging；失败必须抛错。"""
        ...


class ModelRegistryPort(Protocol):
    def locate(self, model_id: str | None) -> Path: ...
