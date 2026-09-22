#!/usr/bin/env python3
"""P2 附加实验：同一基准的起伏档位对照 80/100/120%（仅实验，产品无档位控件）。

运行（真机）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_relief_tiers.py

基准 = PH09 第四轮短毛犬 depth 修订（8a18d7ed…），宽 60mm、基准起伏 2.0mm
（explicit_depth）、底板 3.0mm、无平滑；三档 = 1.6 / 2.0 / 2.4mm 各生成一张
母版，记录每档 relief / clamp_report / 重读校验，渲染侧视+斜视对照。
档位只是本脚本的实验参数：产品与 GUI 均无档位控件（合同不引入"档位"概念，
深度由显式 mm 或参考比例唯一确定）。
输出 experiments/photo_relief/out/p2-relief-tiers/（gitignored），含 report_data.json；
重跑会在同一工程库追加新母版修订（修订史 append-only）。
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
OUT = ROOT / "experiments" / "photo_relief" / "out"
RUN_ROOT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433"
TIER_KEY, TIER_PREFIX = "short_hair_dog", "8a18d7ed"
WIDTH_MM = 60.0
BASE_DEPTH_MM = 2.0  # 100% 档
BASE_THICKNESS_MM = 3.0
TIERS = (0.8, 1.0, 1.2)


def locate_depth(store: Any, prefix: str) -> str:
    depths = [row["id"] for row in store.history() if row.get("kind") == "depth"]
    matched = [revision_id for revision_id in depths if revision_id.startswith(prefix)]
    if len(matched) == 1:
        return matched[0]
    if not matched and len(depths) == 1:
        return depths[0]
    raise SystemExit(f"无法唯一定位短毛犬 depth 修订（前缀 {prefix}，候选 {depths}）")


def render_tier(preview_vtp: Path, out_dir: Path, tag: str) -> list[str]:
    mesh = pv.read(preview_vtp)
    shots: list[str] = []
    for view_name, method in (("side", "view_xz"), ("iso", "view_isometric")):
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
    service = create_photo_workbench(RUN_ROOT / TIER_KEY)
    depth_id = locate_depth(service.store, TIER_PREFIX)
    out_dir = OUT / "p2-relief-tiers"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for tier in TIERS:
        depth_mm = round(BASE_DEPTH_MM * tier, 4)
        tag = f"tier-{int(tier * 100):03d}"
        parameters = ReliefParameters(
            width_mm=WIDTH_MM,
            depth_mm=depth_mm,
            base_thickness_mm=BASE_THICKNESS_MM,
        )
        print(f"=== {tier:.0%} 档（depth {depth_mm}mm）→ 母版")
        started = time.time()
        summary = service.build_master(depth_id, parameters)
        manifest = service.store.get(summary.revision_id)
        directory = service.store.directory(summary.revision_id)
        results.append(
            {
                "tier": tier,
                "depth_mm": depth_mm,
                "master_revision": summary.revision_id,
                "elapsed_s": round(time.time() - started, 1),
                "relief": manifest["relief"],
                "clamp_report": manifest["clamp_report"],
                "geometry_checks": manifest["geometry_checks"],
                "files": {
                    name: str(directory / name)
                    for name in ("master.obj", "master.stl", "heightfield.npz")
                },
                "renders": render_tier(directory / "preview.vtp", out_dir, tag),
            }
        )

    report = {
        "schema_version": 1,
        "depth_id": depth_id,
        "project": str(RUN_ROOT / TIER_KEY),
        "baseline": {
            "width_mm": WIDTH_MM,
            "base_depth_mm": BASE_DEPTH_MM,
            "base_thickness_mm": BASE_THICKNESS_MM,
        },
        "tiers": results,
    }
    report_path = out_dir / "report_data.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "tiers": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
