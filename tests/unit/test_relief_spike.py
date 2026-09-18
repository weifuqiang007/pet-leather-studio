"""M0.5 spike 算法单元测试（小网格快速验证；试验代码仅测试可导入）。

注意：experiments/ 不是生产包；生产层不得导入试验脚本（PRD M0.5）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DIR = REPO_ROOT / "experiments" / "relief_spike"
sys.path.insert(0, str(SPIKE_DIR))

import relief_spike as spike  # noqa: E402


def _annotation_dict(grid_nx: int = 64) -> dict[str, object]:
    return {
        "schema_version": 1,
        "image_size_px": [200, 200],
        "output_width_mm": 40.0,
        "base_thickness_mm": 2.0,
        "grid_nx": grid_nx,
        "seed": 0,
        "regions": [
            {
                "id": "nose",
                "polygon": [[100, 80], [120, 100], [110, 120], [90, 120], [80, 100]],
                "height_mm": 1.5,
                "falloff_px": 15,
            }
        ],
    }


def test_flat_slab_volume_is_analytic(tmp_path: Path) -> None:
    ann = {
        "schema_version": 1,
        "image_size_px": [200, 240],
        "output_width_mm": 40.0,
        "base_thickness_mm": 2.0,
        "grid_nx": 64,
        "seed": 0,
        "regions": [],
    }
    ann_path = tmp_path / "flat.json"
    import json

    ann_path.write_text(json.dumps(ann), encoding="utf-8")
    params = spike.load_annotation(ann_path)
    height, dx, dy = spike.build_heightfield(params)
    mesh = spike.heightfield_to_solid_mesh(height, dx, dy, params.base_thickness_mm)
    expected = 40.0 * 48.0 * 2.0  # W × H × base
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(expected, rel=1e-3)
    bbox_w = mesh.bounds[1][0] - mesh.bounds[0][0]
    assert abs(bbox_w - 40.0) <= 0.01  # AC-F03-03 对应


def test_mesh_closed_and_oriented(tmp_path: Path) -> None:
    ann = _annotation_dict()
    import json

    ann_path = tmp_path / "bump.json"
    ann_path.write_text(json.dumps(ann), encoding="utf-8")
    params = spike.load_annotation(ann_path)
    height, dx, dy = spike.build_heightfield(params)
    assert np.isfinite(height).all()
    mesh = spike.heightfield_to_solid_mesh(height, dx, dy, params.base_thickness_mm)
    assert mesh.is_watertight
    assert mesh.is_winding_consistent
    assert mesh.volume > 0
    # 底面在 z=0，顶面最小值不小于底厚
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-9)
    assert mesh.bounds[1][2] >= 2.0


def test_y_axis_flip_maps_image_top_to_max_y() -> None:
    """图像顶部区域应映射到工件 y 较大一侧（PRD 6.1）。"""
    ann = {
        "schema_version": 1,
        "image_size_px": [100, 100],
        "output_width_mm": 10.0,
        "base_thickness_mm": 1.0,
        "grid_nx": 50,
        "seed": 0,
        "regions": [
            {
                "id": "top_mark",
                "polygon": [[50, 10], [60, 10], [60, 20], [50, 20]],
                "height_mm": 1.0,
                "falloff_px": 5,
            }
        ],
    }
    import json

    path = SPIKE_DIR / "out_test_yflip.json"
    try:
        path.write_text(json.dumps(ann), encoding="utf-8")
        params = spike.load_annotation(path)
        height, _, _ = spike.build_heightfield(params)
        peak_row = int(np.argmax(height.max(axis=1)))
        # 图像顶部（v≈15px）应落在工件 y 大的一侧 → 数组靠后的行
        assert peak_row > height.shape[0] * 0.7
    finally:
        path.unlink(missing_ok=True)


def test_deterministic_rebuild(tmp_path: Path) -> None:
    import json

    ann_path = tmp_path / "det.json"
    ann_path.write_text(json.dumps(_annotation_dict()), encoding="utf-8")
    params = spike.load_annotation(ann_path)
    h1, dx1, _ = spike.build_heightfield(params)
    h2, dx2, _ = spike.build_heightfield(params)
    np.testing.assert_array_equal(h1, h2)
    assert dx1 == dx2


def test_rejects_bad_annotations(tmp_path: Path) -> None:
    import json

    bad = _annotation_dict()
    bad["output_width_mm"] = -5.0
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="正"):
        spike.load_annotation(path)

    bad2 = _annotation_dict()
    bad2["regions"] = [{"id": "x", "polygon": [[0, 0]], "height_mm": 1, "falloff_px": 5}]
    path2 = tmp_path / "bad2.json"
    path2.write_text(json.dumps(bad2), encoding="utf-8")
    with pytest.raises(ValueError, match="3 点"):
        spike.load_annotation(path2)
