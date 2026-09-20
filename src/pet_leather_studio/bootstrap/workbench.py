"""Composition root: wire concrete adapters, never from domain or UI."""

from pathlib import Path

from pet_leather_studio.application.mold_workbench import MoldWorkbench
from pet_leather_studio.infrastructure.mesh_geometry import MeshGeometry
from pet_leather_studio.infrastructure.revisions import RevisionStore


def create_workbench(project: Path) -> MoldWorkbench:
    return MoldWorkbench(RevisionStore(project), MeshGeometry())
