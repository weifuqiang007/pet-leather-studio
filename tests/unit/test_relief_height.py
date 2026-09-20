"""PH03/PH04：深度语义适配、无效域隔离、Y 行翻转、起伏上限误差与参数边界。"""

import numpy as np
import pytest

from pet_leather_studio.algorithms.relief_height import (
    cap_to_mm,
    clamp_cap,
    image_to_geometry_rows,
    unit_height,
)
from pet_leather_studio.domain.photo_relief import (
    DepthSemantics,
    HeightMode,
    ReliefParameters,
)


def _ramp(rows: int = 12, cols: int = 8) -> np.ndarray:
    """行号越大越“近”（值越大）的已知梯度。"""
    return np.repeat(np.linspace(1.0, 11.0, rows)[:, None], cols, axis=1)


def test_unit_height_ramp_near_semantics() -> None:
    valid = np.ones((12, 8), dtype=bool)
    unit = unit_height(_ramp(), valid, DepthSemantics.RELATIVE_LARGER_NEARER)
    np.testing.assert_allclose(unit[0, :], 0.0, atol=1e-12)
    np.testing.assert_allclose(unit[-1, :], 1.0, atol=1e-12)
    np.testing.assert_allclose(unit[6, :], 6 / 11, atol=1e-12)


def test_unit_height_farther_semantics_inverts() -> None:
    valid = np.ones((12, 8), dtype=bool)
    near = unit_height(_ramp(), valid, DepthSemantics.RELATIVE_LARGER_NEARER)
    far = unit_height(_ramp(), valid, DepthSemantics.RELATIVE_LARGER_FARTHER)
    np.testing.assert_allclose(far, 1.0 - near, atol=1e-12)


def test_invalid_region_excluded_from_stats_and_output() -> None:
    depth = _ramp()
    valid = np.zeros((12, 8), dtype=bool)
    valid[2:10] = True
    region = depth[2:10]
    low, high = region.min(), region.max()

    poisoned = depth.copy()
    poisoned[~valid] = 1e9  # 无效区垃圾极值
    poisoned[0, 0] = np.nan  # 无效区 NaN 也不影响统计
    unit = unit_height(poisoned, valid, DepthSemantics.RELATIVE_LARGER_NEARER)
    assert np.all(unit[~valid] == 0.0)  # 无效点输出严格为 0
    expected = (depth - low) / (high - low)
    np.testing.assert_allclose(unit[valid], expected[valid], atol=1e-12)


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_nonfinite_inside_valid_rejected(bad: float) -> None:
    depth = _ramp()
    depth[5, 3] = bad
    with pytest.raises(ValueError, match="NaN/Inf"):
        unit_height(depth, np.ones((12, 8), dtype=bool), DepthSemantics.RELATIVE_LARGER_NEARER)


def test_constant_valid_depth_rejected() -> None:
    with pytest.raises(ValueError, match="恒定"):
        unit_height(
            np.full((6, 6), 3.3), np.ones((6, 6), dtype=bool), DepthSemantics.RELATIVE_LARGER_NEARER
        )


def test_insufficient_valid_area_rejected() -> None:
    valid = np.zeros((100, 100), dtype=bool)
    valid[0, :2] = True  # 0.02% < 0.5% 阈值
    with pytest.raises(ValueError, match="有效面积不足"):
        unit_height(
            np.random.default_rng(7).random((100, 100)),
            valid,
            DepthSemantics.RELATIVE_LARGER_NEARER,
        )


def test_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="形状不一致"):
        unit_height(_ramp(), np.ones((5, 5), dtype=bool), DepthSemantics.RELATIVE_LARGER_NEARER)


def test_cap_to_mm_known_ramp_error_bound() -> None:
    unit = unit_height(_ramp(), np.ones((12, 8), dtype=bool), DepthSemantics.RELATIVE_LARGER_NEARER)
    heights = cap_to_mm(unit, 2.0)
    assert heights.max() == pytest.approx(2.0, abs=1e-4)  # PH04：上限即最深点
    assert heights.min() == pytest.approx(0.0, abs=1e-4)
    expected = np.repeat(np.linspace(0.0, 2.0, 12)[:, None], 8, axis=1)
    np.testing.assert_allclose(heights, expected, atol=1e-4)  # 已知梯度误差 ≤1e-4 mm


def test_cap_to_mm_rejects_nonfinite() -> None:
    with pytest.raises(ValueError, match="非有限"):
        cap_to_mm(np.array([[np.nan, 0.5]]), 2.0)


def test_clamp_cap_reports_truncation_openly() -> None:
    heights = np.array([[0.5, 1.0, 3.0, 9.0]])
    clamped, report = clamp_cap(heights, 2.0)
    np.testing.assert_allclose(clamped, [[0.5, 1.0, 2.0, 2.0]])
    assert report["clamped_points"] == 2
    assert report["max_before_mm"] == pytest.approx(9.0)
    assert report["cap_mm"] == 2.0
    clean, clean_report = clamp_cap(np.array([[0.1, 1.5]]), 2.0)
    assert clean_report["clamped_points"] == 0 and clean.max() == pytest.approx(1.5)


def test_image_to_geometry_rows_flips_row_order() -> None:
    arr = np.arange(12, dtype=np.float64).reshape(4, 3)
    flipped = image_to_geometry_rows(arr)
    np.testing.assert_array_equal(flipped, arr[::-1])  # 工作图 y 向下 → 几何 y 向上
    np.testing.assert_array_equal(flipped[0], arr[-1])


def test_relief_parameters_validation_matrix() -> None:
    base = {
        "width_mm": 60.0,
        "depth_mm": 2.0,
        "height_mode": HeightMode.EXPLICIT_DEPTH,
        "profile_id": None,
        "smoothing_radius_mm": None,
        "detail_strength": 0.0,
    }
    ReliefParameters(**base).validate()  # 默认值合法
    for bad in (
        {"width_mm": 4.0},
        {"width_mm": 400.0},
        {"depth_mm": 0.01},
        {"depth_mm": 25.0},
        {"height_mode": HeightMode.REFERENCE_RATIO},
        {"smoothing_radius_mm": 0.0},
        {"smoothing_radius_mm": 100.0},
        {"detail_strength": -0.1},
    ):
        with pytest.raises(ValueError):
            ReliefParameters(**(base | bad)).validate()
    ReliefParameters(
        **(base | {"height_mode": HeightMode.REFERENCE_RATIO, "profile_id": "calibrated-v1"})
    ).validate()
