#!/usr/bin/env python3
"""PH09：三张真实照片走完整 P1 管线（导入→人工蒙版→真实深度→离屏渲染）。

运行（真机、需已安装模型）：
    scripts/dev.sh run --frozen python experiments/photo_relief/run_p1_three_photos.py
    （可选 --only 短毛犬 / 猫 / 长毛犬）

要点：
- 每张照片使用全新工程目录（时间戳后缀，绝不覆盖既有数据）；
- 蒙版 = FULL_SUBJECT_POLYGONS 完整可见主体多边形（P1 复验 R4 第四轮：阈值
  辅助测定 + 人工复核修正，mask_method=threshold_assisted，判据见多边形注释；
  叠加图人工复核）。
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


# P1 复验（R4，第四轮）：覆盖完整可见主体的蒙版多边形（原图像素坐标，左上原点）。
# 三张均为阈值辅助测定 + 人工复核修正（评审 C：IoU 只是多边形对自身阈值掩码的
# 自洽检查，不等于主体正确率；浅色毛/灰影须回原图逐处判定）：
# - 前景判据按图选择：短毛犬=四角背景色欧氏距离>40；猫=色度 R−B>12 且距离>18
#   （猫毛暖调、白背景与右下灰影水印均中性，色度可分离）；长毛犬=距离>35 主域
#   ∪ 距离>40 主域（白毛浅，降档补回腹/腿间浅色毛，争议区实测 0% 纯白）。
# - 共同后处理：最大连通域（弃水印碎块）→ 补洞 → 闭运算 2px 平滑凹口后并回
#   原前景（不削细毛尖）→ Moore 追迹 + Douglas-Peucker 简化，回填 IoU ≥ 0.985。
# - 人工修正记录：猫右下灰影矩形（中性灰 [161,158,157] vs 猫毛暖调
#   [157,134,126]，gettyimages 白字水印叠灰影上）第三轮曾被误纳为身体，
#   第四轮以色度判据剔除；短毛犬"颈胸缺口"经色度右沿（x≈111-119）与当前
#   多边形三重核对一致，判定为纯红叠加图（B 缺陷）造成的误读，不改。
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
    # 第四轮色度轮廓：耳尖到 y=0、右缘沿暖色毛 (127,89)→(125,110)→(138,144)
    # 直落底部条带右端；右下灰影矩形（x≈128-147 y≈114-138，水印叠灰影上）
    # 已剔除——第三轮亮度阈值版曾把它误纳为身体。
    "cat": [
        (37, 0),
        (49, 0),
        (62, 12),
        (78, 13),
        (82, 19),
        (86, 16),
        (102, 16),
        (120, 4),
        (133, 0),
        (135, 6),
        (122, 39),
        (124, 59),
        (121, 69),
        (127, 89),
        (125, 110),
        (138, 144),
        (138, 147),
        (0, 147),
        (4, 137),
        (16, 125),
        (20, 113),
        (35, 97),
        (41, 78),
        (42, 67),
        (38, 46),
        (43, 32),
        (37, 1),
    ],
    # 全身（趴卧姿态：头在左上，背线向右下斜至臀部，左前爪伸向左下）。
    # 第四轮 thr35∪thr40 轮廓（eps=1.0，IoU 0.991）：头顶/耳尖 y≈10、背线
    # (124,22)→(143,52)→(189,90)→(199,117)、右腹到 x≈199；第三轮阈值过深
    # 把腹/腿间浅色毛（x118-141 y106-135 等三区，实测中位 dist 35-39、
    # 0% 纯白）挖空成锯齿凹口，本轮补回连续腹线及后腿下缘 (159,134)→
    # (150,135)→(144,133)→(140,135)→(128,135)→(119,140)→(113,141)→(15,140)。
    "long_hair_dog": [
        (78, 10),
        (84, 10),
        (91, 15),
        (97, 13),
        (104, 13),
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
        (159, 63),
        (167, 67),
        (177, 76),
        (183, 85),
        (189, 90),
        (188, 94),
        (194, 102),
        (195, 111),
        (199, 117),
        (199, 125),
        (193, 130),
        (188, 131),
        (172, 131),
        (159, 134),
        (156, 132),
        (150, 135),
        (144, 133),
        (140, 135),
        (128, 135),
        (119, 140),
        (115, 139),
        (113, 141),
        (15, 140),
        (13, 138),
        (13, 132),
        (19, 122),
        (24, 120),
        (32, 112),
        (36, 111),
        (45, 101),
        (45, 93),
        (51, 81),
        (48, 77),
        (46, 77),
        (48, 72),
        (45, 65),
        (46, 60),
        (44, 58),
        (46, 42),
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
    """红色 ~31% 混合进原图 RGB + 黄色边界线，4× 放大，供人工核对。

    用 alpha_composite 真正把 (255,48,48,80) 混入原图（主体内部五官/毛流仍可
    辨），成品转 RGB 保存——旧实现 paste 用蒙版整片替换像素，得到纯红 RGB +
    alpha=80，主体内部是"红色×查看器底色"，原图细节完全不可见（第三轮评审 B）。
    """
    with Image.open(work_png) as image:
        base = image.convert("RGBA").resize(
            (mask_arr.shape[1] * 4, mask_arr.shape[0] * 4), Image.NEAREST
        )
    mask_up = Image.fromarray(mask_arr, mode="L").resize(base.size, Image.NEAREST)
    tint = Image.new("RGBA", base.size, (255, 48, 48, 0))
    tint.putalpha(mask_up.point(lambda value: value * 80 // 255))  # 主体处 α=80/255
    base = Image.alpha_composite(base, tint)
    edges = mask_up.filter(ImageFilter.FIND_EDGES)
    base.paste((255, 214, 0), (0, 0), edges)  # 边界描不透明黄线
    base.convert("RGB").save(out_png)


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
        MaskMethod.THRESHASSISTED,
        notes=(
            "P1 复验蒙版（R4 第四轮，threshold_assisted）：完整可见主体多边形。"
            "前景判据：短毛犬=背景色距离>40；猫=色度 R−B>12 且距离>18；"
            "长毛犬=距离>35 主域∪距离>40 主域。后处理：最大连通域+补洞+闭运算"
            "2px 后并回原前景，回填 IoU≥0.985。人工修正：猫剔除右下灰影水印块"
            "（评审C）；长毛犬补回腹/腿间浅色毛；短毛犬经色度复核未改。"
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
