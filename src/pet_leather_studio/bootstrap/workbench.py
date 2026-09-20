"""Composition root: wire concrete adapters, never from domain or UI."""

from pathlib import Path

from pet_leather_studio.application.mold_workbench import MoldWorkbench
from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.bootstrap.environment import app_root
from pet_leather_studio.infrastructure.mesh_geometry import MeshGeometry
from pet_leather_studio.infrastructure.photo_inference import ModelRegistry, PhotoInference
from pet_leather_studio.infrastructure.photo_io import PhotoIO
from pet_leather_studio.infrastructure.revisions import RevisionStore


def create_workbench(project: Path) -> MoldWorkbench:
    return MoldWorkbench(RevisionStore(project), MeshGeometry())


def create_photo_workbench(project: Path) -> PhotoWorkbench:
    root = app_root()
    return PhotoWorkbench(
        RevisionStore(project),
        PhotoIO(),
        PhotoInference(
            root / ".venv-photo" / "bin" / "python",
            root / "scripts" / "photo_inference_worker.py",
        ),
        ModelRegistry(root / "models"),
    )
