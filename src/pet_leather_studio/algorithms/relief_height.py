"""有效区域归一化、深度方向适配、Y 翻转与起伏上限；纯数值，禁止 IO 副作用。"""

from __future__ import annotations

import numpy as np

from pet_leather_studio.domain.photo_relief import DepthSemantics

MIN_VALID_FRACTION = 0.005  # 有效面积低于该比例视为空有效域（工程阈值，非物理量）


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
