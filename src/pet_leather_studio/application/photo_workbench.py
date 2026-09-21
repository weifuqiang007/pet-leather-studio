"""照片导入、人工蒙版、隔离深度推理与修订发布用例；依赖注入端口。

不写模型或 UI 算法；发布前校验上游 hash；失败/取消不产生成功修订。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pet_leather_studio.domain.errors import UnsupportedOperationError
from pet_leather_studio.domain.molds import RevisionPort
from pet_leather_studio.domain.photo_ports import (
    DepthInferencePort,
    ModelRegistryPort,
    PhotoIOPort,
    ReferenceProfilePort,
    ReliefGeometryPort,
)
from pet_leather_studio.domain.photo_relief import (
    HeightMode,
    LocalAdjustment,
    MaskMethod,
    ReliefParameters,
    RevisionSummary,
)

CAMERA_VIEW_NOTE = (
    "深度为相机视角下的相对前后关系；未做姿态归一化或正面化（P1 边界，"
    "趴卧/侧躺姿态会把身体厚度映射为起伏）"
)
AUTO_SEGMENT_NOTE = "自动分割未配置（P1 交付为人工蒙版）；请使用蒙版编辑器后再运行深度推理"


class PhotoWorkbench:
    def __init__(
        self,
        store: RevisionPort,
        photo_io: PhotoIOPort,
        inference: DepthInferencePort,
        registry: ModelRegistryPort,
        geometry: ReliefGeometryPort,
        profiles: ReferenceProfilePort,
    ) -> None:
        self.store = store
        self.photo_io = photo_io
        self.inference = inference
        self.registry = registry
        self.geometry = geometry
        self.profiles = profiles

    def import_photo(self, source: Path) -> RevisionSummary:
        stage = self.store.begin()
        try:
            metadata = self.photo_io.prepare_import(source, stage)
            metadata.update(kind="photo", parent_id=None, visual_review="pending")
            published = self.store.publish(stage, metadata)
            return RevisionSummary.from_metadata(published)
        except BaseException:
            self.store.discard(stage)
            raise

    def save_mask(
        self,
        photo_id: str,
        mask_png: Path,
        method: MaskMethod,
        *,
        threshold_level: int | None = None,
        notes: str | None = None,
    ) -> RevisionSummary:
        photo = self.store.get(photo_id)
        if photo.get("kind") != "photo":
            raise ValueError(f"修订 {photo_id[:8]} 不是 photo（{photo.get('kind')}），不能挂蒙版")
        self.store.verify(photo_id)
        stage = self.store.begin()
        try:
            metadata = self.photo_io.prepare_mask(
                stage, mask_png, photo, method, threshold_level, notes
            )
            metadata.update(
                kind="mask",
                parent_id=photo_id,
                photo_id=photo_id,
                visual_review="pending",
            )
            published = self.store.publish(stage, metadata)
            return RevisionSummary.from_metadata(published)
        except BaseException:
            self.store.discard(stage)
            raise

    def segment_photo(self, photo_id: str, model_id: str | None = None) -> RevisionSummary:
        """预留接口：自动分割未配置时显式拒绝，不以人工结果冒充。"""
        raise UnsupportedOperationError(AUTO_SEGMENT_NOTE)

    def estimate_depth(
        self, photo_id: str, mask_id: str, model_id: str | None = None
    ) -> RevisionSummary:
        photo = self.store.get(photo_id)
        mask = self.store.get(mask_id)
        if photo.get("kind") != "photo":
            raise ValueError(f"修订 {photo_id[:8]} 不是 photo（{photo.get('kind')}）")
        if mask.get("kind") != "mask":
            raise ValueError(f"修订 {mask_id[:8]} 不是 mask（{mask.get('kind')}）")
        if mask.get("photo_id") != photo_id:
            raise ValueError("蒙版与照片来源不一致（photo_id 不同），拒绝混用")
        self.store.verify(photo_id)
        self.store.verify(mask_id)
        model_dir = self.registry.locate(model_id)
        stage = self.store.begin()
        try:
            metadata = self.inference.run_and_stage(
                image=self.store.directory(photo_id) / "work.png",
                mask=self.store.directory(mask_id) / "mask.png",
                model_dir=model_dir,
                stage=stage,
            )
            metadata.update(
                kind="depth",
                parent_id=mask_id,
                photo_id=photo_id,
                mask_id=mask_id,
                visual_review="pending",
                manufacturing_validated=False,
            )
            metadata["warnings"] = [*metadata.get("warnings", []), CAMERA_VIEW_NOTE]
            # 发布前再次校验上游未被篡改
            self.store.verify(photo_id)
            self.store.verify(mask_id)
            published = self.store.publish(stage, metadata)
            return RevisionSummary.from_metadata(published)
        except BaseException:
            self.store.discard(stage)
            raise

    def build_master(
        self,
        depth_id: str,
        parameters: ReliefParameters,
        adjustments: Sequence[LocalAdjustment] = (),
    ) -> RevisionSummary:
        """受控浮雕化：depth 修订 → master 母版修订（几何校验失败不发布）。"""
        depth = self.store.get(depth_id)
        if depth.get("kind") != "depth":
            raise ValueError(f"修订 {depth_id[:8]} 不是 depth（{depth.get('kind')}），不能生成母版")
        parameters.validate()
        for adjustment in adjustments:
            adjustment.validate()
        profile = None
        if parameters.height_mode is HeightMode.REFERENCE_RATIO:
            if not parameters.profile_id:
                raise ValueError("reference_ratio 模式必须提供已标定的 profile_id")
            profile = self.profiles.load(parameters.profile_id)  # 缺失/损坏显式报错
        photo_id = depth.get("photo_id")
        mask_id = depth.get("mask_id")
        for upstream in (photo_id, mask_id, depth_id):
            if upstream:
                self.store.verify(upstream)
        stage = self.store.begin()
        try:
            metadata = self.geometry.build_master(
                depth_npz=self.store.directory(depth_id) / "depth.npz",
                depth_metadata=depth,
                parameters=parameters,
                profile=profile,
                adjustments=adjustments,
                stage=stage,
            )
            metadata.update(
                kind="master",
                parent_id=depth_id,
                photo_id=photo_id,
                mask_id=mask_id,
                depth_id=depth_id,
                input_method="photo_reconstruction",
                visual_review="pending",
                manufacturing_validated=False,
            )
            for upstream in (photo_id, mask_id, depth_id):  # 发布前复验上游未被篡改
                if upstream:
                    self.store.verify(upstream)
            published = self.store.publish(stage, metadata)
            return RevisionSummary.from_metadata(published)
        except BaseException:
            self.store.discard(stage)
            raise
