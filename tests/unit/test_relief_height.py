"""PH03/PH04/PH05：深度语义适配、无效域隔离、Y 行翻转、起伏上限误差、
同比例参考换算、受控浮雕化数值管线与局部调整边界。"""

import numpy as np
import pytest

from pet_leather_studio.algorithms.relief_height import (
    apply_local_adjustments,
    background_clearance_mm,
    cap_to_mm,
    clamp_cap,
    controlled_heights_mm,
    edge_falloff,
    image_to_geometry_rows,
    ratio_depth_mm,
    slope_report,
    smooth_valid_aware,
    unit_height,
)
from pet_leather_studio.domain.photo_relief import (
    DepthSemantics,
    HeightMode,
    LocalAdjustment,
    ReferenceProfile,
    ReliefParameters,
    slope_exceedances,
    suggested_falloff_band_mm,
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
        {"falloff_band_mm": -0.1},
        {"falloff_band_mm": 55.0},
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


# ---- P2 复验 R1：蒙版边界背景过渡带（消除垂直墙） ----


def test_edge_falloff_off_or_full_valid_is_noop() -> None:
    """带宽 0 或全域有效：高度场逐位不变（旧行为兼容），report 如实记录未启用。"""
    heights = np.ones((10, 10))
    valid = np.zeros((10, 10), dtype=bool)
    valid[:, 5:] = True
    off, off_report = edge_falloff(heights, valid, 0.0, dx_mm=1.0, dy_mm=1.0)
    np.testing.assert_array_equal(off, heights)
    assert off_report["enabled"] is False and off_report["raised_points"] == 0
    full, full_report = edge_falloff(heights, np.ones((10, 10), dtype=bool), 3.0, 1.0, 1.0)
    np.testing.assert_array_equal(full, heights)
    assert full_report["enabled"] is False


def test_edge_falloff_shape_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="形状不一致"):
        edge_falloff(np.ones((4, 4)), np.ones((3, 3), dtype=bool), 2.0, 1.0, 1.0)


def test_edge_falloff_constant_subject_lands_smoothly() -> None:
    """R1 验收门：主体到背景连续过渡——主体内部逐点不变、远离主体单调落地、
    全域相邻单元高度差不超过 smoothstep 最大斜率（1.5×h/带宽×单元）。"""
    ny, nx, band, cap = 24, 32, 4.0, 2.0
    valid = np.zeros((ny, nx), dtype=bool)
    valid[4:20, 10:22] = True
    valid[8:14, 22:26] = True  # L 形外凸：边界含非轴对齐段
    heights = np.where(valid, cap, 0.0)
    result, report = edge_falloff(heights, valid, band, dx_mm=1.0, dy_mm=1.0)

    assert report["enabled"] is True
    assert report["raised_points"] > 0
    # 网格间距 1：最近域外像素 d=1，最大抬升 = cap×(1−smoothstep(1/4)) < cap
    assert report["max_raised_mm"] == pytest.approx(cap * (1.0 - 0.15625), abs=1e-9)
    np.testing.assert_array_equal(result[valid], heights[valid])  # 主体内部不变
    assert result[0, 0] == 0.0 and result[-1, -1] == 0.0  # 远离主体处严格为 0
    # 距边界 1 单元处 = cap×(1−smoothstep(1/4))，钉住衰减公式
    assert result[12, 9] == pytest.approx(cap * (1.0 - 0.15625), abs=1e-9)
    # 沿行从背景趋向主体：高度单调不减（远离主体单调不增）
    assert np.all(np.diff(result[12, :10]) >= -1e-12)
    # 连续性门：无任何相邻单元跳变超过平滑落地最大斜率（旧垂直墙=单格跌落整幅 cap）
    jump = max(np.abs(np.diff(result, axis=0)).max(), np.abs(np.diff(result, axis=1)).max())
    assert jump <= cap * 1.5 / band + 1e-9


def test_controlled_heights_pipeline_order_falloff_then_adjustments() -> None:
    """管线顺序（R1）：过渡带先于局部调整——刷选区落在域外过渡带时，偏移作用
    在衰减后的高度上并被最终限幅；report 记录过渡统计。"""
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    valid = np.ones((12, 61), dtype=bool)
    valid[:, :20] = False  # 左侧背景
    region = np.zeros((12, 61))
    region[:, :20] = 1.0  # 过渡带内整体 +0.3 mm（transition=0 即不经高斯）
    heights, report = controlled_heights_mm(
        ramp,
        valid,
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0, falloff_band_mm=5.0),
        adjustments=[(region, 0.3, 0.0)],
    )
    assert report["falloff"]["enabled"] is True
    assert report["falloff"]["band_mm"] == pytest.approx(5.0)
    assert report["falloff"]["raised_points"] > 0
    assert heights[:, 18].max() > 0.2  # 域外近缘已高于背景再叠加调整
    assert heights.max() <= 2.0 + 1e-12  # 调整后仍受上限约束


def test_controlled_heights_deterministic_rerun_with_falloff() -> None:
    """合同"尺寸缩放及局部约束可重跑"延伸：过渡带参与后仍逐位一致。"""
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    valid = np.ones((12, 61), dtype=bool)
    valid[:4, :] = False
    args = (
        ramp,
        valid,
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0, falloff_band_mm=3.0),
    )
    heights_a, report_a = controlled_heights_mm(*args)
    heights_b, report_b = controlled_heights_mm(*args)
    np.testing.assert_array_equal(heights_a, heights_b)
    assert report_a["falloff"] == report_b["falloff"]


# ---- P2 复验 R2：建议带宽 / 版边余量 / 坡度统计 ----


def test_suggested_falloff_band_mm_scales_with_depth() -> None:
    """建议带宽 = ceil0.1(1.5×h/坡度上限)：2→3.0、1.25→1.9、8.352108→12.6、封顶 50。"""
    assert suggested_falloff_band_mm(2.0) == pytest.approx(3.0)
    assert suggested_falloff_band_mm(1.25) == pytest.approx(1.9)  # 1.875 向上取整
    assert suggested_falloff_band_mm(8.352107938604037) == pytest.approx(12.6)
    assert suggested_falloff_band_mm(40.0) == pytest.approx(50.0)  # 封顶带宽上限
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            suggested_falloff_band_mm(bad)


def test_background_clearance_mm_known_layout() -> None:
    """版边余量 = 边框像素到有效域的最小距离；主体贴边/空有效为 inf、全有效为 0。"""
    valid = np.zeros((24, 32), dtype=bool)
    valid[4:20, 8:24] = True
    assert background_clearance_mm(valid, dx_mm=1.0, dy_mm=1.0) == pytest.approx(4.0)
    stretched = background_clearance_mm(valid, dx_mm=0.5, dy_mm=1.0)  # 横向半距
    assert stretched == pytest.approx(4.0)  # 上下边仍是最近约束
    touching = valid.copy()
    touching[0, 10] = True  # 主体贴版边：平边前提不成立，不再构成带宽约束
    assert background_clearance_mm(touching, 1.0, 1.0) == float("inf")
    assert background_clearance_mm(np.ones((5, 5), dtype=bool), 1.0, 1.0) == 0.0
    assert background_clearance_mm(np.zeros((5, 5), dtype=bool), 1.0, 1.0) == float("inf")


def test_slope_report_classifies_pairs() -> None:
    """垂直墙场：跨界坡度 = cap/dx、域内 0；过渡带场：跨界坡度 ≤ 1.5×cap/band。"""
    ny, nx, cap = 12, 20, 2.0
    valid = np.zeros((ny, nx), dtype=bool)
    valid[:, :10] = True
    wall = np.where(valid, cap, 0.0)
    wall_report = slope_report(wall, valid, dx_mm=0.5, dy_mm=1.0)
    assert wall_report["boundary_max_mm_per_mm"] == pytest.approx(cap / 0.5)
    assert wall_report["interior_max_mm_per_mm"] == 0.0
    assert wall_report["max_overall_mm_per_mm"] == pytest.approx(cap / 0.5)
    assert wall_report["boundary_max_deg"] == pytest.approx(75.96, abs=0.01)

    band = 3.0
    skirt, _ = edge_falloff(wall, valid, band, dx_mm=0.5, dy_mm=1.0)
    skirt_report = slope_report(skirt, valid, dx_mm=0.5, dy_mm=1.0)
    assert skirt_report["boundary_max_mm_per_mm"] <= 1.5 * cap / band + 1e-9
    assert skirt_report["interior_max_mm_per_mm"] == 0.0  # 主体内部无断层
    with pytest.raises(ValueError, match="形状不一致"):
        slope_report(np.ones((4, 4)), np.ones((3, 3), dtype=bool), 1.0, 1.0)


def test_controlled_heights_report_contains_slope() -> None:
    """矩形有效域：无跨界对（boundary=0），域内坡度即全域最陡（斜坡 >0）。"""
    ramp = np.repeat(np.linspace(1.0, 11.0, 12)[:, None], 61, axis=1)
    _, report = controlled_heights_mm(
        ramp,
        np.ones((12, 61), dtype=bool),
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0),
    )
    slope = report["slope"]
    assert slope["boundary_max_mm_per_mm"] == 0.0
    assert slope["interior_max_mm_per_mm"] > 0.0
    assert slope["max_overall_mm_per_mm"] == pytest.approx(slope["interior_max_mm_per_mm"])
    assert 0.0 < slope["interior_max_deg"] < 90.0


# ---- P2 复验 R3：坡度超限提示 / 平滑审计 / 细节保留率 ----


def test_slope_exceedances_flags_only_overruns() -> None:
    """45° 目标只针对理想裙边：实测超限项被点名，恰好达标不算，缺键安全。"""
    steep = {"max_overall_deg": 85.4, "boundary_max_deg": 85.4, "interior_max_deg": 10.5}
    flagged = slope_exceedances(steep)
    assert "全域实测最陡 85.4°" in flagged
    assert "边界过渡实测最陡 85.4°" in flagged
    assert not any("域内" in item for item in flagged)  # 10.5° 未超
    at_target = {"max_overall_deg": 45.0, "boundary_max_deg": 0.0, "interior_max_deg": 44.999}
    assert slope_exceedances(at_target) == []  # 恰好 45° 不算超限（容差防浮点）
    assert slope_exceedances({}) == []


def test_smoothing_report_auditable_and_retention_monotone() -> None:
    """平滑关闭也必须可审计（enabled=False）；半径越大细节保留率越低。"""
    rng = np.random.default_rng(7)
    depth = rng.random((20, 80))
    valid = np.ones((20, 80), dtype=bool)
    _, off_report = controlled_heights_mm(
        depth,
        valid,
        DepthSemantics.RELATIVE_LARGER_NEARER,
        ReliefParameters(width_mm=60.0, depth_mm=2.0),
    )
    assert off_report["smoothing"] == {"enabled": False}  # R3：关闭不再是缺省/无记录
    retentions = []
    for radius in (1.0, 4.0):
        _, report = controlled_heights_mm(
            depth,
            valid,
            DepthSemantics.RELATIVE_LARGER_NEARER,
            ReliefParameters(width_mm=60.0, depth_mm=2.0, smoothing_radius_mm=radius),
        )
        block = report["smoothing"]
        assert block["enabled"] is True
        assert block["radius_mm"] == pytest.approx(radius)
        assert 0.0 <= block["detail_retention"] <= 1.0
        retentions.append(block["detail_retention"])
    assert retentions[0] > retentions[1]  # 1 mm 比 4 mm 保留更多细节
