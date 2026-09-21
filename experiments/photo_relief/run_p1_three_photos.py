#!/usr/bin/env python3
"""PH09：三张真实照片走完整 P1 管线（导入→人工蒙版→真实深度→离屏渲染）。

运行（真机、需已安装模型）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p1_three_photos.py
    （可选 --only 短毛犬 / 猫 / 长毛犬）

要点：
- 每张照片使用全新工程目录（时间戳后缀，绝不覆盖既有数据）；
- 蒙版 = FULL_SUBJECT_POLYGONS 完整可见主体多边形（P1 复验 R3 第三轮：三张
  均按四角背景色阈值客观测定轮廓——两轮目测坐标均有偏差；叠加图人工复核）。
  M0.5 旧标注文件原样保留、不再引用；
- 每张输出 mask-overlay.png（半透明红 + 黄色边界线叠加原图，4× 放大）供人工核对蒙版边界；
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
from PIL import Image, ImageDraw, ImageFilter

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


# P1 复验（R3，第三轮）：覆盖完整可见主体的蒙版多边形（原图像素坐标，左上原点）。
# 三张均为客观测定（目测坐标两轮均有偏差；猫的目测轮廓第三轮复核确认切掉了
# 耳尖/额头/右侧毛发）：四角背景色 → 距离阈值前景 → 最大连通域（弃水印碎块）→
# 补洞（耳间/胸前浅色毛）→ 闭运算 2px 平滑凹口后与原前景取并（不削细毛尖）→
# 轮廓追迹简化，多边形回填与主体掩码 IoU ≥ 0.985；叠加图再作人工复核。
# M0.5 旧标注文件保留、不再引用。
FULL_SUBJECT_POLYGONS: dict[str, list[tuple[int, int]]] = {
    # 头部 + 可见上身（正面偏侧，胸口在画面底边被裁切，底边取到 y=147）。
    # 客观轮廓：右耳外沿凸到 (131,55)，耳下缘收回到 x≈111-118（去掉上轮
    # 误纳的 x116-132 背景条），左上背景穹顶（x26-60 y24-99）不再纳入。
    "short_hair_dog": [
        (94, 19),
        (108, 22),
        (117, 29),
        (131, 55),
        (130, 61),
        (123, 71),
        (123, 76),
        (118, 74),
        (118, 65),
        (115, 62),
        (110, 68),
        (114, 87),
        (117, 91),
        (116, 99),
        (120, 108),
        (114, 147),
        (111, 145),
        (109, 147),
        (31, 147),
        (42, 127),
        (46, 113),
        (60, 92),
        (61, 79),
        (65, 73),
        (59, 67),
        (56, 58),
        (66, 34),
        (78, 23),
        (93, 20),
    ],
    # 双耳 + 面部 + 身体（正面，胸口在底边被裁切，底边取到 y=147；底部满宽
    # 条带为胸口毛，gettyimages 半透明水印叠在毛上而非背景，按主体保留）。
    # 客观轮廓：耳尖到 y=0、耳间凹口 y≈13-15、右侧毛发到 x≈126-147、
    # 右下角小块为身体延伸（旧目测轮廓切掉耳尖/额头/右侧毛发约 11% 主体）。
    "cat": [
        (36, 0),
        (49, 0),
        (64, 13),
        (97, 15),
        (107, 15),
        (130, 0),
        (134, 2),
        (122, 38),
        (124, 56),
        (120, 69),
        (126, 87),
        (126, 111),
        (129, 114),
        (147, 114),
        (147, 135),
        (139, 135),
        (136, 138),
        (137, 147),
        (0, 147),
        (4, 136),
        (36, 95),
        (38, 81),
        (43, 73),
        (39, 55),
        (39, 43),
        (43, 32),
        (36, 1),
    ],
    # 全身（趴卧姿态：头在左上，背线向右下斜至臀部，左前爪伸向左下）。
    # 客观轮廓：头顶/耳尖 y≈10、背线 (111,15)→(143,52)→(189,90)→(199,122)
    # （上轮误把背线右侧当背景挖了缺口）、右腹到 x≈199、左前爪到 (13,138)、
    # 腿间空隙 (121,105)-(136,115) 保留为凹口；毛边缘锯齿为真实毛发纹理。
    "long_hair_dog": [
        (78, 10),
        (84, 10),
        (92, 16),
        (98, 13),
        (111, 15),
        (124, 22),
        (132, 31),
        (135, 39),
        (143, 52),
        (146, 55),
        (151, 55),
        (149, 55),
        (146, 58),
        (150, 62),
        (157, 63),
        (167, 67),
        (189, 90),
        (187, 93),
        (193, 100),
        (195, 112),
        (199, 122),
        (191, 128),
        (183, 130),
        (155, 131),
        (152, 129),
        (146, 133),
        (140, 134),
        (140, 128),
        (142, 124),
        (137, 120),
        (136, 115),
        (132, 111),
        (126, 111),
        (125, 108),
        (121, 105),
        (117, 109),
        (119, 115),
        (117, 118),
        (119, 120),
        (120, 129),
        (127, 135),
        (129, 135),
        (132, 132),
        (131, 131),
        (135, 131),
        (137, 135),
        (128, 135),
        (119, 139),
        (102, 141),
        (85, 141),
        (76, 139),
        (64, 140),
        (75, 139),
        (78, 136),
        (75, 133),
        (71, 132),
        (65, 132),
        (59, 138),
        (61, 140),
        (19, 141),
        (13, 138),
        (13, 133),
        (16, 126),
        (20, 122),
        (25, 120),
        (32, 112),
        (37, 111),
        (45, 102),
        (45, 94),
        (51, 81),
        (48, 77),
        (46, 77),
        (48, 71),
        (45, 65),
        (46, 60),
        (44, 58),
        (44, 51),
        (48, 38),
        (53, 32),
        (58, 22),
        (69, 14),
        (77, 11),
    ],
}


def full_subject_mask(key: str, photo_manifest: dict[str, Any]) -> np.ndarray:
    """多边形坐标定义于原图像素系；按工作图尺寸等比缩放后填充为蒙版。"""
    width, height = int(photo_manifest["work_width_px"]), int(photo_manifest["work_height_px"])
    scale_x = width / int(photo_manifest["width_px"])
    scale_y = height / int(photo_manifest["height_px"])
    polygon = [(round(x * scale_x), round(y * scale_y)) for x, y in FULL_SUBJECT_POLYGONS[key]]
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    return np.asarray(mask, dtype=np.uint8)


def save_mask_overlay(work_png: Path, mask_arr: np.ndarray, out_png: Path) -> None:
    """半透明红色蒙版 + 黄色边界线叠加原图并 4× 放大，供人工核对（第二轮复验）。

    内部仅着色 ~31% 不透明度红，原图细节仍可辨；边界用蒙版边缘检测描黄线，
    替代原整片高不透明度红（评审：不利核对内部对齐）。
    """
    with Image.open(work_png) as image:
        base = image.convert("RGBA").resize(
            (mask_arr.shape[1] * 4, mask_arr.shape[0] * 4), Image.NEAREST
        )
    red = Image.new("RGBA", base.size, (255, 48, 48, 80))
    mask_up = Image.fromarray(mask_arr, mode="L").resize(base.size, Image.NEAREST)
    base.paste(red, (0, 0), mask_up)
    edges = mask_up.filter(ImageFilter.FIND_EDGES)
    yellow = Image.new("RGBA", base.size, (255, 214, 0, 255))
    base.paste(yellow, (0, 0), edges)
    base.save(out_png)


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
    xx, yy = np.meshgrid(np.linspace(0.0, PREVIEW_WIDTH_MM, nx), np.linspace(0.0, height_mm, ny))
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
    out_dir = OUT / f"{run_root.name}-{key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    photo = service.import_photo(source)
    photo_manifest = service.store.get(photo.revision_id)

    mask_arr = full_subject_mask(key, photo_manifest)
    mask_png = out_dir / "mask.png"
    Image.fromarray(mask_arr, mode="L").save(mask_png)
    Image.fromarray(mask_arr, mode="L").resize((mask_arr.shape[1] * 4, mask_arr.shape[0] * 4)).save(
        out_dir / "mask-preview.png"
    )
    save_mask_overlay(
        service.store.directory(photo.revision_id) / "work.png",
        mask_arr,
        out_dir / "mask-overlay.png",
    )
    mask = service.save_mask(
        photo.revision_id,
        mask_png,
        MaskMethod.MANUAL,
        notes=(
            "P1 复验蒙版（R3 第三轮）：完整可见主体多边形。三张均按四角背景色阈值"
            "客观测定（最大连通域+补洞+闭运算平滑后并回原前景，IoU≥0.985）；"
            "半透明叠加图（黄边界线）人工复核；M0.5 旧标注文件保留但不再引用"
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
        "mask_overlay": str(out_dir / "mask-overlay.png"),
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
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "photos": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
