"""有效区域归一化、深度方向适配、Y 翻转与起伏上限；纯数值，禁止 IO 副作用。

受控浮雕化（controlled_heights_mm）是预览与导出共用的唯一数值管线（PH10
一致性）：平滑、比例/显式上限解析、局部偏移与限幅都在此发生并记录 report。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import ndimage

from pet_leather_studio.domain.photo_relief import (
    DEPTH_MM_RANGE,
    DepthSemantics,
    HeightMode,
    ReferenceProfile,
    ReliefParameters,
)

MIN_VALID_FRACTION = 0.005  # 有效面积低于该比例视为空有效域（工程阈值，非物理量）
SMOOTHING_DENOM_EPS = 1e-6  # 归一化卷积分母下限：邻域有效权重不足时保留原值


def unit_height(
    depth: np.ndarray,
    valid: np.ndarray,
    semantics: DepthSemantics,
    min_valid_fraction: float = MIN_VALID_FRACTION,
) -> np.ndarray:
    """把原生深度映射为 0–1 高度（1=最凸）；无效点置 0 且不参与任何统计。"""
    depth = np.asarray(depth, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if depth.shape != valid.shape or depth.ndim != 2:
        raise ValueError("深度与有效域形状不一致或不是二维")
    if int(valid.sum()) < max(1, round(valid.size * min_valid_fraction)):
        raise ValueError("有效面积不足，无法归一化")
    region = depth[valid]
    if not np.isfinite(region).all():
        raise ValueError("有效区域包含 NaN/Inf")
    low, high = float(region.min()), float(region.max())
    if high <= low:
        raise ValueError("有效区域深度恒定，无法建立高度关系")
    unit = (depth - low) / (high - low)
    if semantics is DepthSemantics.RELATIVE_LARGER_NEARER:
        pass
    elif semantics is DepthSemantics.RELATIVE_LARGER_FARTHER:
        unit = 1.0 - unit
    else:  # pragma: no cover - 枚举扩充时的防御
        raise ValueError(f"未知深度语义：{semantics}")
    return np.where(valid, unit, 0.0)


def cap_to_mm(unit: np.ndarray, depth_mm: float) -> np.ndarray:
    """0–1 高度 × 起伏上限（mm）；输出非负、有限且不超过上限。"""
    heights = np.asarray(unit, dtype=np.float64) * float(depth_mm)
    if not np.isfinite(heights).all():
        raise ValueError("高度含非有限值")
    return np.clip(heights, 0.0, float(depth_mm))


def clamp_cap(heights_mm: np.ndarray, depth_mm: float) -> tuple[np.ndarray, dict[str, float]]:
    """上限约束（局部编辑后仍须生效）；返回截断统计，调用方必须展示，不得静默。"""
    heights = np.asarray(heights_mm, dtype=np.float64)
    over = heights > depth_mm
    clamped = np.minimum(heights, float(depth_mm))
    report = {
        "clamped_points": int(over.sum()),
        "max_before_mm": float(heights.max()) if heights.size else 0.0,
        "cap_mm": float(depth_mm),
    }
    return clamped, report


def image_to_geometry_rows(array: np.ndarray) -> np.ndarray:
    """工作图 y 向下 → 几何 y 向上：行序翻转（显式转换，禁止靠肉眼取反）。"""
    return np.asarray(array)[::-1]


def ratio_depth_mm(effective_relief_mm: float, reference_width_mm: float, width_mm: float) -> float:
    """同比例参考模式（PH05）：有效参考起伏 / 参考宽度 × 当前宽度。

    结果即该模式的起伏上限；越出工程范围时报错并提示改用 explicit_depth
    （合同：参考部位与目标部位不对应时须提示用户选显式深度，不自动缩放）。
    """
    effective = float(effective_relief_mm)
    reference = float(reference_width_mm)
    if not math.isfinite(effective) or not math.isfinite(reference) or reference <= 0.0:
        raise ValueError("reference_width_mm 必须为正的有限值")
    depth = effective / reference * float(width_mm)
    low, high = DEPTH_MM_RANGE
    if not low <= depth <= high:
        raise ValueError(
            f"reference_ratio 换算起伏 {depth:.3f} mm 超出工程范围 {low}–{high} mm；"
            "参考部位与目标部位可能不对应，请改用 explicit_depth 显式给定深度"
        )
    return depth


def smooth_valid_aware(unit: np.ndarray, valid: np.ndarray, sigma_px: float) -> np.ndarray:
    """有效域感知高斯平滑：分母为邻域有效权重，无效像素不拖低有效边缘。"""
    unit = np.asarray(unit, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if unit.shape != valid.shape:
        raise ValueError("unit 与 valid 形状不一致")
    if not math.isfinite(sigma_px) or sigma_px <= 0.0:
        raise ValueError("sigma_px 必须为正的有限值")
    weights = valid.astype(np.float64)
    numerator = ndimage.gaussian_filter(unit * weights, sigma_px, mode="nearest")
    denominator = ndimage.gaussian_filter(weights, sigma_px, mode="nearest")
    smoothed = np.where(
        denominator > SMOOTHING_DENOM_EPS,
        numerator / np.maximum(denominator, SMOOTHING_DENOM_EPS),
        unit,
    )
    return np.where(valid, smoothed, 0.0)


def apply_local_adjustments(
    heights_mm: np.ndarray,
    adjustments: Sequence[tuple[np.ndarray, float, float]],
    dx_mm: float,
) -> np.ndarray:
    """逐条施加局部偏移：h += offset × 高斯过渡(区域蒙版)。

    过渡 σ_px = transition_mm / dx_mm（mm→px 换算，调用方 report 须记录）；
    平滑过渡带即防尖峰。区域为 0–1 蒙版（工作图朝向，与 heights 同形）。
    """
    heights = np.asarray(heights_mm, dtype=np.float64).copy()
    if not math.isfinite(dx_mm) or dx_mm <= 0.0:
        raise ValueError("dx_mm 必须为正的有限值")
    for region, offset_mm, transition_mm in adjustments:
        region_arr = np.asarray(region, dtype=np.float64)
        if region_arr.shape != heights.shape:
            raise ValueError(f"局部调整区域形状 {region_arr.shape} 与高度场 {heights.shape} 不一致")
        if region_arr.size and (region_arr.min() < 0.0 or region_arr.max() > 1.0):
            raise ValueError("局部调整区域必须在 0–1 范围")
        sigma_px = float(transition_mm) / dx_mm
        falloff = (
            ndimage.gaussian_filter(region_arr, sigma_px, mode="nearest")
            if sigma_px > 0.0
            else region_arr
        )
        heights = heights + float(offset_mm) * falloff
    return heights


def edge_falloff(
    heights_mm: np.ndarray,
    valid: np.ndarray,
    band_mm: float,
    dx_mm: float,
    dy_mm: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """蒙版边界背景过渡带（P2 复验 R1）：把垂直墙改为平滑落地。

    主体内部高度逐点不变；域外像素取最近有效像素高度，沿带宽 band_mm 按
    smoothstep 反函数衰减到背景 0（边界处导数为 0，中段最陡 ≈ 1.5×h/band）。
    不改变 valid 的统计语义（归一化/平滑仍只看有效域）；被抬升的域外范围
    与最大抬升量记入 report 供 manifest 与界面展示。
    """

    heights = np.asarray(heights_mm, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if heights.shape != valid.shape:
        raise ValueError("heights 与 valid 形状不一致")
    report: dict[str, Any] = {
        "band_mm": float(band_mm),
        "algorithm": "edge-falloff-smoothstep-v1",
        "raised_points": 0,
        "max_raised_mm": 0.0,
        "enabled": False,
    }
    if band_mm <= 0.0 or valid.all() or not valid.any():
        return heights.copy(), report
    distance, nearest = ndimage.distance_transform_edt(
        ~valid, sampling=(dy_mm, dx_mm), return_indices=True
    )
    edge_heights = heights[nearest[0], nearest[1]]  # 域外像素的最近有效高度
    t = np.clip(distance / float(band_mm), 0.0, 1.0)
    decay = 1.0 - (3.0 * t * t - 2.0 * t * t * t)  # smoothstep 反向：d→0 取 1，d=band 取 0
    raised = (~valid) & (distance <= band_mm)
    result = heights.copy()
    result[raised] = edge_heights[raised] * decay[raised]
    report["enabled"] = True
    report["raised_points"] = int(raised.sum())
    report["max_raised_mm"] = float(result[raised].max()) if raised.any() else 0.0
    return result, report


def background_clearance_mm(valid: np.ndarray, dx_mm: float, dy_mm: float) -> float:
    """版面边框（无效像素）到有效域（主体）的最小距离 mm（P2 复验 R2）。

    过渡带宽超过该距离会抬起版面边缘（版边应保持平坦以便夹持/裁切），
    GUI 据此收窄建议带宽并提示。主体已贴版边（边框存在有效像素）时平边
    前提本身不成立——返回 inf 表示无余量约束，由调用方另行提示贴边；
    全有效域（无背景，过渡带无作用）返回 0；空有效域返回 inf（上游
    归一化早已拒绝，此处仅保持函数完备）。
    """

    valid = np.asarray(valid, dtype=bool)
    if valid.all():
        return 0.0
    if not valid.any():
        return float("inf")
    border_mask = np.zeros_like(valid)
    border_mask[0, :] = border_mask[-1, :] = True
    border_mask[:, 0] = border_mask[:, -1] = True
    if (valid & border_mask).any():
        return float("inf")  # 主体贴版边：平边已无法保证，不构成带宽约束
    distance = ndimage.distance_transform_edt(~valid, sampling=(float(dy_mm), float(dx_mm)))
    border = np.concatenate([distance[0, :], distance[-1, :], distance[:, 0], distance[:, -1]])
    return float(border.min())


def slope_report(
    heights_mm: np.ndarray, valid: np.ndarray, dx_mm: float, dy_mm: float
) -> dict[str, Any]:
    """顶面坡度统计（P2 复验 R2）：按相邻单元高差/间距分类计数。

    interior = 两端皆有效（输入深度固有断层指标）；boundary = 恰一端有效
    （过渡带落地坡度）；overall 含背景（裙边外缘等）。角度 = atan(斜率)。
    无某类相邻对时该项记 0。
    """

    heights = np.asarray(heights_mm, dtype=np.float64)
    valid = np.asarray(valid, dtype=bool)
    if heights.shape != valid.shape:
        raise ValueError("heights 与 valid 形状不一致")

    def _maxdeg(slope: float) -> float:
        return math.degrees(math.atan(slope))

    overall = interior = boundary = 0.0
    for axis, spacing in ((0, float(dy_mm)), (1, float(dx_mm))):
        drop = np.abs(np.diff(heights, axis=axis)) / spacing
        head = (slice(None),) * axis + (slice(0, -1),)
        tail = (slice(None),) * axis + (slice(1, None),)
        both_valid = valid[head] & valid[tail]
        overall = max(overall, float(drop.max()) if drop.size else 0.0)
        interior = max(interior, float(drop[both_valid].max()) if both_valid.any() else 0.0)
        cross = valid[head] ^ valid[tail]
        boundary = max(boundary, float(drop[cross].max()) if cross.any() else 0.0)
    return {
        "max_overall_mm_per_mm": overall,
        "max_overall_deg": _maxdeg(overall),
        "interior_max_mm_per_mm": interior,
        "interior_max_deg": _maxdeg(interior),
        "boundary_max_mm_per_mm": boundary,
        "boundary_max_deg": _maxdeg(boundary),
    }


def controlled_heights_mm(
    depth: np.ndarray,
    valid: np.ndarray,
    semantics: DepthSemantics,
    parameters: ReliefParameters,
    profile: ReferenceProfile | None = None,
    adjustments: Sequence[tuple[np.ndarray, float, float]] = (),
) -> tuple[np.ndarray, dict[str, Any]]:
    """受控浮雕化主数值管线（预览与导出共用，保证 PH10 一致）。

    unit_height → 有效域感知平滑 → 起伏上限解析（explicit_depth /
    reference_ratio）→ cap_to_mm → 边缘过渡带（主体外平滑落地）→ 局部偏移
    → 上下限限幅；返回工作图朝向 heights_mm 与 report（mm↔px 换算、上限
    来源、过渡与限幅统计；调用方必须展示限幅对用户操作的改动，不得静默
    截断）。局部调整不得拔高整个主体：偏移只经高斯过渡作用在刷选区域内。
    """
    parameters.validate()
    unit = unit_height(depth, valid, semantics)
    ny, nx = unit.shape
    dx_mm = float(parameters.width_mm) / max(nx - 1, 1)
    dy_mm = dx_mm * ny / max(ny - 1, 1)  # 与 photo_geometry 的 height_mm=width×ny/nx 同口径
    report: dict[str, Any] = {"dx_mm": dx_mm, "grid": [int(ny), int(nx)]}

    if parameters.smoothing_radius_mm is not None and parameters.smoothing_radius_mm > 0.0:
        sigma_px = float(parameters.smoothing_radius_mm) / dx_mm
        unit = smooth_valid_aware(unit, np.asarray(valid, dtype=bool), sigma_px)
        report["smoothing"] = {
            "radius_mm": float(parameters.smoothing_radius_mm),
            "sigma_px": sigma_px,
            "dx_mm": dx_mm,
        }

    if parameters.height_mode is HeightMode.REFERENCE_RATIO:
        if profile is None:
            raise ValueError("reference_ratio 模式必须提供已标定的 ReferenceProfile")
        depth_cap = ratio_depth_mm(
            profile.effective_relief_mm, profile.reference_width_mm, parameters.width_mm
        )
        report["depth_source"] = "reference_ratio"
        report["profile_id"] = profile.profile_id
    else:
        depth_cap = float(parameters.depth_mm)
        report["depth_source"] = "explicit_depth"
    report["resolved_depth_mm"] = depth_cap

    heights = cap_to_mm(unit, depth_cap)
    heights, falloff = edge_falloff(
        heights, np.asarray(valid, dtype=bool), parameters.falloff_band_mm, dx_mm, dy_mm
    )
    report["falloff"] = falloff
    heights = apply_local_adjustments(heights, adjustments, dx_mm)
    heights, clamp = clamp_cap(heights, depth_cap)
    below = heights < 0.0  # 负向偏移不得挖穿浮雕基准 0（底板另计，不在此补偿）
    heights = np.maximum(heights, 0.0)
    clamp["clamped_below_points"] = int(below.sum())
    report["clamp"] = clamp
    report["adjustments_count"] = len(adjustments)
    report["slope"] = slope_report(heights, np.asarray(valid, dtype=bool), dx_mm, dy_mm)
    return heights, report
