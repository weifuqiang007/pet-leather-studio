"""Composition root: wire concrete adapters, never from domain or UI."""

from pathlib import Path

from pet_leather_studio.application.leather_mold_workbench import LeatherMoldWorkbench
from pet_leather_studio.application.mold_workbench import MoldWorkbench
from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.bootstrap.environment import app_root, data_root
from pet_leather_studio.infrastructure.leather_mold_geometry import LeatherMoldGeometry
from pet_leather_studio.infrastructure.mesh_geometry import MeshGeometry
from pet_leather_studio.infrastructure.photo_geometry import PhotoGeometry
from pet_leather_studio.infrastructure.photo_inference import ModelRegistry, PhotoInference
from pet_leather_studio.infrastructure.photo_io import PhotoIO
from pet_leather_studio.infrastructure.reference_profile import ReferenceProfileStore
from pet_leather_studio.infrastructure.revisions import RevisionStore


def create_workbench(project: Path) -> MoldWorkbench:
    return MoldWorkbench(RevisionStore(project), MeshGeometry())


def create_leather_mold_workbench(project: Path) -> LeatherMoldWorkbench:
    """皮革阴阳模服务与照片工程共用同一 RevisionStore（kind=mold_pair）。"""
    return LeatherMoldWorkbench(RevisionStore(project), LeatherMoldGeometry())


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
        PhotoGeometry(),
        ReferenceProfileStore(data_root() / "profiles"),
    )
