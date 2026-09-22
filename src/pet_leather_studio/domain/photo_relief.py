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
# 母版加底实体的底板厚度（对齐模具 backing_mm 工程口径；浮雕基准 0，底板另计）
BASE_THICKNESS_MM_RANGE = (1.0, 30.0)
# 局部结构调整：偏移与过渡半径（mm；过渡平滑即防尖峰）
LOCAL_OFFSET_MM_RANGE = (-20.0, 20.0)
TRANSITION_MM_RANGE = (0.0, 50.0)
# 蒙版边界背景过渡带（P2 复验 R1）：主体内部高度不变，主体外按最近有效
# 高度在带宽内平滑落至背景 0——不改变 valid 的统计语义，只做几何过渡。
FALLOFF_BAND_MM_RANGE = (0.0, 50.0)
DEFAULT_FALLOFF_BAND_MM = 2.5
# 过渡带宽度建议（P2 复验 R2）：smoothstep 坡面最陡 1.5×h/band，据此按解析
# 起伏给出最小带宽；版边保留平坦环带，过渡带不得抬起版面边缘。
FALLOFF_MAX_SLOPE = 1.0  # 建议坡度上限（mm/mm；1.0 = 45°）
FALLOFF_BORDER_CLEARANCE_MM = 2.0
# 参考标定稳健统计默认百分位（仅在选定有效正面区域与基准之后应用）
DEFAULT_PERCENTILE = 99.0
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
class ReferenceProfile:
    """参考标定结果（PH05）：显式口径的有效浮雕起伏，非包围盒 Z 跨度。

    分位数仅是选定"有效正面区域/基准"之后的稳健统计；真实极值必须保留
    （true_excess_mm 即被百分位裁掉的最高点超出量，界面须标出供核查）。
    bbox_z_span / bbox_z_span_ratio 分开记录、仅作历史对照，永不自动套用。
    全部字段为标量（domain 仅标准库）。
    """

    profile_id: str
    source_name: str
    source_path: str
    source_sha256: str
    source_units: str  # OBJ 无单位，假设必须显式记录（如 assumed_mm）
    region: tuple[float, float, float, float]  # xmin, xmax, ymin, ymax（源单位）
    region_basis: str  # 区域选择口径（如 full_xy_bounds_v1 / cli_override）
    datum_method: str  # 基准面口径（v1：min_z_plane 区域最低点平面）
    datum_z: float
    percentile: float
    exclusion_fraction: float
    effective_relief_mm: float  # 基准面 → 分位裁剪高度 = 有效参考起伏
    reference_width_mm: float  # 区域 X 跨度（同比例公式的"明确参考宽度"）
    true_min_z: float
    true_max_z: float
    true_excess_mm: float
    excluded_point_count: int
    bbox_z_span: float
    bbox_z_span_ratio: float
    measurement_algorithm: str
    created_at: str

    def validate(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id 不能为空")
        if not self.datum_method.strip() or not self.region_basis.strip():
            raise ValueError("region_basis 与 datum_method 必须显式记录口径")
        if not math.isfinite(self.percentile) or not 0.0 < self.percentile <= 100.0:
            raise ValueError("percentile 必须在 (0, 100] 范围")
        if not math.isfinite(self.exclusion_fraction) or not 0.0 <= self.exclusion_fraction < 1.0:
            raise ValueError("exclusion_fraction 必须在 [0, 1) 范围")
        if not math.isfinite(self.effective_relief_mm) or self.effective_relief_mm <= 0.0:
            raise ValueError("effective_relief_mm 必须为正的有限值")
        if not math.isfinite(self.reference_width_mm) or self.reference_width_mm <= 0.0:
            raise ValueError("reference_width_mm 必须为正的有限值")
        xmin, xmax, ymin, ymax = self.region
        if not all(math.isfinite(v) for v in self.region) or not xmin < xmax or not ymin < ymax:
            raise ValueError("region 必须满足 xmin<xmax 且 ymin<ymax")
        if self.true_excess_mm < 0.0 or self.excluded_point_count < 0:
            raise ValueError("true_excess_mm / excluded_point_count 不能为负")

    def to_json_dict(self) -> dict[str, Any]:
        data = {field: getattr(self, field) for field in self.__dataclass_fields__}
        data["region"] = list(self.region)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ReferenceProfile:
        region = data["region"]
        if not isinstance(region, (tuple, list)) or len(region) != 4:
            raise ValueError("region 必须是长度 4 的序列（xmin,xmax,ymin,ymax）")
        profile = cls(
            profile_id=str(data["profile_id"]),
            source_name=str(data["source_name"]),
            source_path=str(data["source_path"]),
            source_sha256=str(data["source_sha256"]),
            source_units=str(data["source_units"]),
            region=(float(region[0]), float(region[1]), float(region[2]), float(region[3])),
            region_basis=str(data["region_basis"]),
            datum_method=str(data["datum_method"]),
            datum_z=float(data["datum_z"]),
            percentile=float(data["percentile"]),
            exclusion_fraction=float(data["exclusion_fraction"]),
            effective_relief_mm=float(data["effective_relief_mm"]),
            reference_width_mm=float(data["reference_width_mm"]),
            true_min_z=float(data["true_min_z"]),
            true_max_z=float(data["true_max_z"]),
            true_excess_mm=float(data["true_excess_mm"]),
            excluded_point_count=int(data["excluded_point_count"]),
            bbox_z_span=float(data["bbox_z_span"]),
            bbox_z_span_ratio=float(data["bbox_z_span_ratio"]),
            measurement_algorithm=str(data["measurement_algorithm"]),
            created_at=str(data["created_at"]),
        )
        profile.validate()
        return profile


@dataclass(frozen=True)
class LocalAdjustment:
    """局部结构调整输入：刷选区域 PNG + 偏移 + 过渡（合同"参数与区域可撤销"
    在编辑器快照栈满足；本对象是随 build_master 落入母版修订的持久记录）。"""

    label: str
    region_png: str  # 单通道 PNG（工作图朝向），>127 视为选中
    offset_mm: float
    transition_mm: float

    def validate(self) -> None:
        if not self.label.strip():
            raise ValueError("局部调整 label 不能为空")
        if not self.region_png.strip():
            raise ValueError("region_png 不能为空")
        for name, (low, high) in (
            ("offset_mm", LOCAL_OFFSET_MM_RANGE),
            ("transition_mm", TRANSITION_MM_RANGE),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} 必须在 {low}–{high} 范围（单位 mm）")


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
    base_thickness_mm: float = 3.0  # 加底实体底板厚度；浮雕基准 0，底板另计
    falloff_band_mm: float = DEFAULT_FALLOFF_BAND_MM  # 蒙版边界过渡带宽；0=关闭（域外严格为 0）

    def validate(self) -> None:
        for name, (low, high) in (
            ("width_mm", WIDTH_MM_RANGE),
            ("depth_mm", DEPTH_MM_RANGE),
            ("base_thickness_mm", BASE_THICKNESS_MM_RANGE),
            ("falloff_band_mm", FALLOFF_BAND_MM_RANGE),
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


def suggested_falloff_band_mm(depth_mm: float) -> float:
    """按解析最大起伏给出建议过渡带宽（P2 复验 R2）。

    smoothstep 坡面最陡斜率 = 1.5×h/band ≤ FALLOFF_MAX_SLOPE ⇒ band ≥ 1.5×h；
    向上取整到 0.1 mm 保证界仍成立，再封顶到带宽上限。仅是工程建议（起点），
    审美取舍由用户在对照渲染中选定，不由本函数替代。
    """

    depth = float(depth_mm)
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValueError("建议带宽需要正的有限起伏深度")
    band = math.ceil(1.5 * depth / FALLOFF_MAX_SLOPE * 10.0) / 10.0
    return min(band, FALLOFF_BAND_MM_RANGE[1])
