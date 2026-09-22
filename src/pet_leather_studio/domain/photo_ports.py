"""照片管线端口：以路径与可序列化元数据跨进程/层传递，不传 GPU 对象。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pet_leather_studio.domain.photo_relief import (
    LocalAdjustment,
    MaskMethod,
    ReferenceProfile,
    ReliefParameters,
)


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


class ReliefGeometryPort(Protocol):
    def build_master(
        self,
        depth_npz: Path,
        depth_metadata: Mapping[str, Any],
        parameters: ReliefParameters,
        profile: ReferenceProfile | None,
        adjustments: Sequence[LocalAdjustment],
        stage: Path,
        photo_png: Path | None = None,
    ) -> dict[str, Any]:
        """受控浮雕化并导出母版修订文件；校验失败必须抛错（不产出成功修订）。"""
        ...


class ReferenceProfilePort(Protocol):
    def load(self, profile_id: str) -> ReferenceProfile:
        """按 id 载入标定；缺失/损坏须显式报错（不得静默回退）。"""
        ...

    def list_profiles(self) -> list[ReferenceProfile]: ...
