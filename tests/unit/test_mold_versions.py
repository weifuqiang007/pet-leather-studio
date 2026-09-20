"""Geometry contracts and immutable history; no render window required."""

from pathlib import Path

import numpy as np
import pytest

from pet_leather_studio.algorithms.mold_solids import mold_pair
from pet_leather_studio.application.mold_workbench import MoldWorkbench
from pet_leather_studio.domain.molds import MoldParameters
from pet_leather_studio.infrastructure.revisions import RevisionStore, file_hash


def test_mold_pair_gap_and_volume():
    h = np.tile(np.linspace(0, 2, 8), (5, 1))
    male, female = mold_pair(h, 20, 10, 1.2, 3)
    n = h.size
    np.testing.assert_allclose(female.vertices[:n, 2] - male.vertices[n:, 2], 1.2)
    assert male.is_watertight and female.is_watertight
    assert male.is_winding_consistent and female.is_winding_consistent
    assert male.volume == pytest.approx(20 * 10 * 4)
    assert female.volume == pytest.approx(20 * 10 * 4)


@pytest.mark.parametrize(
    "changes",
    [
        {"width_mm": float("nan")},
        {"gap_mm": -1},
        {"grid_size": 1024},
        {"grid_size": 32.5},
        {"accept_top_projection": False},
    ],
)
def test_parameters_reject_invalid(changes):
    values = MoldParameters(accept_top_projection=True).to_dict() | changes
    with pytest.raises(ValueError):
        MoldParameters(**values).validate()


class FakeGeometry:
    def import_master(self, source, destination):
        (destination / "master.vtp").write_text("test-master")
        return {"algorithm": "fake-test-only"}

    def generate(self, source, destination, parameters):
        (destination / "male.stl").write_text(str(parameters.gap_mm))
        return {"algorithm": "fake-test-only"}


def test_rollback_and_branch_preserve_files(tmp_path):
    store = RevisionStore(tmp_path / "工程 空格")
    service = MoldWorkbench(store, FakeGeometry())
    master = service.import_master(Path("unused"))
    first = service.generate(MoldParameters(accept_top_projection=True))
    before = file_hash(store.directory(first["id"]) / "male.stl")
    second = service.generate(MoldParameters(gap_mm=2, accept_top_projection=True))
    store.activate(first["id"])
    assert store.get()["id"] == first["id"]
    third = service.generate(MoldParameters(gap_mm=3, accept_top_projection=True))
    assert third["parent_id"] == first["id"]
    assert third["master_id"] == master["id"]
    assert store.get(second["id"])["parameters"]["gap_mm"] == 2
    assert file_hash(store.directory(first["id"]) / "male.stl") == before
    assert len(store.history()) == 4


def test_failed_generation_keeps_active(tmp_path):
    class FailingGeometry(FakeGeometry):
        def generate(self, source, destination, parameters):
            (destination / "partial").write_text("broken")
            raise RuntimeError("simulated failure")

    store = RevisionStore(tmp_path)
    service = MoldWorkbench(store, FailingGeometry())
    original = service.import_master(Path("unused"))
    with pytest.raises(RuntimeError):
        service.generate(MoldParameters(accept_top_projection=True))
    assert store.get()["id"] == original["id"]
    assert not list((tmp_path / "staging").iterdir())


def test_modified_revision_cannot_activate(tmp_path):
    store = RevisionStore(tmp_path)
    service = MoldWorkbench(store, FakeGeometry())
    original = service.import_master(Path("unused"))
    (store.directory(original["id"]) / "master.vtp").write_text("tampered")
    with pytest.raises(ValueError, match="文件已变化"):
        store.activate(original["id"])
    with pytest.raises(ValueError):
        store.directory("../../outside")


def test_second_writer_cannot_modify_active(tmp_path):
    first, second = RevisionStore(tmp_path), RevisionStore(tmp_path)
    stage = first.begin()
    try:
        with pytest.raises(ValueError, match="另一个任务"):
            second.begin()
    finally:
        first.discard(stage)
    stage = second.begin()
    second.discard(stage)


def test_generation_refuses_changed_master(tmp_path):
    store = RevisionStore(tmp_path)
    service = MoldWorkbench(store, FakeGeometry())
    master = service.import_master(Path("unused"))
    (store.directory(master["id"]) / "master.vtp").write_text("tampered")
    with pytest.raises(ValueError, match="文件已变化"):
        service.generate(MoldParameters(accept_top_projection=True))
    assert len(store.history()) == 1
    assert not list((tmp_path / "staging").iterdir())
