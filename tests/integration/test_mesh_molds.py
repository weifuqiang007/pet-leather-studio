"""Use the real VTK ray sampler, STL exports and version store (without rendering)."""

import numpy as np
import trimesh

from pet_leather_studio.algorithms.mold_solids import solid_between
from pet_leather_studio.bootstrap.workbench import create_workbench
from pet_leather_studio.domain.molds import MoldParameters


def test_real_mesh_to_mold_pair(tmp_path):
    h = np.tile(np.linspace(1, 3, 9), (9, 1))
    source = tmp_path / "倾斜 母版.stl"
    solid_between(np.zeros_like(h), h, 10, 10).export(source)
    service = create_workbench(tmp_path / "project")
    master = service.import_master(source)
    result = service.generate(MoldParameters(grid_size=32, accept_top_projection=True))
    assert result["master_id"] == master["id"]
    assert result["coverage"] > 0.9
    assert not result["sampling_sufficient"]
    assert result["manufacturing_validated"] is False
    folder = service.store.directory(result["id"])
    for name in ("male", "female"):
        mesh = trimesh.load_mesh(folder / f"{name}.stl")
        assert mesh.is_watertight and mesh.volume > 0
    with np.load(folder / "heightfield.npz") as data:
        assert data["height_mm"].max() == 2
