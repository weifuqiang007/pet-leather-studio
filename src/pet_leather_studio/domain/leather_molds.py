"""皮革压制阴阳模参数合同（MOLD-PAIR 规划书 §4）；标准库 only。

LeatherMoldParameters 全字段进入 manifest；任何修改都产生新模具修订。
t_effective 是压制有效皮厚（实测厚度 − 压实余量，下限最小间隙），
只依赖标量运算，放 domain 供应用/算法共用同一口径。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

LEATHER_THICKNESS_MM_RANGE = (0.5, 6.0)
COMPRESSION_ALLOWANCE_MM_RANGE = (0.0, 1.0)
MIN_CLEARANCE_MM_RANGE = (0.1, 2.0)
MOLD_BACKING_MM_RANGE = (2.0, 20.0)
EDGE_MARGIN_MM_RANGE = (2.0, 15.0)
MAX_PLATE_MM_RANGE = (40.0, 300.0)
SAMPLING_FEATURE_MM_RANGE = (0.05, 2.0)
SAMPLING_MODES = ("native", "resample")
MOLD_ALGORITHM = "leather-mold-pair-v1"
EXTERNAL_JIG_NOTE = (
    "external_jig 定位：M1 只输出主模具实体与定位说明（README），"
    "定位柱/孔与排气槽留到 M3，不作为未生效的自由参数"
)


@dataclass(frozen=True)
class LeatherMoldParameters:
    """压制参数（规划书 §4 参数表；建议范围即 validate 的硬范围）。"""

    leather_thickness_mm: float = 2.0
    compression_allowance_mm: float = 0.15
    min_clearance_mm: float = 0.3
    backing_mm: float = 5.0
    edge_margin_mm: float = 4.0
    max_plate_mm: float = 120.0
    sampling_feature_mm: float = 0.2
    sampling_mode: str = "native"

    def validate(self) -> None:
        """拒绝超出建议范围的参数；压实余量必须小于皮厚（t_effective>0 前提）。"""
        for name, low, high in (
            ("leather_thickness_mm", *LEATHER_THICKNESS_MM_RANGE),
            ("compression_allowance_mm", *COMPRESSION_ALLOWANCE_MM_RANGE),
            ("min_clearance_mm", *MIN_CLEARANCE_MM_RANGE),
            ("backing_mm", *MOLD_BACKING_MM_RANGE),
            ("edge_margin_mm", *EDGE_MARGIN_MM_RANGE),
            ("max_plate_mm", *MAX_PLATE_MM_RANGE),
            ("sampling_feature_mm", *SAMPLING_FEATURE_MM_RANGE),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} 必须在 {low}–{high} mm 范围")
        if self.compression_allowance_mm >= self.leather_thickness_mm:
            raise ValueError("compression_allowance_mm 必须小于皮革实测厚度（压实后仍需正厚度）")
        if self.sampling_mode not in SAMPLING_MODES:
            raise ValueError(f"sampling_mode 必须是 {'/'.join(SAMPLING_MODES)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def effective_thickness_mm(parameters: LeatherMoldParameters) -> float:
    """t_effective = max(最小间隙, 皮厚 − 压实余量)（规划书 §3.2）。"""
    return max(
        parameters.min_clearance_mm,
        parameters.leather_thickness_mm - parameters.compression_allowance_mm,
    )


class LeatherMoldGeometryPort(Protocol):
    def generate_leather_molds(
        self,
        heightfield_npz: Path,
        master_metadata: dict[str, Any],
        parameters: LeatherMoldParameters,
        stage: Path,
    ) -> dict[str, Any]:
        """从照片母版原生高度场生成阴阳模修订文件；几何验收失败必须抛错。"""
        ...
