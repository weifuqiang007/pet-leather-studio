"""MOLD-PAIR M1 单元：参数合同、单侧坡度、球形包络（凸脊 pinch 回归）、平铺扩边。

包络验收不信任公式自证：一律把两面三角化后走 bidirectional_min_distance
（M1-R1：重心细分采样 + 精确点到三角面距离 + 半径证书）独立测距；45° 凸脊
同时验证朴素 Z 偏置确实欠清（t·cos45 < t），防止回归成平面近似。另有
"真实最近点在三角面内部、旧 5 点采样全错过"的反例回归（旧点到点 KD-tree
实现必须错误放行）。扩边核心逐位不变（×1.0 精确）以 np.array_equal 断言。
"""

import math

import numpy as np
import pytest
import trimesh
from scipy.spatial import cKDTree

from pet_leather_studio.algorithms.leather_mold_pair import (
    SUBDIVISION_ORDER,
    bidirectional_min_distance,
    distance_tolerance_mm,
    expand_heightfield,
    grid_surface_trimesh,
    normal_clearance_field,
    one_sided_slope,
    spherical_envelope,
)
from pet_leather_studio.domain.leather_molds import (
    LeatherMoldParameters,
    effective_thickness_mm,
)

DX = DY = 0.5  # 测试网格统一间距（mm）
TOL = distance_tolerance_mm(DX, DY)  # 0.125


def test_parameter_validation_matrix() -> None:
    LeatherMoldParameters().validate()  # 默认值全在建议范围
    for field, value, pattern in (
        ("leather_thickness_mm", 0.4, "leather_thickness_mm"),
        ("leather_thickness_mm", 6.5, "leather_thickness_mm"),
        ("compression_allowance_mm", 1.2, "compression_allowance_mm"),
        ("min_clearance_mm", 0.05, "min_clearance_mm"),
        ("backing_mm", 1.9, "backing_mm"),
        ("edge_margin_mm", 1.5, "edge_margin_mm"),
        ("max_plate_mm", 30.0, "max_plate_mm"),
        ("sampling_feature_mm", 0.04, "sampling_feature_mm"),
        ("sampling_mode", "fast", "sampling_mode"),
    ):
        parameters = LeatherMoldParameters(**{field: value})
        with pytest.raises(ValueError, match=pattern):
            parameters.validate()
    with pytest.raises(ValueError, match="压实后仍需正厚度"):
        LeatherMoldParameters(leather_thickness_mm=0.5, compression_allowance_mm=0.5).validate()


def test_effective_thickness_floor() -> None:
    assert effective_thickness_mm(LeatherMoldParameters()) == pytest.approx(1.85)
    # 皮厚 − 压实低于最小间隙时取下限（薄皮场景）
    thin = LeatherMoldParameters(leather_thickness_mm=0.5, compression_allowance_mm=0.3)
    assert effective_thickness_mm(thin) == pytest.approx(0.3)


def test_distance_tolerance_formula() -> None:
    assert distance_tolerance_mm(0.1, 0.1) == pytest.approx(0.05)  # 地板值
    assert distance_tolerance_mm(0.408, 0.408) == pytest.approx(0.102)  # 真实犬模间距
    assert distance_tolerance_mm(0.294, 0.408) == pytest.approx(0.102)  # 取较大间距


def test_one_sided_slope_cliff_not_halved() -> None:
    heights = np.array([[0.0, 0.0, 1.0, 1.0]])
    report = one_sided_slope(heights, 1.0, 1.0)
    assert report["x_max_mm_per_mm"] == pytest.approx(1.0)  # 断崖不折半（非中心差分）
    assert report["max_deg"] == pytest.approx(45.0)
    column = np.array([[0.0], [2.0]])
    assert one_sided_slope(column, 1.0, 1.0)["y_max_mm_per_mm"] == pytest.approx(2.0)


def test_normal_clearance_below_axial_on_45_slope() -> None:
    heights = np.tile(np.array([[0.0, 1.0, 2.0, 3.0]]), (2, 1))  # 沿 x 的 45° 斜坡
    axial = np.full_like(heights, 1.85)
    normal = normal_clearance_field(axial, heights, 1.0, 1.0)
    assert np.allclose(normal, 1.85 / math.sqrt(2.0))  # 仅报告口径：n_z=1/√2


def test_envelope_flat_plane_is_exact_offset() -> None:
    flat = np.full((7, 9), 1.7)
    envelope, report = spherical_envelope(flat, DX, DY, 1.85)
    assert np.allclose(envelope, 1.7 + 1.85)
    assert report["offsets"] > 1 and report["radius_mm"] == pytest.approx(1.85)
    with pytest.raises(ValueError, match="半径必须为正"):
        spherical_envelope(flat, DX, DY, 0.0)


def test_envelope_ridge_pinch_regression() -> None:
    """45° 凸脊：朴素 Z 偏置最小距离 ≈ t·cos45（欠清）；球形包络须达 t−容差。"""

    columns = np.arange(21)
    ridge = np.repeat(np.maximum(0.0, 5.0 - DX * np.abs(columns - 10))[None, :], 21, axis=0)
    slope = np.abs(np.diff(ridge, axis=1)).max() / DX
    assert slope == pytest.approx(1.0)  # 前置：确实是 45° 脊

    t = 1.85
    naive = grid_surface_trimesh(ridge + t, 10.0, 10.0)
    male = grid_surface_trimesh(ridge, 10.0, 10.0)
    naive_check = bidirectional_min_distance(male, naive)
    assert naive_check["min_mm"] < t - 2 * TOL  # 旧平面近似在脊处被夹薄

    envelope, _report = spherical_envelope(ridge, DX, DY, t)
    female = grid_surface_trimesh(envelope, 10.0, 10.0)
    check = bidirectional_min_distance(male, female)
    assert check["min_mm"] >= t - TOL
    assert check["a_to_b_mm"] > 0.0 and check["b_to_a_mm"] > 0.0


def test_envelope_dome_meets_clearance() -> None:
    xs = np.arange(33) * DX
    xx, yy = np.meshgrid(xs, xs)
    radius = np.hypot(xx - 8.0, yy - 8.0)
    dome = 4.0 * np.clip(1.0 - (radius / 8.0) ** 2, 0.0, 1.0)
    envelope, _report = spherical_envelope(dome, DX, DY, 1.85)
    assert np.isfinite(envelope).all()
    check = bidirectional_min_distance(
        grid_surface_trimesh(dome, 16.0, 16.0),
        grid_surface_trimesh(envelope, 16.0, 16.0),
    )
    assert check["min_mm"] >= 1.85 - TOL


def test_envelope_single_spike_needs_guard() -> None:
    """单格尖峰（近垂直壁）：包络处处有限；验收靠 guard 加密兜底（§3.2）。

    上包络只能表达单值 z，近垂直壁的侧向偏置不可表示——无 guard 时精确
    点到三角面距离仍低于 R−容差；guard 加密（生产 GUARD_STEPS 1×/2×容差）
    后达标。细分球心 + 精确测距后 1×容差档即够（旧点到点口径需 2×）。
    """

    spike = np.zeros((21, 21))
    spike[10, 10] = 3.0
    male = grid_surface_trimesh(spike, 10.0, 10.0)

    plain, _report = spherical_envelope(spike, DX, DY, 1.0)
    assert np.isfinite(plain).all()
    plain_check = bidirectional_min_distance(male, grid_surface_trimesh(plain, 10.0, 10.0))
    guard1, _report = spherical_envelope(spike, DX, DY, 1.0 + TOL)
    guard1_check = bidirectional_min_distance(male, grid_surface_trimesh(guard1, 10.0, 10.0))
    guard2, _report = spherical_envelope(spike, DX, DY, 1.0 + 2 * TOL)
    guard2_check = bidirectional_min_distance(male, grid_surface_trimesh(guard2, 10.0, 10.0))
    assert plain_check["min_mm"] < 1.0 - TOL  # 尖峰侧壁：包络单独不够（如实记录）
    assert guard1_check["min_mm"] >= 1.0 - TOL  # guard 兜底后达到验收门
    assert guard2_check["min_mm"] >= 1.0 - TOL
    assert guard1_check["min_mm"] > plain_check["min_mm"]


def _legacy_point_samples(mesh: trimesh.Trimesh) -> np.ndarray:
    """M1 初版采样器（仅回归对照用）：顶点 + 三边中点 + 面心。"""

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    corners = vertices[np.asarray(mesh.faces, dtype=np.int64)]
    return np.vstack(
        [
            vertices,
            0.5 * (corners[:, 0] + corners[:, 1]),
            0.5 * (corners[:, 1] + corners[:, 2]),
            0.5 * (corners[:, 2] + corners[:, 0]),
            corners.mean(axis=1),
        ]
    )


def test_point_to_triangle_interior_nearest_counterexample() -> None:
    """反例（M1-R1 P0）：真实最近点在 A 面内部，新旧验收器结论相反。

    B 的低顶点悬在 A 大三角面内部上方 0.12 mm 处；A/B 的顶点、边中点、
    面心全部远离该接触位置。旧点到点 KD-tree 报 0.731 mm（按 0.5 mm 门限
    会错误放行）；点到三角面报 0.120 mm（真实值，拒绝/加 guard）。
    """

    ground = trimesh.Trimesh(
        [[0.0, 0.0, 0.0], [12.0, 0.0, 0.0], [0.0, 12.0, 0.0]], [[0, 1, 2]], process=False
    )
    hovering = trimesh.Trimesh(
        [[0.6, 0.4, 0.12], [9.0, 9.0, 6.0], [-9.0, 7.0, 6.0]], [[0, 1, 2]], process=False
    )
    legacy = float(
        cKDTree(_legacy_point_samples(hovering)).query(_legacy_point_samples(ground))[0].min()
    )
    check = bidirectional_min_distance(ground, hovering)
    assert legacy > 0.7  # 旧实现：所有采样点对面间距 ≥ 0.731 mm
    assert check["min_mm"] == pytest.approx(0.12, abs=1e-9)  # 新实现：精确 0.12
    assert check["b_to_a_mm"] == pytest.approx(0.12, abs=1e-9)  # 最近点对在 A 面内部
    assert check["a_to_b_mm"] > 0.5
    assert check["certified"] is True
    assert "point-to-triangle" in check["method"]
    # 旧实现按 0.5 mm 门限会放行，新实现必须拒绝——这正是 P0 缺口
    assert legacy >= 0.5 > check["min_mm"]


def test_bidirectional_parallel_planes_and_sample_count() -> None:
    ground = grid_surface_trimesh(np.zeros((5, 5)), 4.0, 4.0)
    lifted = grid_surface_trimesh(np.full((5, 5), 1.0), 4.0, 4.0)
    check = bidirectional_min_distance(ground, lifted)
    # 平行平面：样点到对面三角面的垂直投影精确命中面内部 → 距离恰为 1.0
    assert check["min_mm"] == pytest.approx(1.0, abs=1e-12)
    assert check["a_to_b_mm"] == pytest.approx(1.0, abs=1e-12)
    assert check["b_to_a_mm"] == pytest.approx(1.0, abs=1e-12)
    # 采样 = 面数 × 重心细分格点数（不去重；5×5 网格 → 32 面 × 15 点）
    assert check["subdivision_order"] == SUBDIVISION_ORDER
    assert check["points_per_face"] == (SUBDIVISION_ORDER + 1) * (SUBDIVISION_ORDER + 2) // 2
    assert check["samples_a"] == 32 * check["points_per_face"]
    assert check["certified"] is True
    assert check["sampling_bound_mm"] > 0.0  # 采样误差界随报告可审计
    assert check["conservative_min_mm"] < check["min_mm"]


def _ramp_grid() -> np.ndarray:
    return 0.5 + 0.05 * np.arange(41)[None, :].repeat(21, axis=0)


def test_expand_noop_when_flat_stop_sufficient() -> None:
    heights = _ramp_grid()
    padded, report = expand_heightfield(
        heights,
        DX,
        DY,
        existing_flat_mm=4.0,
        edge_margin_mm=4.0,
        max_plate_mm=120.0,
        plate_width_mm=20.0,
        plate_height_mm=10.0,
    )
    assert not report["expanded"]
    assert np.array_equal(padded, heights)  # 余量足够：原样返回，逐位不变


def test_expand_preserves_core_bitwise_and_adds_flat_stop() -> None:
    heights = _ramp_grid()
    padded, report = expand_heightfield(
        heights,
        DX,
        DY,
        existing_flat_mm=0.0,  # 贴边/无余量：必须扩
        edge_margin_mm=4.0,
        max_plate_mm=120.0,
        plate_width_mm=20.0,
        plate_height_mm=10.0,
    )
    assert report["expanded"]
    rows, cols = report["core_rows"], report["core_cols"]
    assert np.array_equal(padded[rows[0] : rows[1], cols[0] : cols[1]], heights)
    # 版边四缘纯平（decay 已归零），止口宽度 ≥ margin − 一个格距
    for edge in (padded[0, :], padded[-1, :], padded[:, 0], padded[:, -1]):
        assert np.all(edge <= 1e-9)
    assert report["flat_stop_min_mm"] >= 4.0 - max(DX, DY)
    assert report["final_width_mm"] == pytest.approx(20.0 + 2 * report["pad_x_px"] * DX)
    assert padded.shape == (
        21 + 2 * report["pad_y_px"],
        41 + 2 * report["pad_x_px"],
    )
    # 核心右缘向外：高度单调落地到 0（smoothstep 衰减不回弹）
    outward = padded[padded.shape[0] // 2, cols[1] - 1 :]
    assert np.all(np.diff(outward) <= 1e-12)


def test_expand_rejects_oversize_plate() -> None:
    with pytest.raises(ValueError, match="max_plate_mm"):
        expand_heightfield(
            _ramp_grid(),
            DX,
            DY,
            existing_flat_mm=0.0,
            edge_margin_mm=4.0,
            max_plate_mm=30.0,  # 扩边后 36 mm 会超
            plate_width_mm=20.0,
            plate_height_mm=10.0,
        )
