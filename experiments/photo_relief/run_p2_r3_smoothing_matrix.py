#!/usr/bin/env python3
"""P2 复验 R3 附加实验①：平滑半径矩阵（显式 2 mm 与参考比例 8.35 mm 两类）。

运行（真机）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_r3_smoothing_matrix.py

独立验收 R3 必修第 2 点：R2 只验证过 2 mm 显式 + 1.5 mm 平滑一条臂，不能外推
到比例高度模式。本脚本对短毛犬同一条 depth 修订跑 2（高度模式）× 4（平滑
0/1.0/1.5/2.0 mm）= 8 臂，逐臂记录三类坡度、细节保留率（detail_retention，
数值代理非视觉评审）、manifest 警告与版边最大抬升，渲染侧视/斜视对照。
带宽取各自模式的 R2 建议值（显式 3.0 / 比例 12.6）。输出
experiments/photo_relief/out/p2-r3-smoothing-matrix/（gitignored），含
report_data.json；重跑在同一工程库追加新母版修订（修订史 append-only）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv

from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import (
    HeightMode,
    ReliefParameters,
    suggested_falloff_band_mm,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out" / "p2-r3-smoothing-matrix"
PROJECT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433" / "short_hair_dog"
DEPTH_PREFIX = "8a18d7ed"
PROFILE_ID = "ref-5c1ae382ab802ef6"  # PH05 真实标定（run_p2_masters 同一来源）
WIDTH_MM = 60.0
BASE_THICKNESS_MM = 3.0
EXPLICIT_DEPTH_MM = 2.0
RATIO_RESOLVED_MM = 8.352107938604037  # 2.679…/19.283…×60（run_p2_falloff_bands 实测）
SMOOTHING_RADII = (None, 1.0, 1.5, 2.0)  # 未平滑 + R3 三档


def locate_depth(store: Any, prefix: str) -> str:
    depths = [row["id"] for row in store.history() if row.get("kind") == "depth"]
    matched = [revision_id for revision_id in depths if revision_id.startswith(prefix)]
    if len(matched) == 1:
        return matched[0]
    raise SystemExit(f"无法唯一定位短毛犬 depth 修订（前缀 {prefix}，候选 {depths}）")


def border_max_mm(heightfield_npz: Path) -> float:
    """版面边框（四缘）最大高度：>0 即过渡带/平滑抬起了版边。"""
    with np.load(heightfield_npz) as data:
        heights = np.asarray(data["heights_mm"], dtype=np.float64)
    border = np.concatenate([heights[0, :], heights[-1, :], heights[:, 0], heights[:, -1]])
    return float(border.max())


def render(preview_vtp: Path, tag: str) -> list[str]:
    mesh = pv.read(preview_vtp)
    shots: list[str] = []
    for view_name, method in (("side", "view_xz"), ("iso", "view_isometric")):
        plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
        plotter.set_background("#2b3038")
        plotter.add_mesh(mesh, color="ivory", smooth_shading=True)
        plotter.enable_lightkit()
        getattr(plotter, method)()
        path = OUT / f"{tag}-{view_name}-lightkit.png"
        plotter.show(screenshot=str(path))
        shots.append(str(path))
    return shots


def build_arm(
    service: Any, depth_id: str, tag: str, parameters: ReliefParameters
) -> dict[str, Any]:
    started = time.time()
    summary = service.build_master(depth_id, parameters)
    manifest = service.store.get(summary.revision_id)
    directory = service.store.directory(summary.revision_id)
    return {
        "tag": tag,
        "master_revision": summary.revision_id,
        "parameters": manifest["parameters"],
        "elapsed_s": round(time.time() - started, 1),
        "falloff": manifest["falloff"],
        "slope": manifest["slope"],
        "smoothing": manifest["smoothing"],
        "warnings": manifest["warnings"],
        "border_max_mm": round(border_max_mm(directory / "heightfield.npz"), 4),
        "renders": render(directory / "preview.vtp", tag),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    service = create_photo_workbench(PROJECT)
    depth_id = locate_depth(service.store, DEPTH_PREFIX)
    profile = service.profiles.load(PROFILE_ID)  # 缺/损 profile 会显式报错（同产品链路）

    arms: list[dict[str, Any]] = []
    for radius in SMOOTHING_RADII:
        label = radius or 0.0
        print(f"=== 显式 {EXPLICIT_DEPTH_MM} mm × 带宽 3.0 × 平滑 {label:.1f} mm")
        arms.append(
            build_arm(
                service,
                depth_id,
                f"explicit-s{label:.1f}",
                ReliefParameters(
                    width_mm=WIDTH_MM,
                    depth_mm=EXPLICIT_DEPTH_MM,
                    base_thickness_mm=BASE_THICKNESS_MM,
                    falloff_band_mm=suggested_falloff_band_mm(EXPLICIT_DEPTH_MM),
                    smoothing_radius_mm=radius,
                ),
            )
        )
    for radius in SMOOTHING_RADII:
        label = radius or 0.0
        print(f"=== 参考比例 {RATIO_RESOLVED_MM:.4f} mm × 带宽 12.6 × 平滑 {label:.1f} mm")
        arms.append(
            build_arm(
                service,
                depth_id,
                f"ratio-s{label:.1f}",
                ReliefParameters(
                    width_mm=WIDTH_MM,
                    height_mode=HeightMode.REFERENCE_RATIO,
                    profile_id=PROFILE_ID,
                    base_thickness_mm=BASE_THICKNESS_MM,
                    falloff_band_mm=suggested_falloff_band_mm(RATIO_RESOLVED_MM),
                    smoothing_radius_mm=radius,
                ),
            )
        )

    report = {
        "schema_version": 1,
        "depth_id": depth_id,
        "project": str(PROJECT),
        "baseline": {
            "width_mm": WIDTH_MM,
            "base_thickness_mm": BASE_THICKNESS_MM,
            "explicit_depth_mm": EXPLICIT_DEPTH_MM,
            "ratio_resolved_mm": profile.effective_relief_mm
            / profile.reference_width_mm
            * WIDTH_MM,
            "bands_mm": {
                "explicit": suggested_falloff_band_mm(EXPLICIT_DEPTH_MM),
                "ratio": suggested_falloff_band_mm(RATIO_RESOLVED_MM),
            },
            "smoothing_radii_mm": [r or 0.0 for r in SMOOTHING_RADII],
        },
        "arms": arms,
    }
    report_path = OUT / "report_data.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "arms": len(arms)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
