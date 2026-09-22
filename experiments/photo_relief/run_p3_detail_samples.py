#!/usr/bin/env python3
"""P3 细节层验收：三样本无贴图母版（体块 + 受限照片细节层）。

运行：scripts/dev.sh run --frozen python experiments/photo_relief/run_p3_detail_samples.py
输出位于 experiments/photo_relief/out/p3-detail-samples/（gitignored）。每次运行会
追加母版修订，并记录参数、细节层、坡度、警告和三视图，便于比较或回退。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pyvista as pv

from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import DEFAULT_DETAIL_STRENGTH, ReliefParameters

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out" / "p3-detail-samples"
RUN_ROOT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433"
SAMPLES: list[tuple[str, str]] = [
    ("short_hair_dog", "8a18d7ed"),
    ("cat", "f5336763"),
    ("long_hair_dog", "e9009bdb"),
]
PARAMETERS = ReliefParameters(
    width_mm=60.0,
    depth_mm=2.0,
    base_thickness_mm=3.0,
    falloff_band_mm=3.0,
    smoothing_radius_mm=1.5,
    detail_strength=DEFAULT_DETAIL_STRENGTH,
)


def locate_depth(store: Any, prefix: str) -> str:
    matches = [
        row["id"]
        for row in store.history()
        if row.get("kind") == "depth" and row["id"].startswith(prefix)
    ]
    if len(matches) != 1:
        raise SystemExit(f"无法唯一定位 depth 修订 {prefix}，候选：{matches}")
    return matches[0]


def render(preview_vtp: Path, out_dir: Path, key: str) -> list[str]:
    mesh = pv.read(preview_vtp)
    paths: list[str] = []
    for name, camera in (("front", "view_xy"), ("side", "view_xz"), ("iso", "view_isometric")):
        plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
        plotter.set_background("#2b3038")
        plotter.add_mesh(mesh, color="ivory", smooth_shading=True)
        plotter.enable_lightkit()
        getattr(plotter, camera)()
        output = out_dir / f"{key}-{name}-lightkit.png"
        plotter.show(screenshot=str(output))
        paths.append(str(output))
    return paths


def main() -> int:
    rows: list[dict[str, Any]] = []
    for key, prefix in SAMPLES:
        service = create_photo_workbench(RUN_ROOT / key)
        depth_id = locate_depth(service.store, prefix)
        started = time.time()
        summary = service.build_master(depth_id, PARAMETERS)
        manifest = service.store.get(summary.revision_id)
        directory = service.store.directory(summary.revision_id)
        out_dir = OUT / key
        out_dir.mkdir(parents=True, exist_ok=True)
        rows.append(
            {
                "key": key,
                "depth_id": depth_id,
                "master_revision": summary.revision_id,
                "elapsed_s": round(time.time() - started, 2),
                "parameters": manifest["parameters"],
                "detail": manifest["detail"],
                "slope": manifest["slope"],
                "warnings": manifest["warnings"],
                "renders": render(directory / "preview.vtp", out_dir, key),
            }
        )
    report = {"schema_version": 1, "parameters": PARAMETERS.__dict__, "results": rows}
    destination = OUT / "report_data.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination), "masters": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
