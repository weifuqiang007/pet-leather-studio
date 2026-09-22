"""PH06：母版几何导出——重读单位/朝向/边界一致、封闭正体积、起伏误差 ≤1e-4 mm。

用行斜坡深度（每行常数、沿行 1→11）让 Y 翻转可被断言：几何 y=0 缘最高、
y=H 缘为 0；顶面为平面（体积有解析值），OBJ/STL 重读后独立复核。
"""

import math
from pathlib import Path

import numpy as np
import pytest
import pyvista as pv
import trimesh
from PIL import Image

from pet_leather_studio.bootstrap.workbench import create_workbench
from pet_leather_studio.domain.molds import MoldParameters
from pet_leather_studio.domain.photo_relief import (
    HeightMode,
    LocalAdjustment,
    ReferenceProfile,
    ReliefParameters,
)
from pet_leather_studio.infrastructure.photo_geometry import GEOM_TOL_MM, PhotoGeometry

ROWS, COLS = 12, 61
WIDTH_MM = 60.0
HEIGHT_MM = WIDTH_MM * ROWS / COLS
CAP_MM = 2.0
BASE_MM = 3.0


def _write_depth(path: Path, corrupt_with_nan: bool = False) -> None:
    depth = np.repeat(np.linspace(1.0, 11.0, ROWS)[:, None], COLS, axis=1)
    if corrupt_with_nan:
        depth[5, 5] = np.nan
    np.savez_compressed(
        path, depth=depth.astype(np.float32), valid=np.ones((ROWS, COLS), dtype=bool)
    )


def _expected_heights() -> np.ndarray:
    """工作图行高 (d-1)/10×CAP；几何行序经 Y 翻转。"""
    work = (np.repeat(np.linspace(1.0, 11.0, ROWS)[:, None], COLS, axis=1) - 1.0) / 10.0 * CAP_MM
    return work[::-1]


def _profile(effective_relief: float = 4.0, reference_width: float = 20.0) -> ReferenceProfile:
    profile = ReferenceProfile(
        profile_id="ref-test00000000001",
        source_name="reference.obj",
        source_path="/nonexistent/reference.obj",
        source_sha256="0" * 64,
        source_units="assumed_mm",
        region=(0.0, reference_width, 0.0, 15.0),
        region_basis="full_xy_bounds_v1",
        datum_method="min_z_plane",
        datum_z=0.0,
        percentile=99.0,
        exclusion_fraction=0.006,
        effective_relief_mm=effective_relief,
        reference_width_mm=reference_width,
        true_min_z=0.0,
        true_max_z=6.0,
        true_excess_mm=2.0,
        excluded_point_count=2,
        bbox_z_span=6.0,
        bbox_z_span_ratio=6.0 / reference_width,
        measurement_algorithm="reference-profile-v1",
        created_at="2026-09-21T00:00:00+00:00",
    )
    profile.validate()
    return profile


def _build(
    tmp_path: Path,
    parameters: ReliefParameters | None = None,
    adjustments: tuple[LocalAdjustment, ...] = (),
    profile: ReferenceProfile | None = None,
    corrupt_with_nan: bool = False,
) -> tuple[Path, dict]:
    depth = tmp_path / "depth.npz"
    _write_depth(depth, corrupt_with_nan)
    stage = tmp_path / "stage"
    stage.mkdir()
    params = parameters or ReliefParameters(
        width_mm=WIDTH_MM, depth_mm=CAP_MM, base_thickness_mm=BASE_MM
    )
    metadata = PhotoGeometry().build_master(
        depth,
        {"depth_semantics": "relative_larger_nearer"},
        params,
        profile,
        adjustments,
        stage,
    )
    return stage, metadata


def test_revision_file_set_is_flat_and_complete(tmp_path: Path) -> None:
    stage, _ = _build(tmp_path)
    names = {path.name for path in stage.iterdir()}
    assert {"master.vtp", "preview.vtp", "master.obj", "master.stl", "heightfield.npz"} <= names
    assert all(path.is_file() for path in stage.iterdir())  # RevisionStore 只哈希顶层平铺文件


def test_metadata_records_relief_and_checks(tmp_path: Path) -> None:
    _, metadata = _build(tmp_path)
    assert metadata["schema_version"] == 2
    assert metadata["units"] == "mm"
    assert metadata["width_mm"] == pytest.approx(WIDTH_MM)
    assert metadata["height_mm"] == pytest.approx(HEIGHT_MM)
    assert metadata["dx_mm"] == pytest.approx(1.0)
    # 正面起伏与加底实体厚度分开记录（浮雕基准 0，底板另计）
    assert metadata["relief"]["front_relief_mm"] == pytest.approx(CAP_MM)
    assert metadata["relief"]["base_thickness_mm"] == pytest.approx(BASE_MM)
    assert metadata["relief"]["solid_thickness_mm"] == pytest.approx(BASE_MM + CAP_MM)
    assert metadata["relief"]["datum_z_mm"] == 0.0
    assert metadata["height_resolution"]["source"] == "explicit_depth"
    assert metadata["height_resolution"]["depth_mm"] == pytest.approx(CAP_MM)
    assert metadata["geometry_checks"]["obj_watertight"] is True
    assert metadata["geometry_checks"]["stl_watertight"] is True
    assert metadata["geometry_checks"]["top_surface_max_error_mm"] <= GEOM_TOL_MM


def test_obj_reload_watertight_volume_bounds(tmp_path: Path) -> None:
    stage, metadata = _build(tmp_path)
    mesh = trimesh.load_mesh(stage / "master.obj", process=True)
    assert mesh.is_watertight
    assert mesh.volume > 0
    # 斜坡顶面为平面：体积有解析值 W×H×(base + cap/2)
    assert mesh.volume == pytest.approx(WIDTH_MM * HEIGHT_MM * (BASE_MM + CAP_MM / 2), rel=1e-7)
    assert metadata["geometry_checks"]["volume_mm3"] == pytest.approx(mesh.volume, rel=1e-9)
    expected_bounds = np.array(  # 每轴 (min, max)
        [[0.0, 0.0, 0.0], [WIDTH_MM, HEIGHT_MM, BASE_MM + CAP_MM]]
    )
    assert np.abs(np.asarray(mesh.bounds) - expected_bounds).max() <= GEOM_TOL_MM


def test_orientation_y_flip_visible_in_obj_vertices(tmp_path: Path) -> None:
    """Y 翻转正确：几何 y=0 缘 = 工作图末行（最高），y=H 缘 = 工作图第 0 行（0）。"""
    stage, _ = _build(tmp_path)
    vertices = np.asarray(trimesh.load_mesh(stage / "master.obj", process=False).vertices)
    assert len(vertices) == 2 * ROWS * COLS
    top = vertices[ROWS * COLS :].reshape(ROWS, COLS, 3)
    assert top[0, 0, 1] == pytest.approx(0.0, abs=1e-6)
    assert top[-1, 0, 1] == pytest.approx(HEIGHT_MM, abs=1e-6)
    assert top[0, 0, 0] == pytest.approx(0.0, abs=1e-6)
    assert top[0, -1, 0] == pytest.approx(WIDTH_MM, abs=1e-6)
    np.testing.assert_allclose(top[:, :, 2], BASE_MM + _expected_heights(), atol=1e-6)


def test_stl_top_surface_matches_heightfield(tmp_path: Path) -> None:
    """STL（float32、无索引）按网格吸附逐列复核顶面 z ≤ 1e-4 mm。"""
    stage, _ = _build(tmp_path)
    vertices = np.asarray(trimesh.load_mesh(stage / "master.stl", process=False).vertices)
    vertices = vertices.reshape(-1, 3)
    dx, dy = WIDTH_MM / (COLS - 1), HEIGHT_MM / (ROWS - 1)
    indices_i = np.round(vertices[:, 0] / dx).astype(int)
    indices_j = np.round(vertices[:, 1] / dy).astype(int)
    snap = max(1e-6, 1e-3 * min(dx, dy))
    on_grid = (np.abs(vertices[:, 0] - indices_i * dx) <= snap) & (
        np.abs(vertices[:, 1] - indices_j * dy) <= snap
    )
    assert on_grid.all()
    tops = np.full((ROWS, COLS), -np.inf)
    np.maximum.at(tops, (indices_j[on_grid], indices_i[on_grid]), vertices[on_grid, 2])
    assert np.isfinite(tops).all()
    np.testing.assert_allclose(tops, BASE_MM + _expected_heights(), atol=GEOM_TOL_MM)


def test_master_vtp_is_front_surface_datum_zero(tmp_path: Path) -> None:
    stage, _ = _build(tmp_path)
    surface = pv.read(stage / "master.vtp")
    assert surface.n_points == ROWS * COLS
    points = np.asarray(surface.points).reshape(ROWS, COLS, 3)
    np.testing.assert_allclose(points[:, :, 2], _expected_heights(), atol=1e-9)  # 不含底板
    assert points[0, 0, 1] == pytest.approx(0.0, abs=1e-9)
    preview = pv.read(stage / "preview.vtp")
    assert preview.n_cells > 0
    assert preview.n_cells <= 150_000


def test_heightfield_npz_fields(tmp_path: Path) -> None:
    stage, _ = _build(tmp_path)
    with np.load(stage / "heightfield.npz") as data:
        np.testing.assert_allclose(data["heights_mm"], _expected_heights(), atol=1e-12)
        assert data["valid"].all()
        assert data["dx_mm"] == pytest.approx(WIDTH_MM / (COLS - 1))
        assert data["dy_mm"] == pytest.approx(HEIGHT_MM / (ROWS - 1))
        assert data["width_mm"] == pytest.approx(WIDTH_MM)
        assert data["height_mm"] == pytest.approx(HEIGHT_MM)
        assert data["base_thickness_mm"] == pytest.approx(BASE_MM)
        assert data["datum_z_mm"] == 0.0
        assert str(data["orientation"]) == "geometry_y_up"
        assert int(data["schema_version"]) == 2


def test_mold_generation_from_photo_master(tmp_path: Path) -> None:
    """photo master.vtp 直接进入模具链：raycast 采样与 male/female STL 输出。"""
    service = create_workbench(tmp_path / "project")
    depth = tmp_path / "depth.npz"
    _write_depth(depth)
    stage = service.store.begin()
    metadata = PhotoGeometry().build_master(
        depth,
        {"depth_semantics": "relative_larger_nearer"},
        ReliefParameters(width_mm=WIDTH_MM, depth_mm=CAP_MM, base_thickness_mm=BASE_MM),
        None,
        (),
        stage,
    )
    metadata.update(kind="master", parent_id=None, input_method="photo_reconstruction")
    published = service.store.publish(stage, metadata)
    result = service.generate(MoldParameters(grid_size=32, accept_top_projection=True))
    assert result["master_id"] == published["id"]
    assert result["input_method"] == "photo_reconstruction"
    folder = service.store.directory(result["id"])
    for name in ("male", "female"):
        mesh = trimesh.load_mesh(folder / f"{name}.stl")
        assert mesh.is_watertight and mesh.volume > 0


def test_ratio_mode_metadata(tmp_path: Path) -> None:
    profile = _profile(effective_relief=4.0, reference_width=20.0)
    parameters = ReliefParameters(
        width_mm=WIDTH_MM, height_mode=HeightMode.REFERENCE_RATIO, profile_id=profile.profile_id
    )
    stage, metadata = _build(tmp_path, parameters=parameters, profile=profile)
    resolution = metadata["height_resolution"]
    assert resolution["source"] == "reference_ratio"
    assert resolution["profile_id"] == profile.profile_id
    assert resolution["resolved_depth_mm"] == pytest.approx(4.0 / 20.0 * WIDTH_MM)  # = 12 mm
    assert "effective_relief_mm / reference_width_mm" in resolution["formula"]
    assert metadata["relief"]["front_relief_mm"] == pytest.approx(12.0)
    with np.load(stage / "heightfield.npz") as data:
        assert data["heights_mm"].max() == pytest.approx(12.0)


def test_adjustment_recorded_and_clamp_reported(tmp_path: Path) -> None:
    region = np.zeros((ROWS, COLS), dtype=np.uint8)
    region[8:, :] = 255  # 工作图下部（高深度区）
    png = tmp_path / "region.png"
    Image.fromarray(region, mode="L").save(png)
    adjustment = LocalAdjustment(
        label="胸口", region_png=str(png), offset_mm=5.0, transition_mm=1.0
    )
    stage, metadata = _build(tmp_path, adjustments=(adjustment,))
    record = metadata["adjustments"][0]
    assert record["file"] == "adjustment-0.png"
    assert record["label"] == "胸口"
    assert record["offset_mm"] == pytest.approx(5.0)
    assert (stage / "adjustment-0.png").is_file()
    assert len(record["region_sha256"]) == 64
    clamp = metadata["clamp_report"]
    assert clamp["clamped_points"] > 0  # 限幅不静默
    assert clamp["max_before_mm"] > CAP_MM
    assert clamp["cap_mm"] == pytest.approx(CAP_MM)
    assert any("限幅" in warning for warning in metadata["warnings"])
    with np.load(stage / "heightfield.npz") as data:
        assert data["heights_mm"].max() <= CAP_MM + 1e-12


def test_adjustment_shape_mismatch_rejected_before_export(tmp_path: Path) -> None:
    png = tmp_path / "bad_region.png"
    Image.fromarray(np.zeros((10, 10), dtype=np.uint8), mode="L").save(png)
    adjustment = LocalAdjustment(
        label="错形", region_png=str(png), offset_mm=1.0, transition_mm=1.0
    )
    with pytest.raises(ValueError, match="不一致"):
        _build(tmp_path, adjustments=(adjustment,))
    stage = tmp_path / "stage"
    assert not (stage / "master.stl").exists()  # 拒绝发生在任何产物写出之前


def test_nonfinite_depth_rejected_without_export(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="NaN"):
        _build(tmp_path, corrupt_with_nan=True)
    assert not (tmp_path / "stage" / "master.obj").exists()


def test_master_falloff_smooths_nonrectangular_boundary(tmp_path: Path) -> None:
    """P2 复验 R1：非矩形主体母版——域外过渡带连续落地（无垂直墙）；主体
    内部与关闭过渡的版本逐位一致；导出几何经 build_master 内建重读校验。"""
    rows, cols = 24, 48
    depth = np.repeat(np.linspace(1.0, 11.0, rows)[:, None], cols, axis=1)
    valid = np.zeros((rows, cols), dtype=bool)
    valid[4:20, 12:36] = True
    valid[8:14, 36:42] = True  # L 形外凸：边界含非轴对齐段
    npz = tmp_path / "depth-irregular.npz"
    np.savez_compressed(npz, depth=depth.astype(np.float32), valid=valid)
    band, cap, base = 3.0, 2.0, 2.0
    stage = tmp_path / "stage"
    stage.mkdir()
    metadata = PhotoGeometry().build_master(
        npz,
        {"depth_semantics": "relative_larger_nearer"},
        ReliefParameters(width_mm=24.0, depth_mm=cap, base_thickness_mm=base, falloff_band_mm=band),
        None,
        (),
        stage,
    )
    assert metadata["falloff"]["enabled"] is True
    assert metadata["falloff"]["raised_points"] > 0
    assert metadata["falloff"]["max_raised_mm"] > 0.0
    assert metadata["parameters"]["falloff_band_mm"] == pytest.approx(band)
    assert metadata["geometry_checks"]["top_surface_max_error_mm"] <= GEOM_TOL_MM
    with np.load(stage / "heightfield.npz") as data:
        heights, valid_geom = data["heights_mm"], data["valid"]

    stage_off = tmp_path / "stage-off"
    stage_off.mkdir()
    PhotoGeometry().build_master(
        npz,
        {"depth_semantics": "relative_larger_nearer"},
        ReliefParameters(width_mm=24.0, depth_mm=cap, base_thickness_mm=base, falloff_band_mm=0.0),
        None,
        (),
        stage_off,
    )
    with np.load(stage_off / "heightfield.npz") as off:
        heights_off = off["heights_mm"]
    assert (heights_off[~valid_geom] == 0.0).all()  # 旧行为：域外严格为 0（垂直墙来源）
    np.testing.assert_array_equal(heights[valid_geom], heights_off[valid_geom])  # 主体内部不变
    assert (heights[~valid_geom] > 0.0).any()  # 过渡带抬升域外近缘

    dx, dy = float(metadata["dx_mm"]), float(metadata["dy_mm"])
    jump = max(np.abs(np.diff(heights, axis=0)).max(), np.abs(np.diff(heights, axis=1)).max())
    # 连续性门：单格跳变 ≤ smoothstep 最大斜率 1.5×cap/band×单元尺寸
    # （旧垂直墙的单格跳变≈cap=2.0 mm）
    assert jump <= 1.5 * cap / band * max(dx, dy) + 1e-9
    assert jump < cap


def test_master_metadata_records_slope(tmp_path: Path) -> None:
    """P2 复验 R2：manifest 记录顶面坡度统计（全域/边界/域内分开，含角度）。"""
    _, metadata = _build(tmp_path)
    slope = metadata["slope"]
    assert slope["boundary_max_mm_per_mm"] == 0.0  # 矩形有效域无跨界对
    assert slope["interior_max_mm_per_mm"] > 0.0  # 行斜坡
    assert slope["max_overall_mm_per_mm"] == pytest.approx(slope["interior_max_mm_per_mm"])
    assert slope["interior_max_deg"] == pytest.approx(
        math.degrees(math.atan(slope["interior_max_mm_per_mm"]))
    )
