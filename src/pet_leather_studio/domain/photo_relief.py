"""照片浮雕域描述：阶段、蒙版方式、深度语义、修订摘要与浮雕参数。

仅标准库与本包 domain 导入（分层规则）；数值范围是工程输入边界，
不解释为物理安全范围（沿用 MoldParameters 口径）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

WIDTH_MM_RANGE = (5.0, 300.0)
DEPTH_MM_RANGE = (0.05, 20.0)
SMOOTHING_RADIUS_MM_RANGE = (0.0, 50.0)
# 深度发布时的最小有效覆盖率（工程阈值，PH04：面积不足明确报错）
MIN_DEPTH_VALID_COVERAGE = 0.01


class PhotoStage(StrEnum):
    """流程阶段仅描述进度，不代表任何质量验收通过。"""

    IMPORTED = "imported"
    MASKED = "masked"
    DEPTH_DONE = "depth_done"
    MASTER = "master"


class MaskMethod(StrEnum):
    MANUAL = "manual"
    THRESHASSISTED = "threshold_assisted"


class DepthSemantics(StrEnum):
    """推理输出原生语义：必须先记录再适配，禁止靠肉眼临时取反。"""

    RELATIVE_LARGER_NEARER = "relative_larger_nearer"
    RELATIVE_LARGER_FARTHER = "relative_larger_farther"


class HeightMode(StrEnum):
    EXPLICIT_DEPTH = "explicit_depth"
    REFERENCE_RATIO = "reference_ratio"


@dataclass(frozen=True)
class RevisionSummary:
    """跨层修订描述；完整元数据以 manifest 为准。"""

    revision_id: str
    kind: str
    parent_id: str | None
    created_at: str
    input_method: str | None = None
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> RevisionSummary:
        return cls(
            revision_id=str(metadata["id"]),
            kind=str(metadata["kind"]),
            parent_id=metadata.get("parent_id"),
            created_at=str(metadata.get("created_at", "")),
            input_method=metadata.get("input_method"),
            warnings=tuple(metadata.get("warnings", ())),
        )


@dataclass(frozen=True)
class ReliefParameters:
    """浮雕化设计参数（P2 生效；P1 仅使用 explicit_depth 预览子集）。

    整体深度、局部偏移、细节强度、平滑程度分开存储；
    smoothing_radius_mm 以毫米计，UI 须显示对应像素换算。
    """

    width_mm: float = 60.0
    depth_mm: float = 2.0
    height_mode: HeightMode = HeightMode.EXPLICIT_DEPTH
    profile_id: str | None = None
    smoothing_radius_mm: float | None = None
    detail_strength: float = 0.0

    def validate(self) -> None:
        for name, (low, high) in (
            ("width_mm", WIDTH_MM_RANGE),
            ("depth_mm", DEPTH_MM_RANGE),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} 必须在 {low}–{high} 范围")
        if self.height_mode is HeightMode.REFERENCE_RATIO and not self.profile_id:
            raise ValueError("reference_ratio 模式必须提供已标定的 profile_id；不会暗用参考比例")
        if self.smoothing_radius_mm is not None and not (
            SMOOTHING_RADIUS_MM_RANGE[0] < self.smoothing_radius_mm <= SMOOTHING_RADIUS_MM_RANGE[1]
        ):
            raise ValueError("smoothing_radius_mm 超出允许范围（单位 mm）")
        if not math.isfinite(self.detail_strength) or self.detail_strength < 0.0:
            raise ValueError("detail_strength 不能为负")
