"""PH05：参考标定——包围盒与有效浮雕高度分开记录、口径显式、可重跑、损坏显式报错。"""

import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from pet_leather_studio.domain.errors import ResourceMissingError
from pet_leather_studio.domain.photo_relief import (
    HeightMode,
    ReferenceProfile,
    ReliefParameters,
)
from pet_leather_studio.infrastructure.reference_profile import (
    ReferenceProfileStore,
    excluded_points,
    measure_reference,
)


def _write_reference_obj(path: Path, scale: float = 1.0, with_spikes: bool = True) -> None:
    """21×16 表面网格：0 底 + 4 mm 主凸（20 点）+ 6 mm 尖点（2/336≈0.6%<1%）。

    percentile=99 时 z_cut 落在 4.0：有效起伏 4 mm，与包围盒 Z 跨度 6 mm 分离。
    """
    xs = np.linspace(0.0, 20.0, 21) * scale
    ys = np.linspace(0.0, 15.0, 16) * scale
    xx, yy = np.meshgrid(xs, ys)
    zz = np.zeros_like(xx)
    zz[(yy > 5 * scale) & (yy < 10 * scale) & (xx > 7 * scale) & (xx < 13 * scale)] = 4.0 * scale
    if with_spikes:
        zz[8, 10] = 6.0 * scale
        zz[8, 11] = 6.0 * scale
    ny, nx = zz.shape
    index = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)).ravel()
    b, c, d = index + 1, index + nx + 1, index + nx
    faces = np.vstack([np.column_stack([index, b, c]), np.column_stack([index, c, d])])
    points = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
    trimesh.Trimesh(points, faces, process=False).export(path)


def test_effective_relief_recorded_separately_from_bbox_span(tmp_path: Path) -> None:
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0)
    assert profile.effective_relief_mm == pytest.approx(4.0)  # 分位裁剪后的有效起伏
    assert profile.bbox_z_span == pytest.approx(6.0)  # 包围盒跨度分开记录，仅历史对照
    assert profile.bbox_z_span_ratio == pytest.approx(6.0 / 20.0)
    assert profile.datum_z == pytest.approx(0.0)
    assert profile.datum_method == "min_z_plane"
    assert profile.percentile == 99.0
    assert profile.region_basis == "full_xy_bounds_v1"
    assert profile.region == pytest.approx((0.0, 20.0, 0.0, 15.0))
    assert profile.reference_width_mm == pytest.approx(20.0)
    assert profile.source_units == "assumed_mm"


def test_true_extremes_retained_with_exclusion_stats(tmp_path: Path) -> None:
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0)
    assert profile.true_min_z == pytest.approx(0.0)
    assert profile.true_max_z == pytest.approx(6.0)  # 尖点不被分位裁掉而丢失
    assert profile.true_excess_mm == pytest.approx(2.0)  # 鼻尖超出量
    assert profile.excluded_point_count == 2
    assert profile.exclusion_fraction == pytest.approx(2 / 336, abs=1e-6)


def test_region_selection_precedes_quantile(tmp_path: Path) -> None:
    """区域选择先于分位数：区域外尖点不入有效起伏统计，但入真实极值。"""
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0, region=(0.0, 9.5, 0.0, 15.0))
    assert profile.region_basis == "cli_override"
    assert profile.effective_relief_mm == pytest.approx(4.0)  # 主凸在区域内
    assert profile.excluded_point_count == 0  # 区域内无超过 z_cut 的点
    assert profile.true_max_z == pytest.approx(6.0)  # 区域外尖点保留在真实极值


def test_deterministic_profile_id_and_scale_rerun(tmp_path: Path) -> None:
    """同输入重测同 profile_id；几何等比缩放后起伏/宽度等比（可重跑）。"""
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    first = measure_reference(obj, percentile=99.0)
    second = measure_reference(obj, percentile=99.0)
    assert first.profile_id == second.profile_id
    assert first.effective_relief_mm == second.effective_relief_mm

    scaled = tmp_path / "reference_scaled.obj"
    _write_reference_obj(scaled, scale=2.0)
    big = measure_reference(scaled, percentile=99.0)
    assert big.effective_relief_mm == pytest.approx(8.0)
    assert big.reference_width_mm == pytest.approx(40.0)
    ratio_first = first.effective_relief_mm / first.reference_width_mm
    assert big.effective_relief_mm / big.reference_width_mm == pytest.approx(ratio_first)


def test_store_roundtrip_and_corruption_errors(tmp_path: Path) -> None:
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0)
    store = ReferenceProfileStore(tmp_path / "profiles")

    assert store.list_profiles() == []
    path = store.save(profile)
    assert path.is_file()
    assert store.load(profile.profile_id) == profile
    assert [item.profile_id for item in store.list_profiles()] == [profile.profile_id]

    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ResourceMissingError, match="无法解析"):
        store.load(profile.profile_id)

    path.write_text(json.dumps({"profile_id": "ref-x", "region": [1, 2]}), encoding="utf-8")
    with pytest.raises(ResourceMissingError, match="字段不完整或非法"):
        store.load(profile.profile_id)

    with pytest.raises(ResourceMissingError, match="不存在"):
        store.load("ref-missing0000000000")


def test_store_rejects_path_like_profile_id(tmp_path: Path) -> None:
    store = ReferenceProfileStore(tmp_path / "profiles")
    with pytest.raises(ValueError, match="非法 profile_id"):
        store.load("../outside")


def test_json_roundtrip_preserves_profile(tmp_path: Path) -> None:
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0)
    restored = ReferenceProfile.from_mapping(json.loads(json.dumps(profile.to_json_dict())))
    assert restored == profile


def test_excluded_points_for_review_and_hash_guard(tmp_path: Path) -> None:
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0)
    points = excluded_points(obj, profile)
    assert points.shape == (2, 3)
    assert np.all(points[:, 2] == pytest.approx(6.0))  # 被裁的正是尖点

    original = obj.read_text(encoding="utf-8")
    obj.write_text(original + "# touched\n", encoding="utf-8")  # 内容变化但仍可读
    with pytest.raises(ResourceMissingError, match="sha256 不匹配"):
        excluded_points(obj, profile)
    obj.unlink()
    with pytest.raises(ResourceMissingError, match="不存在"):
        excluded_points(obj, profile)


def test_measure_rejects_bad_inputs(tmp_path: Path) -> None:
    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    with pytest.raises(ValueError, match="percentile"):
        measure_reference(obj, percentile=0.0)
    with pytest.raises(ValueError, match="xmin<xmax"):
        measure_reference(obj, region=(10.0, 5.0, 0.0, 15.0))
    with pytest.raises(ValueError, match="没有顶点"):
        measure_reference(obj, region=(100.0, 101.0, 100.0, 101.0))
    with pytest.raises(ResourceMissingError, match="不存在"):
        measure_reference(tmp_path / "missing.obj")


def test_reference_ratio_without_profile_rejected() -> None:
    """缺 profile 禁止参考模式（ReliefParameters 层即拒绝，不暗用包围盒比例）。"""
    with pytest.raises(ValueError, match="profile_id"):
        ReliefParameters(height_mode=HeightMode.REFERENCE_RATIO).validate()
