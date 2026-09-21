"""PH03/PH04/PH05：深度语义适配、无效域隔离、Y 行翻转、起伏上限误差、
同比例参考换算、受控浮雕化数值管线与局部调整边界。"""

import numpy as np
import pytest

from pet_leather_studio.algorithms.relief_height import (
    apply_local_adjustments,
    cap_to_mm,
    clamp_cap,
    controlled_heights_mm,
    image_to_geometry_rows,
    ratio_depth_mm,
    smooth_valid_aware,
    unit_height,
)
from pet_leather_studio.domain.photo_relief import (
    DepthSemantics,
    HeightMode,
    LocalAdjustment,
    ReferenceProfile,
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
        "base_thickness_mm": 3.0,
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
        {"base_thickness_mm": 0.5},
        {"base_thickness_mm": 31.0},
    ):
        with pytest.raises(ValueError):
            ReliefParameters(**(base | bad)).validate()
    ReliefParameters(
        **(base | {"height_mode": HeightMode.REFERENCE_RATIO, "profile_id": "calibrated-v1"})
    ).validate()


def test_local_adjustment_validation_matrix() -> None:
    base = {"label": "鼻尖", "region_png": "adjust-0.png", "offset_mm": 0.5, "transition_mm": 2.0}
    LocalAdjustment(**base).validate()
    for bad in (
        {"label": " "},
        {"region_png": ""},
        {"offset_mm": -20.5},
        {"offset_mm": 20.5},
        {"transition_mm": 51.0},
    ):
        with pytest.raises(ValueError):
            LocalAdjustment(**(base | bad)).validate()


def _reference_profile(**overrides: float) -> ReferenceProfile:
    """有效参考起伏 2.879 / 参考宽度 19.283（SubTool3 历史数字）的合成标定。"""
    values: dict[str, object] = {
        "profile_id": "ref-test0000000000ff",
        "source_name": "synthetic.obj",
        "source_path": "/synthetic/synthetic.obj",
        "source_sha256": "0" * 64,
        "source_units": "assumed_mm",
        "region": (0.0, 19.283, 0.0, 19.0),
        "region_basis": "full_xy_bounds_v1",
        "datum_method": "min_z_plane",
        "datum_z": -0.771,
        "percentile": 99.0,
        "exclusion_fraction": 0.01,
        "effective_relief_mm": 2.879,
        "reference_width_mm": 19.283,
        "true_min_z": -0.771,
        "true_max_z": 2.107,
        "true_excess_mm": 0.0,
        "excluded_point_count": 0,
        "bbox_z_span": 2.878,
        "bbox_z_span_ratio": 0.1493,
        "measurement_algorithm": "reference-profile-v1",
        "created_at": "2026-09-21T00:00:00+00:00",
    }
    return ReferenceProfile(**(values | overrides))  # type: ignore[arg-type]


def test_ratio_depth_mm_value_and_range() -> None:
    depth = ratio_depth_mm(2.879, 19.283, 60.0)
    assert depth == pytest.approx(2.879 / 19.283 * 60.0, rel=1e-12)
    # 参考部位与目标部位不对应（换算越界）：提示改显式深度，不自动缩放
    with pytest.raises(ValueError, match="explicit_depth"):
        ratio_depth_mm(2.879, 19.283, 300.0)
    with pytest.raises(ValueError, match="正的有限值"):
        ratio_depth_mm(2.879, 0.0, 60.0)


def test_smooth_valid_aware_keeps_valid_edge_undragged() -> None:
    """归一化卷积：常量场在有效边缘不被无效像素拖低（朴素卷积会向 0 塌陷）。"""
    unit = np.full((20, 20), 0.5)
    valid = np.ones((20, 20), dtype=bool)
    valid[:, :10] = False  # 左半无效
    smoothed = smooth_valid_aware(unit, valid, sigma_px=2.0)
    np.testing.assert_allclose(smoothed[valid], 0.5, atol=1e-9)
    assert np.all(smoothed[~valid] == 0.0)


def test_controlled_heights_report_records_unit_conversion() -> None:
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    valid = np.ones((12, 61), dtype=bool)
    heights, report = controlled_heights_mm(
        ramp,
        valid,
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0, smoothing_radius_mm=2.0),
    )
    assert report["dx_mm"] == pytest.approx(1.0)  # 60 mm / (61-1) 采样
    assert report["smoothing"]["sigma_px"] == pytest.approx(2.0)  # 2 mm / 1 mm
    assert report["smoothing"]["radius_mm"] == pytest.approx(2.0)
    assert report["depth_source"] == "explicit_depth"
    assert report["resolved_depth_mm"] == pytest.approx(2.0)
    assert heights.min() >= 0.0 and heights.max() <= 2.0 + 1e-12


def test_controlled_heights_reference_ratio_uses_profile() -> None:
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    valid = np.ones((12, 61), dtype=bool)
    profile = _reference_profile()
    heights, report = controlled_heights_mm(
        ramp,
        valid,
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(
            width_mm=60.0, height_mode=HeightMode.REFERENCE_RATIO, profile_id=profile.profile_id
        ),
        profile=profile,
    )
    assert report["depth_source"] == "reference_ratio"
    assert report["profile_id"] == profile.profile_id
    assert report["resolved_depth_mm"] == pytest.approx(2.879 / 19.283 * 60.0)
    assert heights.max() == pytest.approx(2.879 / 19.283 * 60.0, abs=1e-9)


def test_controlled_heights_reference_ratio_requires_profile() -> None:
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    with pytest.raises(ValueError, match="必须提供已标定"):
        controlled_heights_mm(
            ramp,
            np.ones((12, 61), dtype=bool),
            DepthSemantics.RELATIVE_LARGER_NEARER,
            ReliefParameters(
                width_mm=60.0, height_mode=HeightMode.REFERENCE_RATIO, profile_id="ref-x"
            ),
        )


def test_local_adjustment_stays_local_and_spike_free() -> None:
    """合同验收：调整局部不得拔高整个主体、不产生尖峰。"""
    heights = np.zeros((40, 40))
    region = np.zeros((40, 40))
    region[15:25, 15:25] = 1.0
    adjusted = apply_local_adjustments(heights, [(region, 1.0, 2.0)], dx_mm=1.0)
    assert adjusted[19, 19] >= 0.9  # 刷选区内基本到位
    assert adjusted[0:7, :].max() < 1e-3  # 3σ（6px）再外 1px 处不受影响
    assert adjusted[35:, :].max() < 1e-3
    # 过渡带斜率有界（高斯平滑步进 ≈ 1/(σ√(2π)) ≈ 0.2 mm/px；尖峰会是整幅 1.0）
    assert np.abs(np.diff(adjusted, axis=0)).max() <= 0.25


def test_local_adjustment_clamp_report_surfaces() -> None:
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    region = np.zeros((12, 61))
    region[8:12, :] = 1.0  # 高段整体 +5 mm，必然越过 2 mm 上限
    _, report = controlled_heights_mm(
        ramp,
        np.ones((12, 61), dtype=bool),
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0),
        adjustments=[(region, 5.0, 1.0)],
    )
    assert report["clamp"]["clamped_points"] > 0
    assert report["clamp"]["max_before_mm"] > 2.0  # 改动范围如实展示，不静默截断
    assert report["clamp"]["cap_mm"] == pytest.approx(2.0)
    assert report["adjustments_count"] == 1


def test_local_adjustment_negative_offset_clamped_at_datum() -> None:
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    region = np.zeros((12, 61))
    region[0:3, :] = 1.0  # 低段（高度≈0）向下挖，不得挖穿浮雕基准 0
    heights, report = controlled_heights_mm(
        ramp,
        np.ones((12, 61), dtype=bool),
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0),
        adjustments=[(region, -5.0, 1.0)],
    )
    assert heights.min() >= 0.0
    assert report["clamp"]["clamped_below_points"] > 0


def test_controlled_heights_deterministic_rerun() -> None:
    """合同：尺寸缩放及局部约束可重跑——同输入两次调用逐位一致。"""
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    valid = np.ones((12, 61), dtype=bool)
    region = np.zeros((12, 61))
    region[4:8, 10:50] = 1.0
    args = (
        ramp,
        valid,
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0, smoothing_radius_mm=1.5),
        None,
        [(region, 0.75, 2.0)],
    )
    heights_a, report_a = controlled_heights_mm(*args)
    heights_b, report_b = controlled_heights_mm(*args)
    np.testing.assert_array_equal(heights_a, heights_b)
    assert report_a["clamp"] == report_b["clamp"] and report_a["smoothing"] == report_b["smoothing"]
