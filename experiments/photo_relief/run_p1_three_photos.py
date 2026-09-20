#!/usr/bin/env python3
"""PH09：三张真实照片走完整 P1 管线（导入→人工蒙版→真实深度→离屏渲染）。

运行（真机、需已安装模型）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p1_three_photos.py [--only 短毛犬]

要点：
- 每张照片使用全新工程目录（时间戳后缀，绝不覆盖既有数据）；
- 蒙版 = workspace/annotations/photo_*.json 全部区域多边形并集填充
  （该标注为 M0.5 期间 AI 辅助定位 + 人工核对的产物，manifest notes 如实记录）；
- 深度走 .venv-photo 隔离进程的真实 DA2-Small（MPS 优先，回退 CPU）；
- 渲染为离屏 pyvista（正/侧/斜 × 三点光组/头部单光源）+ 深度色图；
- 输出 experiments/photo_relief/out/<key>/（gitignored），含 report_data.json。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
from PIL import Image, ImageDraw

from pet_leather_studio.algorithms.relief_height import (
    cap_to_mm,
    image_to_geometry_rows,
    unit_height,
)
from pet_leather_studio.bootstrap.workbench import create_photo_workbench
from pet_leather_studio.domain.photo_relief import DepthSemantics, MaskMethod

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments" / "photo_relief" / "out"
PHOTOS: list[tuple[str, str]] = [
    ("短毛犬", "short_hair_dog"),
    ("猫", "cat"),
    ("长毛犬", "long_hair_dog"),
]
PREVIEW_WIDTH_MM = 80.0
PREVIEW_DEPTH_MM = 2.0

_COLORMAP_ANCHORS = np.array(
    [
        [30, 20, 70],
        [55, 80, 170],
        [35, 160, 190],
        [140, 210, 110],
        [250, 220, 90],
        [240, 110, 50],
    ],
    dtype=np.float64,
)


def mask_from_annotations(annotation: dict[str, Any]) -> np.ndarray:
    width, height = annotation["image_size_px"]
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for region in annotation["regions"]:
        draw.polygon([tuple(point) for point in region["polygon"]], fill=255)
    return np.asarray(mask, dtype=np.uint8)


def depth_colormap_png(depth: np.ndarray, valid: np.ndarray, path: Path) -> None:
    unit = (depth - depth[valid].min()) / (depth[valid].max() - depth[valid].min())
    unit = np.where(valid, unit, 0.0)
    positions = np.linspace(0.0, 1.0, len(_COLORMAP_ANCHORS))
    colored = np.stack(
        [np.interp(unit, positions, _COLORMAP_ANCHORS[:, c]) for c in range(3)], axis=-1
    ).astype(np.uint8)
    Image.fromarray(colored, mode="RGB").resize((depth.shape[1] * 4, depth.shape[0] * 4)).save(path)


def render_views(heights_mm: np.ndarray, out_dir: Path, key: str) -> list[str]:
    ny, nx = heights_mm.shape
    height_mm = PREVIEW_WIDTH_MM * ny / nx
    xx, yy = np.meshgrid(
        np.linspace(0.0, PREVIEW_WIDTH_MM, nx), np.linspace(0.0, height_mm, ny)
    )
    grid = pv.StructuredGrid(xx, yy, heights_mm)
    shots: list[str] = []
    for view_name, method in (("front", "view_xy"), ("side", "view_xz"), ("iso", "view_isometric")):
        for light_name in ("lightkit", "headlight"):
            plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
            plotter.set_background("#2b3038")
            plotter.add_mesh(grid, color="ivory", smooth_shading=True)
            if light_name == "headlight":
                plotter.remove_all_lights()
                light = pv.Light(position=(0, 0, 3), color="white")
                light.set_headlight()
                plotter.add_light(light)
            else:
                plotter.enable_lightkit()
            getattr(plotter, method)()
            path = out_dir / f"{key}-{view_name}-{light_name}.png"
            plotter.show(screenshot=str(path))
            shots.append(str(path))
    return shots


def run_one(key_cn: str, key: str, run_root: Path) -> dict[str, Any]:
    project = run_root / key
    service = create_photo_workbench(project)
    source = ROOT / "images" / f"{key_cn}.jpeg"
    annotation = json.loads(
        (ROOT / "workspace" / "annotations" / f"photo_{key}.json").read_text(encoding="utf-8")
    )
    out_dir = OUT / f"{run_root.name}-{key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    photo = service.import_photo(source)
    photo_manifest = service.store.get(photo.revision_id)

    mask_arr = mask_from_annotations(annotation)
    mask_png = out_dir / "mask.png"
    Image.fromarray(mask_arr, mode="L").save(mask_png)
    Image.fromarray(mask_arr, mode="L").resize(
        (mask_arr.shape[1] * 4, mask_arr.shape[0] * 4)
    ).save(out_dir / "mask-preview.png")
    mask = service.save_mask(
        photo.revision_id,
        mask_png,
        MaskMethod.MANUAL,
        notes=(
            "操作员蒙版（M0.5 标注多边形并集填充：AI 辅助定位 + 人工核对；"
            "P1 交付口径为人工蒙版）"
        ),
    )

    depth = service.estimate_depth(photo.revision_id, mask.revision_id)
    depth_manifest = service.store.get(depth.revision_id)
    elapsed_total = round(time.time() - started, 1)

    with np.load(service.store.directory(depth.revision_id) / "depth.npz") as data:
        depth_arr, valid = data["depth"], data["valid"]
    unit = unit_height(depth_arr, valid, DepthSemantics(depth_manifest["depth_semantics"]))
    heights = image_to_geometry_rows(cap_to_mm(unit, PREVIEW_DEPTH_MM))
    shots = render_views(heights, out_dir, key)
    depth_colormap_png(depth_arr, valid, out_dir / f"{key}-depth-colormap.png")
    np.savez_compressed(out_dir / f"{key}-heightfield.npz", heights_mm=heights, valid=valid[::-1])

    return {
        "key": key,
        "project": str(project),
        "revision_ids": {
            "photo": photo.revision_id,
            "mask": mask.revision_id,
            "depth": depth.revision_id,
        },
        "source": str(source),
        "image_size": [photo_manifest["width_px"], photo_manifest["height_px"]],
        "import_warnings": photo_manifest["warnings"],
        "mask_coverage": service.store.get(mask.revision_id)["coverage"],
        "mask_notes": service.store.get(mask.revision_id)["notes"],
        "depth_runtime": depth_manifest["runtime"],
        "depth_semantics": depth_manifest["depth_semantics"],
        "valid_coverage": depth_manifest["valid_coverage"],
        "depth_warnings": depth_manifest["warnings"],
        "preview_depth_mm": PREVIEW_DEPTH_MM,
        "elapsed_total_s": elapsed_total,
        "renders": shots,
        "colormap": str(out_dir / f"{key}-depth-colormap.png"),
        "heightfield_npz": str(out_dir / f"{key}-heightfield.npz"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default=None, help="只跑一张（短毛犬/猫/长毛犬）")
    args = parser.parse_args()
    photos = [item for item in PHOTOS if args.only in (None, item[0])]
    if not photos:
        parser.error(f"--only 需为 {'/'.join(cn for cn, _ in PHOTOS)} 之一")

    run_root = ROOT / "workspace" / "photo-relief-p1" / datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for key_cn, key in photos:
        print(f"=== {key_cn}（{key}）→ {run_root / key}")
        rows.append(run_one(key_cn, key, run_root))

    report = {
        "schema_version": 1,
        "run_root": str(run_root),
        "order": [key for _, key in photos],
        "model": "depth-anything-v2-small-hf（Apache-2.0）",
        "preview_depth_mm": PREVIEW_DEPTH_MM,
        "results": rows,
    }
    report_path = OUT / f"{run_root.name}-report_data.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"report": str(report_path), "photos": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
