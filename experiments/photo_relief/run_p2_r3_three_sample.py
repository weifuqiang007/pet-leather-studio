#!/usr/bin/env python3
"""P2 复验 R3 附加实验②：三张真实样本同条件无贴图对照（R3 候选配置）。

运行（真机）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_r3_three_sample.py

独立验收 R3 必修第 4 点：以短毛犬/猫/长毛犬三张真实样本做同条件对照，供用户
对无贴图正面/侧面/斜视图逐一确认（通过条件：无硬墙/条状断层、关键轮廓清晰，
且用户在 GUI 亲自确认后才能进入阴阳模）。R3 候选配置：显式 2.0 mm 起伏 +
建议带宽 3.0 mm + 平滑 1.5 mm（矩阵实验①给出坡度/细节权衡依据）。逐样本记录
三类坡度、细节保留率与 manifest 警告。输出
experiments/photo_relief/out/p2-r3-three-sample/<key>/（gitignored），含
report_data.json；重跑在各工程库追加新母版修订（修订史 append-only）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pyvista as pv

from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import ReliefParameters

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out" / "p2-r3-three-sample"
RUN_ROOT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433"
# PH09 第四轮各工程库的 depth 修订 id 前缀（历史行按前缀唯一定位，防错库）
PHOTOS: list[tuple[str, str, str]] = [
    ("短毛犬", "short_hair_dog", "8a18d7ed"),
    ("猫", "cat", "f5336763"),
    ("长毛犬", "long_hair_dog", "e9009bdb"),
]
# R3 候选配置：建议带宽（2.0 mm ⇒ 3.0）+ 平滑 1.5 mm（断层一阶缓解）
MASTER_PARAMETERS = ReliefParameters(
    width_mm=60.0,
    depth_mm=2.0,
    base_thickness_mm=3.0,
    falloff_band_mm=3.0,
    smoothing_radius_mm=1.5,
)


def locate_depth(store: Any, prefix: str, key: str) -> str:
    depths = [row["id"] for row in store.history() if row.get("kind") == "depth"]
    matched = [revision_id for revision_id in depths if revision_id.startswith(prefix)]
    if len(matched) == 1:
        return matched[0]
    if not matched and len(depths) == 1:
        return depths[0]
    raise SystemExit(f"{key}: 无法唯一定位 depth 修订（前缀 {prefix}，候选 {depths}）")


def render_master(preview_vtp: Path, out_dir: Path, tag: str) -> list[str]:
    mesh = pv.read(preview_vtp)
    shots: list[str] = []
    for view_name, method in (("front", "view_xy"), ("side", "view_xz"), ("iso", "view_isometric")):
        plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
        plotter.set_background("#2b3038")
        plotter.add_mesh(mesh, color="ivory", smooth_shading=True)
        plotter.enable_lightkit()
        getattr(plotter, method)()
        path = out_dir / f"{tag}-{view_name}-lightkit.png"
        plotter.show(screenshot=str(path))
        shots.append(str(path))
    return shots


def main() -> int:
    results = []
    for key_cn, key, prefix in PHOTOS:
        service = create_photo_workbench(RUN_ROOT / key)
        depth_id = locate_depth(service.store, prefix, key)
        print(f"=== {key_cn}（{key}）depth {depth_id[:8]} → R3 候选配置母版")
        started = time.time()
        summary = service.build_master(depth_id, MASTER_PARAMETERS)
        manifest = service.store.get(summary.revision_id)
        directory = service.store.directory(summary.revision_id)
        out_dir = OUT / key
        out_dir.mkdir(parents=True, exist_ok=True)
        results.append(
            {
                "key": key,
                "project": str(RUN_ROOT / key),
                "depth_id": depth_id,
                "master_revision": summary.revision_id,
                "parameters": manifest["parameters"],
                "elapsed_s": round(time.time() - started, 1),
                "relief": manifest["relief"],
                "falloff": manifest["falloff"],
                "slope": manifest["slope"],
                "smoothing": manifest["smoothing"],
                "warnings": manifest["warnings"],
                "renders": render_master(directory / "preview.vtp", out_dir, key),
            }
        )

    report = {
        "schema_version": 1,
        "configuration": {
            "parameters": {
                "width_mm": MASTER_PARAMETERS.width_mm,
                "depth_mm": MASTER_PARAMETERS.depth_mm,
                "base_thickness_mm": MASTER_PARAMETERS.base_thickness_mm,
                "falloff_band_mm": MASTER_PARAMETERS.falloff_band_mm,
                "smoothing_radius_mm": MASTER_PARAMETERS.smoothing_radius_mm,
            },
            "note": "R3 候选：建议带宽 + 平滑 1.5；视觉通过与否由用户逐样本确认",
        },
        "results": results,
    }
    report_path = OUT / "report_data.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "masters": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
