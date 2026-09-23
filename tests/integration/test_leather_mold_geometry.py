"""MOLD-PAIR M1 集成（几何）：照片母版高度场 → 阴阳模文件集与独立验收。

直接驱动 LeatherMoldGeometry（应用层链路见 test_leather_mold_revisions.py）：
文件集齐全、OBJ/STL 重读水密、mold_pair.npz 字段与 manifest 一致、
独立最近距离 ≥ t_eff−容差、扩边核心逐位不变、止口足够时不扩边、
超版面/非有限高度场显式拒绝。
"""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from pet_leather_studio.algorithms.leather_mold_pair import distance_tolerance_mm
from pet_leather_studio.domain.leather_molds import (
    LeatherMoldParameters,
    effective_thickness_mm,
)
from pet_leather_studio.infrastructure.leather_mold_geometry import (
    GEOM_TOL_MM,
    GUARD_STEPS,
    LeatherMoldGeometry,
)

MASTER_ID = "11111111-2222-3333-4444-555555555555"


def _write_heightfield(path: Path, heights: np.ndarray, valid: np.ndarray) -> None:
    ny, nx = heights.shape
    np.savez_compressed(
        path,
        heights_mm=heights.astype(np.float64),
        valid=valid,
        dx_mm=1.0,
        dy_mm=1.0,
        width_mm=float(nx - 1),
        height_mm=float(ny - 1),
    )


def _ramp(ny: int = 16, nx: int = 49) -> np.ndarray:
    return np.repeat(np.linspace(0.2, 2.0, ny)[:, None], nx, axis=1)


def _generate(
    tmp_path: Path, heights: np.ndarray, valid: np.ndarray, parameters=None
) -> tuple[dict, Path]:
    source = tmp_path / "heightfield.npz"
    _write_heightfield(source, heights, valid)
    stage = tmp_path / "stage"
    stage.mkdir()
    metadata = LeatherMoldGeometry().generate_leather_molds(
        source,
        {"id": MASTER_ID, "falloff": {"band_mm": 2.5}},
        parameters or LeatherMoldParameters(),
        stage,
    )
    return metadata, stage


def test_generate_full_file_set_and_independent_clearance(tmp_path: Path) -> None:
    metadata, stage = _generate(tmp_path, _ramp(), np.ones((16, 49), dtype=bool))

    assert {
        "male.obj",
        "male.stl",
        "male.vtp",
        "female.obj",
        "female.stl",
        "female.vtp",
        "mold_pair.npz",
        "assembly_preview.vtp",
        "README.txt",
    } <= {item.name for item in stage.iterdir()}
    t_eff = effective_thickness_mm(LeatherMoldParameters())
    tolerance = distance_tolerance_mm(1.0, 1.0)
    assert metadata["target_effective_thickness_mm"] == pytest.approx(t_eff)
    assert metadata["master_revision_id"] == MASTER_ID
    assert metadata["manufacturing_validated"] is False
    check = metadata["clearance_independent"]
    assert check["min_mm"] >= t_eff - tolerance  # 独立测距验收（§7）
    assert check["guard_mm"] in {step * tolerance for step in GUARD_STEPS}
    # M1-R1：验收器是精确点到三角面（重心细分采样 + 半径证书），可复算
    assert "point-to-triangle" in check["method"]
    assert check["certified"] is True
    assert check["subdivision_order"] >= 2
    assert (
        check["points_per_face"]
        == (check["subdivision_order"] + 1) * (check["subdivision_order"] + 2) // 2
    )
    # 采样数按扩边后网格算：全有效 16×49 ramp → 扩边 grid 30×63 → 面 2×29×62
    grid_ny, grid_nx = metadata["plate"]["grid"]
    face_count = 2 * (grid_ny - 1) * (grid_nx - 1)
    assert check["samples_a"] == check["points_per_face"] * face_count
    assert check["samples_b"] == check["samples_a"]
    assert check["conservative_min_mm"] == pytest.approx(
        check["min_mm"] - check["sampling_bound_mm"]
    )
    assert metadata["envelope_kernel"]["subdivision_order"] == check["subdivision_order"]
    assert metadata["envelope_kernel"]["radius_mm"] >= t_eff
    assert metadata["geometry_checks"]["watertight"] is True
    assert metadata["geometry_checks"]["surface_max_error_mm"] <= GEOM_TOL_MM
    assert metadata["axial_gap_min_mm"] > 0.0
    # 采样间距 1.0 mm > feature/4=0.05 → 分辨率不足警告必须给出
    assert any("源分辨率不足" in warning for warning in metadata["warnings"])
    assert metadata["slope"]["max_deg"] < 45.0  # 平缓斜坡不触发陡坡警告
    assert not any("陡坡" in warning for warning in metadata["warnings"])

    with np.load(stage / "mold_pair.npz") as pair:
        assert pair["independent_min_distance_mm"] == pytest.approx(check["min_mm"])
        assert pair["independent_a_to_b_mm"] == pytest.approx(check["a_to_b_mm"])
        assert pair["independent_b_to_a_mm"] == pytest.approx(check["b_to_a_mm"])
        assert pair["independent_sampling_bound_mm"] == pytest.approx(check["sampling_bound_mm"])
        assert int(pair["subdivision_order"]) == check["subdivision_order"]
        assert "point-to-triangle" in str(pair["distance_method"])
        assert pair["male_contact_mm"].shape == tuple(metadata["plate"]["grid"])
        assert np.all(pair["normal_clearance_mm"] <= pair["axial_gap_mm"] + 1e-12)
        assert bool(pair["flat_stop"][0, 0])  # 扩边后版缘是纯平止口


def test_expanded_core_bitwise_and_reloaded_solids(tmp_path: Path) -> None:
    heights = _ramp()
    metadata, stage = _generate(tmp_path, heights, np.ones((16, 49), dtype=bool))

    expansion = metadata["expansion"]
    assert expansion["expanded"]  # 全有效域（无平边）→ 必须扩
    rows, cols = expansion["core_rows"], expansion["core_cols"]
    with np.load(stage / "mold_pair.npz") as pair, np.load(tmp_path / "heightfield.npz") as src:
        assert np.array_equal(
            pair["male_contact_mm"][rows[0] : rows[1], cols[0] : cols[1]], src["heights_mm"] + 5.0
        )  # 核心逐位 = 源 + 底板
    assert metadata["core_bitwise_preserved"] is True
    assert metadata["plate"]["final_width_mm"] > metadata["plate"]["source_width_mm"]

    female = trimesh.load_mesh(stage / "female.obj", process=True)
    assert female.is_watertight and female.volume > 0
    with np.load(stage / "mold_pair.npz") as pair:
        bounds = female.bounds
        assert bounds[0, 0] == pytest.approx(0.0, abs=GEOM_TOL_MM)
        assert bounds[1, 0] == pytest.approx(metadata["plate"]["final_width_mm"], abs=GEOM_TOL_MM)
        assert bounds[0, 2] == pytest.approx(float(pair["female_inner_mm"].min()), abs=GEOM_TOL_MM)


def test_no_expansion_when_flat_stop_sufficient(tmp_path: Path) -> None:
    valid = np.zeros((20, 61), dtype=bool)
    valid[7:13, 7:54] = True  # 四周 ≥ 7 mm 余量（带宽 2.5 → 止口 4.5 ≥ 4）
    metadata, stage = _generate(tmp_path, _ramp(20, 61), valid)

    assert metadata["border_clearance_mm"] == pytest.approx(7.0)
    assert metadata["existing_flat_stop_mm"] == pytest.approx(4.5)
    assert not metadata["expansion"]["expanded"]
    assert metadata["plate"]["final_width_mm"] == pytest.approx(60.0)
    assert metadata["plate"]["grid"] == [20, 61]
    with np.load(stage / "mold_pair.npz") as pair:
        assert not pair["flat_stop"].any()  # 斜坡母版本体无纯平区
        assert np.array_equal(pair["valid_subject"], valid)


def test_steep_relief_flags_slope_warning(tmp_path: Path) -> None:
    heights = np.zeros((20, 61))
    heights[10:, :] = 2.0  # 2 mm 断崖 / 1 mm 格距 → 63.4°
    metadata, _stage = _generate(tmp_path, heights, np.ones((20, 61), dtype=bool))
    assert metadata["slope"]["max_deg"] > 45.0
    assert any("陡坡" in warning for warning in metadata["warnings"])


def test_oversize_plate_rejected_before_any_file(tmp_path: Path) -> None:
    source = tmp_path / "heightfield.npz"
    _write_heightfield(source, _ramp(), np.ones((16, 49), dtype=bool))
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(ValueError, match="max_plate_mm"):
        LeatherMoldGeometry().generate_leather_molds(
            source,
            {"id": MASTER_ID},
            LeatherMoldParameters(max_plate_mm=60.0),  # 扩边后 62 mm 超限
            stage,
        )
    assert list(stage.iterdir()) == []  # 拒绝发生在写文件之前


def test_non_finite_heights_rejected(tmp_path: Path) -> None:
    heights = _ramp()
    heights[5, 5] = np.nan
    with pytest.raises(ValueError, match="非有限"):
        _generate(tmp_path, heights, np.ones((16, 49), dtype=bool))


def test_real_master_heightfield_schema_compatible(tmp_path: Path) -> None:
    """真实 PhotoGeometry.build_master 产物（schema v2）可直接进模具几何。"""

    from test_photo_geometry import (
        _build,  # noqa: PLC0415  同目录桩链（sys.path 含 tests/integration）
    )

    stage_master, built = _build(tmp_path)
    mold_stage = tmp_path / "mold"
    mold_stage.mkdir()
    metadata = LeatherMoldGeometry().generate_leather_molds(
        stage_master / "heightfield.npz",
        {**built, "id": MASTER_ID},
        LeatherMoldParameters(),
        mold_stage,
    )
    assert metadata["plate"]["grid"][1] == built["grid"][1] + 2 * metadata["expansion"]["pad_x_px"]
    assert (mold_stage / "README.txt").read_text(encoding="utf-8").startswith("皮革压制阴阳模候选")
