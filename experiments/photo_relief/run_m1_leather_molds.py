#!/usr/bin/env python3
"""MOLD-PAIR M1：三张 R3 真实母版 → 皮革阴阳模修订（默认参数全链）。

运行（真机）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_m1_leather_molds.py
    （可选 --only 短毛犬 / 猫 / 长毛犬）

要点：
- 复用 R3 同条件母版（workspace/photo-relief-p1/20260921-110433/ 三工程库，
  2026-09-22 09:01 生成的 2.0mm/平滑1.5/过渡3.0 版本）：9c37b28a / bef3f6cc /
  bdb68708——三者版边余量都不足（犬/猫贴边、长毛犬余量 1.47 < 过渡带 3.0），
  全部走 M1 模具侧平铺扩边路径；
- 生成走 LeatherMoldWorkbench.generate（与 CLI/GUI 同一用例，同一工程库追加
  kind=mold_pair 修订，修订史 append-only）；发布内建独立双向测距 + guard
  逐级加密 + OBJ/STL 重读校验，失败即 discard；
- 记录：扩边（过渡宽/像素/最终版面/纯平止口）、guard 档位、t_eff 与容差、
  独立实测最小距离、Z 向间隙、阳模最陡坡度、体积与重读误差、警告清单；
- 渲染离屏装配预览（阳模象牙 + 阴模半透明钢蓝，读已发布 male.vtp/female.vtp）；
- 输出 experiments/photo_relief/out/m1-leather-molds/<key>/（gitignored），
  含 report_data.json；重跑会追加新的 mold_pair 修订（不改旧版）。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pyvista as pv

from pet_leather_studio.bootstrap.workbench import (
    create_leather_mold_workbench,
    create_photo_workbench,
)
from pet_leather_studio.domain.leather_molds import LeatherMoldParameters
from pet_leather_studio.infrastructure.revisions import RevisionStore

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out"
RUN_ROOT = ROOT / "workspace" / "photo-relief-p1" / "20260921-110433"
# R3 同条件母版修订 id 前缀（2026-09-22 09:01 批次；前缀在各自工程库内唯一）
MASTERS: list[tuple[str, str, str]] = [
    ("短毛犬", "short_hair_dog", "9c37b28a"),
    ("猫", "cat", "bef3f6cc"),
    ("长毛犬", "long_hair_dog", "bdb68708"),
]
PAIR_FILES = (
    "male.obj",
    "male.stl",
    "male.vtp",
    "female.obj",
    "female.stl",
    "female.vtp",
    "mold_pair.npz",
    "assembly_preview.vtp",
    "README.txt",
)


def locate_master(store: RevisionStore, prefix: str, key: str) -> str:
    candidates = [
        row["id"]
        for row in store.history()
        if row.get("kind") == "master" and row["id"].startswith(prefix)
    ]
    if len(candidates) != 1:
        raise SystemExit(f"{key}: 无法唯一定位母版修订（前缀 {prefix}，候选 {candidates}）")
    return candidates[0]


def render_pair(directory: Path, out_dir: Path, tag: str) -> list[str]:
    male = pv.read(directory / "male.vtp")
    female = pv.read(directory / "female.vtp")
    shots: list[str] = []
    for view_name, method in (("front", "view_xy"), ("side", "view_xz"), ("iso", "view_isometric")):
        plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
        plotter.set_background("#2b3038")
        plotter.add_mesh(male, color="ivory", smooth_shading=True)
        plotter.add_mesh(female, color="steelblue", opacity=0.35, smooth_shading=True)
        plotter.enable_lightkit()
        getattr(plotter, method)()
        path = out_dir / f"{tag}-assembly-{view_name}.png"
        plotter.show(screenshot=str(path))
        shots.append(str(path))
    return shots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default=None, help="只跑一张（短毛犬/猫/长毛犬）")
    args = parser.parse_args()
    masters = [item for item in MASTERS if args.only in (None, item[0])]
    if not masters:
        parser.error(f"--only 需为 {'/'.join(cn for cn, _, _ in MASTERS)} 之一")

    parameters = LeatherMoldParameters()  # 默认：2.0 皮厚 / 0.15 压实 / 止口 4mm
    results = []
    for cn, key, prefix in masters:
        project = RUN_ROOT / key
        photo_store = create_photo_workbench(project).store
        master_id = locate_master(photo_store, prefix, key)
        workbench = create_leather_mold_workbench(project)
        print(f"=== {cn}（{key}）母版 {master_id[:8]} → 皮革阴阳模")
        started = time.time()
        summary = workbench.generate(master_id, parameters)
        manifest = photo_store.get(summary.revision_id)
        directory = photo_store.directory(summary.revision_id)
        elapsed = round(time.time() - started, 1)
        record: dict[str, Any] = {
            "master_revision": master_id,
            "mold_pair_revision": summary.revision_id,
            "elapsed_s": elapsed,
            "border_clearance_mm": manifest["border_clearance_mm"],
            "existing_flat_stop_mm": manifest["existing_flat_stop_mm"],
            "expansion": manifest["expansion"],
            "plate": manifest["plate"],
            "target_effective_thickness_mm": manifest["target_effective_thickness_mm"],
            "distance_tolerance_mm": manifest["distance_tolerance_mm"],
            "envelope_kernel": manifest["envelope_kernel"],
            "clearance_independent": manifest["clearance_independent"],
            "axial_gap_min_mm": manifest["axial_gap_min_mm"],
            "slope": manifest["slope"],
            "geometry_checks": manifest["geometry_checks"],
            "core_bitwise_preserved": manifest["core_bitwise_preserved"],
            "warnings": manifest["warnings"],
            "files": {name: str(directory / name) for name in PAIR_FILES},
        }
        out_dir = OUT / "m1-leather-molds" / key
        out_dir.mkdir(parents=True, exist_ok=True)
        record["renders"] = render_pair(directory, out_dir, key)
        results.append(record)
        check = manifest["clearance_independent"]
        expansion = manifest["expansion"]
        print(
            f"    pair {summary.revision_id[:8]}（{elapsed}s）："
            + (
                f"扩边 {manifest['plate']['source_width_mm']:.1f}→"
                f"{manifest['plate']['final_width_mm']:.1f} mm，"
                f"过渡 {expansion.get('transition_mm')} mm + 纯平止口 "
                f"{expansion.get('flat_stop_min_mm', 0.0):.1f} mm；"
                if expansion.get("expanded")
                else "未扩边（余量足）；"
            )
            + f"guard {check['guard_mm']:.3f}；独立最小 {check['min_mm']:.3f} mm"
            f"（t_eff {manifest['target_effective_thickness_mm']:.3f} − 容差 "
            f"{manifest['distance_tolerance_mm']:.3f}）；"
            f"核心逐位不变 {manifest['core_bitwise_preserved']}；警告 {len(record['warnings'])} 条"
        )

    report = OUT / "m1-leather-molds" / "report_data.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {"parameters": parameters.to_dict(), "samples": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"report → {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
