"""M0.5 relief spike：标注 → 区域基函数高度场 → 封闭 STL → 多视图。

一次性试验脚本（PRD 15/M0.5）：不做生产级持久化，但不豁免单位、
可复现与文件校验要求。生产代码不得导入本模块。

子命令：
  build      单个标注文件 → NPZ + STL + 视图 + validation.json
  selftest   3 个合成样本全链路 + 解析检查 + 局部性 + 可复现性
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

# 单位约定：所有几何量 mm；图像坐标 px（原点左上）；工件坐标 Y 向上（PRD 6.1）。
SCHEMA_VERSION = 1
WIDTH_TOL_MM = 0.01  # AC-F03-03
LOCALITY_DELTA_MM = 0.5  # 局部性测试扰动量
LOCALITY_SENSITIVITY_MM = 0.01  # |ΔH| 超过该值视为受影响


@dataclass(frozen=True)
class RegionSpec:
    """单个高度区域的标注（多边形，单位：图像像素坐标）。"""

    id: str
    polygon: tuple[tuple[float, float], ...]
    height_mm: float
    falloff_px: float


@dataclass(frozen=True)
class SpikeParams:
    """一次 spike 构建的全部参数（可完整重跑）。"""

    output_width_mm: float
    base_thickness_mm: float
    grid_nx: int
    image_width_px: int
    image_height_px: int
    regions: tuple[RegionSpec, ...]
    seed: int  # 当前算法确定性无随机；保留以满足参数快照契约
    annotation_name: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "algorithm": "region_basis_additive_heightfield_v1",
            "output_width_mm": self.output_width_mm,
            "base_thickness_mm": self.base_thickness_mm,
            "grid_nx": self.grid_nx,
            "image_size_px": [self.image_width_px, self.image_height_px],
            "seed": self.seed,
            "annotation_name": self.annotation_name,
            "regions": [
                {
                    "id": r.id,
                    "polygon": [list(p) for p in r.polygon],
                    "height_mm": r.height_mm,
                    "falloff_px": r.falloff_px,
                }
                for r in self.regions
            ],
        }


def load_annotation(path: Path) -> SpikeParams:
    """读取标注 JSON 并校验必要字段与取值范围。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("output_width_mm", "base_thickness_mm", "image_size_px", "regions"):
        if key not in data:
            raise ValueError(f"标注缺少字段 {key}: {path}")
    w_px, h_px = data["image_size_px"]
    if w_px <= 0 or h_px <= 0:
        raise ValueError("image_size_px 必须为正")
    if data["output_width_mm"] <= 0 or data["base_thickness_mm"] <= 0:
        raise ValueError("宽度与底厚必须为正（mm）")
    regions = tuple(
        RegionSpec(
            id=r["id"],
            polygon=tuple((float(x), float(y)) for x, y in r["polygon"]),
            height_mm=float(r["height_mm"]),
            falloff_px=float(r["falloff_px"]),
        )
        for r in data["regions"]
    )
    for r in regions:
        if len(r.polygon) < 3:
            raise ValueError(f"区域 {r.id} 多边形至少 3 点")
        if r.falloff_px <= 0:
            raise ValueError(f"区域 {r.id} falloff_px 必须为正")
    return SpikeParams(
        output_width_mm=float(data["output_width_mm"]),
        base_thickness_mm=float(data["base_thickness_mm"]),
        grid_nx=int(data.get("grid_nx", 512)),
        image_width_px=int(w_px),
        image_height_px=int(h_px),
        regions=regions,
        seed=int(data.get("seed", 0)),
        annotation_name=path.stem,
    )


def region_weight(
    region: RegionSpec,
    grid_nx: int,
    grid_ny: int,
    scale: float,
) -> np.ndarray:
    """区域平滑权重：栅格化多边形 → 高斯模糊 → 峰值归一化到 [0,1]。

    scale = grid_nx / image_width_px（每图像像素对应网格像素数）。
    """
    # 用足够大的画布栅格化（取多边形包围盒外扩 falloff*3，避免截断模糊）
    xs = [p[0] * scale for p in region.polygon]
    ys = [p[1] * scale for p in region.polygon]
    pad = int(region.falloff_px * scale * 3) + 2
    x_min = max(0, int(np.floor(min(xs))) - pad)
    y_min = max(0, int(np.floor(min(ys))) - pad)
    x_max = min(grid_nx, int(np.ceil(max(xs))) + pad)
    y_max = min(grid_ny, int(np.ceil(max(ys))) + pad)
    if x_max <= x_min or y_max <= y_min:
        return np.zeros((grid_ny, grid_nx), dtype=np.float32)

    canvas = Image.new("L", (grid_nx, grid_ny), 0)
    draw = ImageDraw.Draw(canvas)
    scaled = [(x * scale, y * scale) for x, y in region.polygon]
    draw.polygon(scaled, fill=255)
    mask = np.asarray(canvas, dtype=np.float32) / 255.0

    sigma = max(region.falloff_px * scale, 0.5)
    smoothed = gaussian_filter(mask, sigma=sigma, mode="constant")
    peak = float(smoothed.max())
    if peak <= 0.0:
        return np.zeros((grid_ny, grid_nx), dtype=np.float32)
    return np.clip(smoothed / peak, 0.0, 1.0).astype(np.float32)


def build_heightfield(params: SpikeParams) -> tuple[np.ndarray, float, float]:
    """构造基础高度场。

    返回 (H[ny,nx] mm, dx mm, dy mm)。
    网格间距按"首末采样点恰好覆盖目标跨度"约定：dx = W/(nx-1)、
    dy = H_mm/(ny-1)，因此实体包围盒精确等于 W × H_mm（AC-F03-03）。
    数组行序已翻转为工件 Y 向上：第 0 行对应工件 y=0（图像底部），
    最后一行对应图像顶部（PRD 6.1）。
    """
    aspect = params.image_height_px / params.image_width_px
    grid_ny = int(round(params.grid_nx * aspect))
    scale = params.grid_nx / params.image_width_px

    height = np.zeros((grid_ny, params.grid_nx), dtype=np.float32)
    for region in params.regions:
        weight = region_weight(region, params.grid_nx, grid_ny, scale)
        height += region.height_mm * weight
    # 轻度整体平滑，消除区域叠加的数值台阶
    height = gaussian_filter(height, sigma=1.0, mode="nearest").astype(np.float32)
    # 图像 v 向下 → 工件 y 向上：翻转行序
    height = np.ascontiguousarray(height[::-1])

    dx = params.output_width_mm / max(params.grid_nx - 1, 1)
    total_h_mm = params.output_width_mm * aspect
    dy = total_h_mm / max(grid_ny - 1, 1)
    return height, dx, dy


def heightfield_to_solid_mesh(
    height: np.ndarray,
    dx: float,
    dy: float,
    base_thickness_mm: float,
):
    """矩形域高度场 → 封闭实体网格（顶面=base+H，底面=0，四周侧壁）。

    使用列向量右手系：X 向右、Y 向上、Z 凸起。底面朝 -Z，法向朝外。
    """
    import trimesh

    ny, nx = height.shape
    xs = np.arange(nx, dtype=np.float64) * dx
    ys = np.arange(ny, dtype=np.float64) * dy
    grid_x, grid_y = np.meshgrid(xs, ys)  # (ny, nx)

    top_z = base_thickness_mm + height.astype(np.float64)
    bottom_z = np.zeros_like(top_z)

    top_idx = np.arange(ny * nx).reshape(ny, nx)
    bottom_idx = top_idx + ny * nx

    v_top = np.column_stack([grid_x.ravel(), grid_y.ravel(), top_z.ravel()])
    v_bottom = np.column_stack([grid_x.ravel(), grid_y.ravel(), bottom_z.ravel()])
    vertices = np.vstack([v_top, v_bottom])

    i00 = top_idx[:-1, :-1]
    i01 = top_idx[:-1, 1:]
    i10 = top_idx[1:, :-1]
    i11 = top_idx[1:, 1:]
    # 顶面三角形（法向 +Z）
    top_faces = np.vstack(
        [
            np.column_stack([i00.ravel(), i01.ravel(), i11.ravel()]),
            np.column_stack([i00.ravel(), i11.ravel(), i10.ravel()]),
        ]
    )
    # 底面（法向 -Z）
    j00 = bottom_idx[:-1, :-1]
    j01 = bottom_idx[:-1, 1:]
    j10 = bottom_idx[1:, :-1]
    j11 = bottom_idx[1:, 1:]
    bottom_faces = np.vstack(
        [
            np.column_stack([j00.ravel(), j11.ravel(), j01.ravel()]),
            np.column_stack([j00.ravel(), j10.ravel(), j11.ravel()]),
        ]
    )

    def wall(top_a, top_b, bot_a, bot_b):
        """一条竖直侧壁的三角形（外法向）。

        top_a/top_b 为沿边界相邻顶点的索引数组（A 在行进方向左侧时
        绕向为外法向）；长度 m 时输出 2m 个三角形。
        """
        return np.vstack(
            [
                np.column_stack([top_a, bot_a, bot_b]),
                np.column_stack([top_a, bot_b, top_b]),
            ]
        )

    faces = [top_faces, bottom_faces]
    # y=y_min 边（法向 -Y）：行 0
    faces.append(wall(top_idx[0, :-1], top_idx[0, 1:], bottom_idx[0, :-1], bottom_idx[0, 1:]))
    # y=y_max 边（法向 +Y）：行 ny-1
    faces.append(wall(top_idx[-1, 1:], top_idx[-1, :-1], bottom_idx[-1, 1:], bottom_idx[-1, :-1]))
    # x=x_min 边（法向 -X）：列 0
    faces.append(wall(top_idx[1:, 0], top_idx[:-1, 0], bottom_idx[1:, 0], bottom_idx[:-1, 0]))
    # x=x_max 边（法向 +X）：列 nx-1
    faces.append(wall(top_idx[:-1, -1], top_idx[1:, -1], bottom_idx[:-1, -1], bottom_idx[1:, -1]))

    all_faces = np.vstack(faces).astype(np.int64)
    return trimesh.Trimesh(vertices=vertices, faces=all_faces, process=False)


def render_views(
    mesh,
    out_dir: Path,
    width_mm: float,
) -> dict[str, str]:
    """中性材质多视图（正面/斜侧/侧视），各含真实比例与 Z×3 夸大版本。

    夸大版本文件名带 zx3 并在 validation.json 中声明；不冒充真实比例。
    优先 pyvista 离屏渲染；失败时回退 matplotlib 并如实记录。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    used: dict[str, str] = {}
    try:
        import pyvista as pv

        def shoot(mesh_to_use, name: str, camera: tuple[tuple[float, float, float], ...]) -> None:
            plotter = pv.Plotter(off_screen=True, window_size=(900, 900))
            plotter.add_mesh(mesh_to_use, color="gainsboro", smooth_shading=True)
            pos, focal, viewup = camera
            plotter.camera.position = pos
            plotter.camera.focal_point = focal
            plotter.camera.up = viewup
            path = out_dir / f"{name}.png"
            plotter.screenshot(str(path))
            plotter.close()
            used[name] = "pyvista_offscreen"

        w = width_mm
        dist = w * 2.2
        for tag, mesh_used, scale_label in (("z1", mesh, ""), ("zx3", mesh.copy(), "_zx3")):
            m = mesh_used
            if tag == "zx3":
                m.vertices[:, 2] = m.vertices[:, 2] * 3.0
            shoot(m, f"front{scale_label}", ((w / 2, w / 2, dist), (w / 2, w / 2, 0), (0, 1, 0)))
            shoot(
                m,
                f"oblique{scale_label}",
                (
                    (w / 2 - dist * 0.7, w / 2 - dist * 0.7, dist * 0.8),
                    (w / 2, w / 2, 0),
                    (0, 1, 0),
                ),
            )
            shoot(m, f"side{scale_label}", ((-dist, w / 2, w / 2), (0, w / 2, w / 2), (0, 1, 0)))
    except Exception as exc:  # noqa: BLE001 - 回退路径需如实记录原因
        used["fallback_reason"] = f"pyvista 离屏失败: {exc}"
        used.update(_render_views_matplotlib(mesh, out_dir, width_mm))
    return used


def _render_views_matplotlib(mesh, out_dir: Path, width_mm: float) -> dict[str, str]:
    """matplotlib 回退渲染（如实标注渲染器）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    produced: dict[str, str] = {}
    for tag, z_factor in (("z1", 1.0), ("zx3", 3.0)):
        verts = mesh.vertices.copy()
        verts[:, 2] *= z_factor
        for view, elev, azim in (("front", 5, -90), ("oblique", 25, -55), ("side", 2, 0)):
            fig = plt.figure(figsize=(7, 7))
            ax = fig.add_subplot(projection="3d")
            ax.plot_trisurf(
                verts[:, 0],
                verts[:, 1],
                verts[:, 2],
                triangles=mesh.faces,
                color="0.85",
                edgecolor="none",
            )
            ax.set_box_aspect((1, 1, 0.35))
            ax.view_init(elev=elev, azim=azim)
            ax.set_axis_off()
            path = out_dir / f"{view}_{tag}_matplotlib.png"
            fig.savefig(path, dpi=110, bbox_inches="tight")
            plt.close(fig)
            produced[f"{view}_{tag}"] = "matplotlib_agg"
    return produced


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_outputs(
    mesh,
    params: SpikeParams,
    height: np.ndarray,
    dx: float,
    dy: float,
    stl_path: Path,
) -> dict[str, object]:
    """数值验收：NaN/Inf、宽度、封闭性、体积、法向一致性。"""
    checks: dict[str, object] = {}
    checks["no_nan_inf"] = bool(np.isfinite(height).all())
    bbox_min, bbox_max = mesh.bounds
    measured_w = float(bbox_max[0] - bbox_min[0])
    measured_h = float(bbox_max[1] - bbox_min[1])
    checks["width_mm"] = {
        "target": params.output_width_mm,
        "measured": round(measured_w, 6),
        "abs_err_mm": round(abs(measured_w - params.output_width_mm), 6),
        "pass_le_0.01mm": bool(abs(measured_w - params.output_width_mm) <= WIDTH_TOL_MM),
    }
    checks["height_y_mm"] = {
        "expected_from_aspect": round(measured_h, 6),
    }
    checks["watertight"] = bool(mesh.is_watertight)
    checks["winding_consistent"] = bool(mesh.is_winding_consistent)
    checks["volume_positive"] = bool(mesh.volume > 0)
    checks["volume_mm3"] = round(float(mesh.volume), 4)
    checks["euler_number"] = int(mesh.euler_number)
    checks["face_count"] = int(len(mesh.faces))
    checks["dx_mm"] = dx
    checks["dy_mm"] = dy
    return checks


def cmd_build(annotation: Path, out: Path, spike_root: Path) -> int:
    started = time.perf_counter()
    params = load_annotation(annotation)
    out.mkdir(parents=True, exist_ok=True)

    height, dx, dy = build_heightfield(params)
    mesh = heightfield_to_solid_mesh(height, dx, dy, params.base_thickness_mm)

    stl_path = out / "relief_solid.stl"
    mesh.export(str(stl_path))

    npz_path = out / "heightfield.npz"
    np.savez_compressed(
        npz_path,
        schema_version=SCHEMA_VERSION,
        h_base_mm=height,
        dx_mm=dx,
        dy_mm=dy,
        base_thickness_mm=params.base_thickness_mm,
        origin_xy_mm=(0.0, 0.0),
    )

    snapshot = out / "params_snapshot.json"
    snapshot.write_text(
        json.dumps(params.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    views_dir = out / "views"
    renderers = render_views(mesh, views_dir, params.output_width_mm)

    validation = validate_outputs(mesh, params, height, dx, dy, stl_path)
    validation["renderers"] = renderers
    validation["stl_sha256"] = sha256_file(stl_path)
    validation["annotation_sha256"] = sha256_file(annotation)
    validation["elapsed_s"] = round(time.perf_counter() - started, 2)
    (out / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(spike_root: Path) -> int:
    """三个合成样本：全链路构建 + 解析检查 + 局部性 + 可复现性。"""
    ann_dir = spike_root / "annotations"
    work = spike_root / "out"
    if work.exists():
        shutil.rmtree(work)
    results: dict[str, object] = {}

    for name in ("sample_a_head", "sample_b_bump", "sample_c_flat"):
        out_dir = work / name
        rc = cmd_build(ann_dir / f"{name}.json", out_dir, spike_root)
        if rc != 0:
            return rc
        results[name] = json.loads((out_dir / "validation.json").read_text(encoding="utf-8"))

    failures: list[str] = []

    # 解析检查 1：平板块体积 == W × H × base（解析值）
    flat = results["sample_c_flat"]
    ann_c = json.loads((ann_dir / "sample_c_flat.json").read_text(encoding="utf-8"))
    w = ann_c["output_width_mm"]
    h_mm = w * (ann_c["image_size_px"][1] / ann_c["image_size_px"][0])
    expected_v = w * h_mm * ann_c["base_thickness_mm"]
    actual_v = flat["volume_mm3"]
    if abs(actual_v - expected_v) / expected_v > 1e-3:
        failures.append(f"平板体积 {actual_v} != 解析值 {expected_v:.2f}")

    # 解析检查 2：单凸起中心高度 ≈ 设定值（网格中心处顶面 − base）
    npz = np.load(work / "sample_b_bump" / "heightfield.npz")
    h_field = npz["h_base_mm"]
    center_val = float(h_field[h_field.shape[0] // 2, h_field.shape[1] // 2])
    ann_b = json.loads((ann_dir / "sample_b_bump.json").read_text(encoding="utf-8"))
    target = sum(r["height_mm"] for r in ann_b["regions"])
    if abs(center_val - target) > 0.15:  # 网格离散 + 平滑的容差
        failures.append(f"凸起中心 {center_val:.3f}mm 偏离设定 {target}mm 超容差")

    # 局部性：sample_a 鼻部 +0.5mm，|ΔH|>0.01mm 区域须在影响带内
    params_a = load_annotation(ann_dir / "sample_a_head.json")
    h_base, _, _ = build_heightfield(params_a)
    nose = next(r for r in params_a.regions if r.id == "nose")
    scale = params_a.grid_nx / params_a.image_width_px
    nose_weight = region_weight(nose, params_a.grid_nx, h_base.shape[0], scale)
    # build_heightfield 输出已翻转为工件 Y 向上；掩码需同样翻转后再比较
    nose_weight = np.ascontiguousarray(nose_weight[::-1])
    perturbed = SpikeParams(
        **{
            **params_a.__dict__,
            "regions": tuple(
                RegionSpec(**{**r.__dict__, "height_mm": r.height_mm + LOCALITY_DELTA_MM})
                if r.id == "nose"
                else r
                for r in params_a.regions
            ),
        }
    )
    h_pert, _, _ = build_heightfield(perturbed)
    delta = np.abs(h_pert - h_base)
    changed = delta > LOCALITY_SENSITIVITY_MM
    # 影响带 = 权重 > 0.01 的像素（高斯衰减尾），再外扩 3 个网格像素
    influence = nose_weight > 0.01
    influence_pad = gaussian_filter(influence.astype(np.float32), 3.0) > 0
    outside = changed & ~influence_pad
    leaked = int(outside.sum())
    if leaked > 0:
        failures.append(f"局部性泄漏：{leaked} 个网格点在影响带外发生 >0.01mm 变化")
    results["locality"] = {
        "delta_mm": LOCALITY_DELTA_MM,
        "changed_points": int(changed.sum()),
        "leaked_points_outside_influence": leaked,
    }

    # 可复现性：重跑 sample_a，STL sha256 一致
    first = results["sample_a_head"]["stl_sha256"]
    rerun_dir = work / "_rerun_a"
    cmd_build(ann_dir / "sample_a_head.json", rerun_dir, spike_root)
    second = json.loads((rerun_dir / "validation.json").read_text(encoding="utf-8"))["stl_sha256"]
    results["reproducibility"] = {
        "stl_sha256_run1": first,
        "stl_sha256_run2": second,
        "identical": first == second,
    }
    if first != second:
        failures.append("可复现性失败：同参数两次构建 STL 不一致")

    results["failures"] = failures
    results["all_pass"] = not failures
    report_path = spike_root / "out" / "selftest.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== selftest 汇总 ===")
    print(
        json.dumps(
            {k: results[k] for k in ("all_pass", "failures", "locality", "reproducibility")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    spike_root = Path(__file__).resolve().parent

    p_build = sub.add_parser("build", help="标注 → 高度场 + STL + 视图")
    p_build.add_argument("--annotation", type=Path, required=True)
    p_build.add_argument("--out", type=Path, required=True)

    sub.add_parser("selftest", help="合成样本全链路自测")

    args = parser.parse_args()
    if args.command == "build":
        return cmd_build(args.annotation, args.out, spike_root)
    return cmd_selftest(spike_root)


if __name__ == "__main__":
    sys.exit(main())
