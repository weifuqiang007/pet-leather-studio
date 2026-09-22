#!/usr/bin/env python3
"""P2 复验 R2 附加实验：过渡带宽度对照（2 mm 显式与 8.35 mm 参考比例两类样例）。

运行（真机）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_falloff_bands.py

独立验收 R2 要求：为 2 mm 与 8.35 mm 两类样例导出至少三种带宽的侧视/斜视
对照，由用户选定样式（审美选择不由数值测试替代）。本脚本据此生成：
- 显式组（depth 2.0 mm）：带宽 2.5（R1 默认）/ 3.0（R2 建议=1.5h）/ 4.0（2h）
  / 6.0（3h），另加一条"建议带宽 + 平滑 1.5 mm"对照——R1 保持域内逐位
  不变，输入深度固有断层须靠平滑缓解（坡度统计可见差别）；
- 参考比例组（ref-5c1ae382ab802ef6 ⇒ 8.352108 mm）：带宽 2.5（R1 默认，
  验收指出的近垂直墙）/ 12.6（R2 建议）/ 16.8（2h）/ 25.1（3h）。
每条记录 falloff/slope（manifest）、版边余量与版边最大抬升（带宽越过余量
会抬起版面边缘，对照渲染可见）。产品与 GUI 无档位控件；深度由显式 mm 或
参考比例唯一确定，带宽是 ReliefParameters.falloff_band_mm 的实验扫描。
输出 experiments/photo_relief/out/p2-falloff-bands/（gitignored），含
report_data.json；重跑在同一工程库追加新母版修订（修订史 append-only）。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv

from pet_leather_studio.algorithms.relief_height import background_clearance_mm
from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import (
    HeightMode,
    ReliefParameters,
    suggested_falloff_band_mm,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out" / "p2-falloff-bands"
PROJECT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433" / "short_hair_dog"
DEPTH_PREFIX = "8a18d7ed"
PROFILE_ID = "ref-5c1ae382ab802ef6"  # PH05 真实标定（run_p2_masters 同一来源）
WIDTH_MM = 60.0
BASE_THICKNESS_MM = 3.0
EXPLICIT_DEPTH_MM = 2.0
EXPLICIT_BANDS = (2.5, 3.0, 4.0, 6.0)  # R1 默认 / R2 建议 / 2h / 3h
SMOOTHING_MM = 1.5  # 断层缓解对照臂（作用于主体内部，非过渡带参数）


def locate_depth(store: Any, prefix: str) -> str:
    depths = [row["id"] for row in store.history() if row.get("kind") == "depth"]
    matched = [revision_id for revision_id in depths if revision_id.startswith(prefix)]
    if len(matched) == 1:
        return matched[0]
    raise SystemExit(f"无法唯一定位短毛犬 depth 修订（前缀 {prefix}，候选 {depths}）")


def load_valid(depth_npz: Path) -> np.ndarray:
    with np.load(depth_npz) as data:
        return np.asarray(data["valid"], dtype=bool)


def border_max_mm(heightfield_npz: Path) -> float:
    """版面边框（四缘）最大高度：>0 即过渡带抬起了版边。"""
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
    service: Any,
    depth_id: str,
    tag: str,
    parameters: ReliefParameters,
    clearance: float,
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
        "clearance_mm": None if math.isinf(clearance) else round(clearance, 3),
        "border_max_mm": round(border_max_mm(directory / "heightfield.npz"), 4),
        "files": {name: str(directory / name) for name in ("master.stl", "heightfield.npz")},
        "renders": render(directory / "preview.vtp", tag),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    service = create_photo_workbench(PROJECT)
    depth_id = locate_depth(service.store, DEPTH_PREFIX)
    valid = load_valid(service.store.directory(depth_id) / "depth.npz")
    rows, cols = valid.shape
    dx = WIDTH_MM / max(cols - 1, 1)
    dy = dx * rows / max(rows - 1, 1)
    clearance = background_clearance_mm(valid, dx, dy)
    margin = "inf（主体贴版边，平边前提不成立）" if math.isinf(clearance) else f"{clearance:.2f} mm"
    print(f"depth {depth_id[:8]}：valid {rows}×{cols}，版边余量 {margin}")

    arms: list[dict[str, Any]] = []
    for band in EXPLICIT_BANDS:
        print(f"=== 显式 2.0 mm × 带宽 {band} mm")
        arms.append(
            build_arm(
                service,
                depth_id,
                f"explicit-b{band:.1f}",
                ReliefParameters(
                    width_mm=WIDTH_MM,
                    depth_mm=EXPLICIT_DEPTH_MM,
                    base_thickness_mm=BASE_THICKNESS_MM,
                    falloff_band_mm=band,
                ),
                clearance,
            )
        )
    print(f"=== 显式 2.0 mm × 建议带宽 + 平滑 {SMOOTHING_MM} mm（断层缓解对照）")
    arms.append(
        build_arm(
            service,
            depth_id,
            "explicit-b3.0-smooth",
            ReliefParameters(
                width_mm=WIDTH_MM,
                depth_mm=EXPLICIT_DEPTH_MM,
                base_thickness_mm=BASE_THICKNESS_MM,
                falloff_band_mm=suggested_falloff_band_mm(EXPLICIT_DEPTH_MM),
                smoothing_radius_mm=SMOOTHING_MM,
            ),
            clearance,
        )
    )

    profile = service.profiles.load(PROFILE_ID)  # 缺/损 profile 会显式报错（同产品链路）
    resolved = profile.effective_relief_mm / profile.reference_width_mm * WIDTH_MM
    ratio_bands = (
        2.5,
        suggested_falloff_band_mm(resolved),
        round(2 * resolved, 1),
        round(3 * resolved, 1),
    )
    for band in ratio_bands:
        print(f"=== 参考比例 {resolved:.4f} mm × 带宽 {band} mm")
        arms.append(
            build_arm(
                service,
                depth_id,
                f"ratio-b{band:.1f}",
                ReliefParameters(
                    width_mm=WIDTH_MM,
                    height_mode=HeightMode.REFERENCE_RATIO,
                    profile_id=PROFILE_ID,
                    base_thickness_mm=BASE_THICKNESS_MM,
                    falloff_band_mm=band,
                ),
                clearance,
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
            "resolved_ratio_depth_mm": resolved,
            "clearance_mm": None if math.isinf(clearance) else round(clearance, 3),
            "suggested_band_explicit_mm": suggested_falloff_band_mm(EXPLICIT_DEPTH_MM),
            "suggested_band_ratio_mm": suggested_falloff_band_mm(resolved),
            "smoothing_mm": SMOOTHING_MM,
        },
        "arms": arms,
    }
    report_path = OUT / "report_data.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "arms": len(arms)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
