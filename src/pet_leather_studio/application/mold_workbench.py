"""Use cases for imported masters and immutable mold revisions; no GUI or SQL."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pet_leather_studio.domain.molds import GeometryPort, MoldParameters, RevisionPort

PHOTO_CHAIN_KINDS = ("photo", "mask", "depth")


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

    def _resolve_master_id(self, parent: dict[str, Any]) -> str:
        kind = parent.get("kind")
        if kind == "master":
            return str(parent["id"])
        if kind == "mold":
            return str(parent["master_id"])
        if kind in PHOTO_CHAIN_KINDS:
            raise ValueError(
                f"当前修订是 {kind}（照片链中间产物）；请先生成/激活 master 母版后再生成模具"
            )
        raise ValueError(f"当前修订类型 {kind!r} 不能生成模具；请激活 master 母版")

    def generate(self, parameters: MoldParameters) -> dict[str, Any]:
        parameters.validate()
        stage = self.store.begin()
        try:
            parent = self.store.get()
            master_id = self._resolve_master_id(parent)
            self.store.verify(master_id)
            master = self.store.get(master_id)
            input_method = master.get("input_method")
            if not input_method:
                raise ValueError("母版缺少 input_method 记录，拒绝继承来源")
            source = self.store.directory(master_id) / "master.vtp"
            metadata = self.geometry.generate(source, stage, parameters)
            metadata.update(
                kind="mold",
                parent_id=parent["id"],
                master_id=master_id,
                parameters=parameters.to_dict(),
                input_method=input_method,
            )
            return self.store.publish(stage, metadata)
        except BaseException:
            self.store.discard(stage)
            raise
