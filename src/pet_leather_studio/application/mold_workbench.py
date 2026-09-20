"""Use cases for imported masters and immutable mold revisions; no GUI or SQL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pet_leather_studio.domain.molds import GeometryPort, MoldParameters, RevisionPort


class MoldWorkbench:
    def __init__(self, store: RevisionPort, geometry: GeometryPort) -> None:
        self.store = store
        self.geometry = geometry

    def import_master(self, source: Path) -> dict[str, Any]:
        stage = self.store.begin()
        try:
            metadata = self.geometry.import_master(source, stage)
            metadata.update(kind="master", parent_id=None, input_method="source_import")
            return self.store.publish(stage, metadata)
        except BaseException:
            self.store.discard(stage)
            raise

    def generate(self, parameters: MoldParameters) -> dict[str, Any]:
        parameters.validate()
        stage = self.store.begin()
        try:
            parent = self.store.get()
            master_id = parent["id"] if parent["kind"] == "master" else parent["master_id"]
            self.store.verify(master_id)
            source = self.store.directory(master_id) / "master.vtp"
            metadata = self.geometry.generate(source, stage, parameters)
            metadata.update(
                kind="mold",
                parent_id=parent["id"],
                master_id=master_id,
                parameters=parameters.to_dict(),
                input_method="source_import",
            )
            return self.store.publish(stage, metadata)
        except BaseException:
            self.store.discard(stage)
            raise
