"""Local Qt/VTK regression: light restoration, child-process generation and activation."""

from pathlib import Path

import numpy as np

from pet_leather_studio.bootstrap import environment

environment.apply_local_env()

from pet_leather_studio.algorithms.mold_solids import solid_between  # noqa: E402
from pet_leather_studio.bootstrap.workbench import create_workbench  # noqa: E402
from pet_leather_studio.presentation.workbench import WorkbenchWindow  # noqa: E402


def test_workbench_generate_and_restore(qtbot, tmp_path: Path):
    source = tmp_path / "source.stl"
    h = np.tile(np.linspace(1, 2, 6), (6, 1))
    solid_between(np.zeros_like(h), h, 10, 10).export(source)
    service = create_workbench(tmp_path / "project")
    master = service.import_master(source)
    window = WorkbenchWindow(service, tmp_path / "project")
    qtbot.addWidget(window)
    window.show()
    assert len(window.viewer.renderer.lights) > 0
    window.grid.setCurrentText("64")
    window.consent.setChecked(True)
    window.generate()
    qtbot.waitUntil(lambda: window.process is None, timeout=30000)
    assert len(service.store.history()) == 2
    assert service.store.get()["kind"] == "mold"
    assert len(window.viewer.renderer.lights) > 0
    window.versions.setCurrentIndex(window.versions.findData(master["id"]))
    window.activate()
    assert service.store.get()["id"] == master["id"]
    assert len(service.store.history()) == 2
    window.close()
