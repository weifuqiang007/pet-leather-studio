#!/usr/bin/env python3
"""P2：三张真实照片的既有 depth 修订 → 受控浮雕化母版（不重跑推理）。

运行（真机）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_masters.py
    （可选 --only 短毛犬 / 猫 / 长毛犬）

要点：
- 复用 PH09 第四轮 workspace/photo-relief-p1/20260921-110433/ 既有 depth 修订，
  每张生成一张 explicit_depth 母版（60mm 宽 / 2.0mm 起伏 / 3.0mm 底板，无平滑）；
- 真实参考标定（PH05）：images/test1_result/1_SubTool3.obj——14.93% 包围盒比例的
  来源实物，percentile 99 / min_z_plane / 全 XY 区域（v1 口径），存 app 级 profiles/
  （与 GUI 同一存储，profile_id 确定性、重跑覆盖同一文件）；
- 短毛犬另以 reference_ratio 模式生成一张母版，演示标定→母版全链；
- 母版生成走 PhotoWorkbench.build_master（与 CLI/GUI 同一用例）；发布前 OBJ/STL
  重读校验由几何器内建，失败即 discard 不产生修订；
- 渲染离屏 pyvista 正/侧/斜 × 三点光组/头部单光源（读已发布 preview.vtp，与 GUI
  同 LOD）；
- 输出 experiments/photo_relief/out/p2-masters/<key>/（gitignored），含
  report_data.json；重跑会在同一工程库追加新母版修订（修订史 append-only）。
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyvista as pv

from pet_leather_studio.bootstrap.environment import data_root
from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import (
    DEFAULT_PERCENTILE,
    HeightMode,
    ReliefParameters,
)
from pet_leather_studio.infrastructure.reference_profile import (
    ReferenceProfileStore,
    measure_reference,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out"
RUN_ROOT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433"
REFERENCE_OBJ = ROOT / "images" / "test1_result" / "1_SubTool3.obj"
# PH09 第四轮各工程库的 depth 修订 id 前缀（历史行按前缀唯一定位，防错库）
PHOTOS: list[tuple[str, str, str]] = [
    ("短毛犬", "short_hair_dog", "8a18d7ed"),
    ("猫", "cat", "f5336763"),
    ("长毛犬", "long_hair_dog", "e9009bdb"),
]
MASTER_PARAMETERS = ReliefParameters(width_mm=60.0, depth_mm=2.0, base_thickness_mm=3.0)
RATIO_KEY = "short_hair_dog"  # 参考比例全链演示挂在短毛犬上（与 GUI 手测同工程）
MASTER_FILES = ("master.obj", "master.stl", "master.vtp", "preview.vtp", "heightfield.npz")


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
        for light_name in ("lightkit", "headlight"):
            plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
            plotter.set_background("#2b3038")
            plotter.add_mesh(mesh, color="ivory", smooth_shading=True)
            if light_name == "headlight":
                plotter.remove_all_lights()
                light = pv.Light(position=(0, 0, 3), color="white")
                light.set_headlight()
                plotter.add_light(light)
            else:
                plotter.enable_lightkit()
            getattr(plotter, method)()
            path = out_dir / f"{tag}-{view_name}-{light_name}.png"
            plotter.show(screenshot=str(path))
            shots.append(str(path))
    return shots


def master_record(
    service: Any, depth_id: str, parameters: ReliefParameters, tag: str
) -> dict[str, Any]:
    started = time.time()
    summary = service.build_master(depth_id, parameters)
    manifest = service.store.get(summary.revision_id)
    directory = service.store.directory(summary.revision_id)
    out_dir = OUT / "p2-masters" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "depth_id": depth_id,
        "master_revision": summary.revision_id,
        "parameters": manifest["parameters"],
        "elapsed_s": round(time.time() - started, 1),
        "files": {name: str(directory / name) for name in MASTER_FILES},
        "relief": manifest["relief"],
        "height_resolution": manifest["height_resolution"],
        "geometry_checks": manifest["geometry_checks"],
        "clamp_report": manifest["clamp_report"],
        "warnings": manifest["warnings"],
        "renders": render_master(directory / "preview.vtp", out_dir, tag),
    }


def calibrate() -> dict[str, Any]:
    """真实参考标定：SubTool3 实物 → app 级 profiles/（GUI 下拉同库）。"""
    started = time.time()
    profile = measure_reference(REFERENCE_OBJ, percentile=DEFAULT_PERCENTILE)
    saved = ReferenceProfileStore(data_root() / "profiles").save(profile)
    return {
        "saved": str(saved),
        "elapsed_s": round(time.time() - started, 1),
        "profile": profile.to_json_dict(),
        # 14.93% 包围盒比例仅历史对照（runtime/reference_inspection/stats.json 的
        # 2.878/19.283）；标定不自动套用该数字，见 profile.bbox_z_span_ratio 分开记录。
        "note": "bbox_z_span_ratio 仅历史对照，永不自动套用；有效起伏=分位裁剪口径",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default=None, help="只跑一张（短毛犬/猫/长毛犬）")
    args = parser.parse_args()
    photos = [item for item in PHOTOS if args.only in (None, item[0])]
    if not photos:
        parser.error(f"--only 需为 {'/'.join(cn for cn, _, _ in PHOTOS)} 之一")

    calibration = calibrate()
    results = []
    ratio_result = None
    for key_cn, key, prefix in photos:
        service = create_photo_workbench(RUN_ROOT / key)
        depth_id = locate_depth(service.store, prefix, key)
        print(f"=== {key_cn}（{key}）depth {depth_id[:8]} → explicit 母版")
        results.append(
            {
                "key": key,
                "project": str(RUN_ROOT / key),
                **master_record(service, depth_id, MASTER_PARAMETERS, key),
            }
        )
        if key == RATIO_KEY:
            ratio_parameters = ReliefParameters(
                width_mm=MASTER_PARAMETERS.width_mm,
                height_mode=HeightMode.REFERENCE_RATIO,
                profile_id=calibration["profile"]["profile_id"],
                base_thickness_mm=MASTER_PARAMETERS.base_thickness_mm,
            )
            print(f"=== {key_cn}（{key}）depth {depth_id[:8]} → reference_ratio 母版")
            ratio_result = {
                "key": key,
                "project": str(RUN_ROOT / key),
                **master_record(service, depth_id, ratio_parameters, f"{key}-ratio"),
            }

    report = {
        "schema_version": 1,
        "reference_calibration": calibration,
        "explicit_parameters": asdict(MASTER_PARAMETERS),
        "results": results,
        "ratio_result": ratio_result,
    }
    report_path = OUT / "p2-masters" / "report_data.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "masters": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
