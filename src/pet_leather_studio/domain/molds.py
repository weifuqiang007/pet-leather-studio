"""Explicit design parameters for +Z mold candidates; all lengths are millimetres."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class MoldParameters:
    width_mm: float = 60.0
    depth_mm: float = 2.0
    gap_mm: float = 1.0
    backing_mm: float = 3.0
    grid_size: int = 128
    feature_mm: float = 0.5
    accept_top_projection: bool = False

    def validate(self) -> None:
        """Reject unsupported designs, not estimate leather forming limits."""
        for name, low, high in (
            ("width_mm", 5, 300),
            ("depth_mm", 0.05, 20),
            ("gap_mm", 0.05, 10),
            ("backing_mm", 1, 30),
            ("feature_mm", 0.05, 5),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} 必须在 {low}–{high} mm 范围")
        if type(self.grid_size) is not int or not 32 <= self.grid_size <= 512:
            raise ValueError("grid_size 必须是 32–512 的整数")
        if not self.accept_top_projection:
            raise ValueError("必须确认正面朝 +Z，并接受投影忽略背面/倒扣的限制")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GeometryPort(Protocol):
    def import_master(self, source: Path, destination: Path) -> dict[str, Any]: ...

    def generate(
        self, source: Path, destination: Path, parameters: MoldParameters
    ) -> dict[str, Any]: ...


class RevisionPort(Protocol):
    def begin(self) -> Path: ...

    def publish(self, stage: Path, metadata: dict[str, Any]) -> dict[str, Any]: ...

    def discard(self, stage: Path) -> None: ...

    def get(self, revision_id: str | None = None) -> dict[str, Any]: ...

    def directory(self, revision_id: str) -> Path: ...

    def verify(self, revision_id: str) -> None: ...

    def history(self) -> list[dict[str, Any]]: ...

    def activate(self, revision_id: str) -> None: ...
