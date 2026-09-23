"""皮革阴阳模数值核心（MOLD-PAIR 规划书 §3）；纯数值 + 确定性网格工具。

关键口径：
- 阴模内表面 = 阳模接触面的**球形偏置上包络**（离散 Minkowski 膨胀）：
  每个采样点上方放半径 t_effective(+guard) 的球取上半最大值。凸脊被圆化，
  处处欧氏距离 ≥ 目标——不是局部 t/n_z 的平面近似（规划书 §3.2）。
- 梯度一律**单侧最大差分**（与 P2 slope_report 同口径），断崖不折半（§3.3）。
- 平坦止口 = 版边余量 − 源母版过渡带宽；不足时**模具侧平铺扩边**，
  原核心像素逐位不变（×1.0 精确），新增区域平滑落地到 0 后接纯平止口（§3.4）。
- 独立验收：把两接触面三角化后双向采样（顶点+三边中点+面心），
  KD-tree 最近点距离；不得用包络公式回填自证（§3.2 验收）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

DISTANCE_TOLERANCE_FLOOR_MM = 0.05  # 离散网格验收容差下限（规划书 §7）
DISTANCE_TOLERANCE_SPACING_RATIO = 0.25  # 容差 = max(下限, 0.25×max(dx,dy))
EXPANSION_TRANSITION_MIN_MM = 1.0  # 扩边落地过渡最小宽度（工程值）
EXPANSION_TRANSITION_SLOPE = 1.5  # smoothstep 峰值斜率（与 P2 裙边公式同源）
EXPANSION_TRANSITION_CAP_MM = 12.0  # 过渡宽度上限（防贴边大高度把版面撑爆）
FLAT_EPS_MM = 1e-9  # 判定"纯平"的高度容差（构造上背景恒 0）


def distance_tolerance_mm(dx_mm: float, dy_mm: float) -> float:
    """独立最近距离验收容差（§7）：max(0.05, 0.25×最大网格间距)。"""
    return max(
        DISTANCE_TOLERANCE_FLOOR_MM,
        DISTANCE_TOLERANCE_SPACING_RATIO * max(float(dx_mm), float(dy_mm)),
    )


def one_sided_slope(heights_mm: np.ndarray, dx_mm: float, dy_mm: float) -> dict[str, Any]:
    """单侧最大差分坡度（相邻单元 |Δh|/间距，不中心差分）。"""

    heights = np.asarray(heights_mm, dtype=np.float64)
    gx = np.abs(np.diff(heights, axis=1)) / float(dx_mm)
    gy = np.abs(np.diff(heights, axis=0)) / float(dy_mm)
    x_max = float(gx.max()) if gx.size else 0.0
    y_max = float(gy.max()) if gy.size else 0.0
    overall = max(x_max, y_max)
    return {
        "x_max_mm_per_mm": x_max,
        "y_max_mm_per_mm": y_max,
        "max_mm_per_mm": overall,
        "max_deg": math.degrees(math.atan(overall)),
    }


def _cell_gradients(
    heights_mm: np.ndarray, dx_mm: float, dy_mm: float
) -> tuple[np.ndarray, np.ndarray]:
    """逐单元单侧最大梯度（左右/上下邻差取大；边界用存在的一侧）。"""

    heights = np.asarray(heights_mm, dtype=np.float64)
    diff_x = np.abs(np.diff(heights, axis=1)) / float(dx_mm)
    diff_y = np.abs(np.diff(heights, axis=0)) / float(dy_mm)
    gx = np.maximum(
        np.pad(diff_x, ((0, 0), (1, 0)), mode="edge"),
        np.pad(diff_x, ((0, 0), (0, 1)), mode="edge"),
    )
    gy = np.maximum(
        np.pad(diff_y, ((1, 0), (0, 0)), mode="edge"),
        np.pad(diff_y, ((0, 1), (0, 0)), mode="edge"),
    )
    return gx, gy


def normal_clearance_field(
    axial_gap_mm: np.ndarray, male_contact_mm: np.ndarray, dx_mm: float, dy_mm: float
) -> np.ndarray:
    """公式法向间隙场（仅报告用）：Z 间隙 × n_z，不作为阴模几何依据。"""

    gx, gy = _cell_gradients(male_contact_mm, dx_mm, dy_mm)
    n_z = 1.0 / np.sqrt(1.0 + gx**2 + gy**2)
    return np.asarray(axial_gap_mm, dtype=np.float64) * n_z


def expand_heightfield(
    heights_mm: np.ndarray,
    dx_mm: float,
    dy_mm: float,
    *,
    existing_flat_mm: float,
    edge_margin_mm: float,
    max_plate_mm: float,
    plate_width_mm: float,
    plate_height_mm: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    """平铺扩边（§3.4）：止口不足时在模具侧加过渡+纯平止口；核心逐位不变。

    existing_flat_mm = 版边余量 − 源母版过渡带宽（贴边记 0）；≥ edge_margin 时
    原样返回。过渡宽度按"裙边同源 smoothstep 斜率 1.5×边缘高度"确定，记录在
    report；扩边后单边版面超过 max_plate_mm 抛错（拒绝原因由调用方入 manifest）。
    """

    heights = np.asarray(heights_mm, dtype=np.float64)
    ny, nx = heights.shape
    if existing_flat_mm >= edge_margin_mm:
        report: dict[str, Any] = {
            "expanded": False,
            "existing_flat_mm": float(existing_flat_mm),
            "edge_margin_mm": float(edge_margin_mm),
        }
        return heights, report

    border = np.concatenate([heights[0, :], heights[-1, :], heights[:, 0], heights[:, -1]])
    border_max = float(border.max())
    transition = min(
        EXPANSION_TRANSITION_CAP_MM,
        max(EXPANSION_TRANSITION_MIN_MM, EXPANSION_TRANSITION_SLOPE * border_max),
    )
    pad_x = int(math.ceil((transition + edge_margin_mm) / dx_mm))
    pad_y = int(math.ceil((transition + edge_margin_mm) / dy_mm))
    final_w = plate_width_mm + 2.0 * pad_x * dx_mm
    final_h = plate_height_mm + 2.0 * pad_y * dy_mm
    if max(final_w, final_h) > max_plate_mm + 1e-9:
        raise ValueError(
            f"扩边后版面 {final_w:.1f}×{final_h:.1f} mm 超过 max_plate_mm "
            f"{max_plate_mm:.1f} mm；请降低 edge_margin_mm 或提高 max_plate_mm"
        )

    replicated = np.pad(heights, ((pad_y, pad_y), (pad_x, pad_x)), mode="edge")
    core = np.zeros(replicated.shape, dtype=bool)
    core[pad_y : pad_y + ny, pad_x : pad_x + nx] = True
    distance = ndimage.distance_transform_edt(~core, sampling=(float(dy_mm), float(dx_mm)))
    t = np.clip(distance / transition, 0.0, 1.0)
    decay = 1.0 - (3.0 * t * t - 2.0 * t * t * t)  # 核心内 t=0 → decay=1 → ×1.0 精确
    padded = replicated * decay
    report = {
        "expanded": True,
        "existing_flat_mm": float(existing_flat_mm),
        "edge_margin_mm": float(edge_margin_mm),
        "border_max_mm": border_max,
        "transition_mm": float(transition),
        "pad_x_px": pad_x,
        "pad_y_px": pad_y,
        "core_rows": [pad_y, pad_y + ny],
        "core_cols": [pad_x, pad_x + nx],
        "final_width_mm": float(final_w),
        "final_height_mm": float(final_h),
        "flat_stop_min_mm": float(min(pad_x * dx_mm, pad_y * dy_mm) - transition),
    }
    return padded, report


def spherical_envelope(
    surface_mm: np.ndarray, dx_mm: float, dy_mm: float, radius_mm: float
) -> tuple[np.ndarray, dict[str, Any]]:
    """球形偏置上包络（§3.2）：max over 椭圆盘 (du,dv) [surface + √(R²−r²)]。

    radius_mm = t_effective + discretization_guard_mm（由调用方决定 guard 并记录）。
    网格外无实体，越界贡献记 −inf（不虚构版面外材料）；(0,0) 偏移保证
    envelope ≥ surface + R ≥ surface + t_effective 处处成立。
    """

    surface = np.asarray(surface_mm, dtype=np.float64)
    if radius_mm <= 0.0:
        raise ValueError("包络半径必须为正")
    ny, nx = surface.shape
    du_max = int(math.floor(radius_mm / dx_mm))
    offsets: list[tuple[int, int, float]] = []
    for du in range(-du_max, du_max + 1):
        rest2 = radius_mm**2 - (du * dx_mm) ** 2
        if rest2 < 0.0:
            continue
        dv_limit = int(math.floor(math.sqrt(rest2) / dy_mm))
        for dv in range(-dv_limit, dv_limit + 1):
            lift = math.sqrt(radius_mm**2 - (du * dx_mm) ** 2 - (dv * dy_mm) ** 2)
            offsets.append((du, dv, lift))
    envelope = np.full((ny, nx), -np.inf)
    for du, dv, lift in offsets:
        # envelope[i,j] 取 surface[i-du, j-dv] + lift（球心在被偏移单元）
        i0d, i1d = max(0, du), min(nx, nx + du)
        j0d, j1d = max(0, dv), min(ny, ny + dv)
        i0s, i1s = i0d - du, i1d - du
        j0s, j1s = j0d - dv, j1d - dv
        view = envelope[j0d:j1d, i0d:i1d]
        np.maximum(view, surface[j0s:j1s, i0s:i1s] + lift, out=view)
    if not np.isfinite(envelope).all():  # (0,0) 偏移保证不会发生；防御性断言
        raise ValueError("包络计算出现未覆盖单元")
    report = {
        "radius_mm": float(radius_mm),
        "offsets": len(offsets),
        "radius_px_x": radius_mm / float(dx_mm),
        "radius_px_y": radius_mm / float(dy_mm),
    }
    return envelope, report


def grid_surface_trimesh(z_mm: np.ndarray, width_mm: float, height_mm: float) -> trimesh.Trimesh:
    """高度场 → 顶面三角网格（外法向 +Z；与 solid_between 顶面同构）。"""

    z = np.asarray(z_mm, dtype=np.float64)
    ny, nx = z.shape
    xx, yy = np.meshgrid(np.linspace(0.0, width_mm, nx), np.linspace(0.0, height_mm, ny))
    points = np.column_stack([xx.ravel(), yy.ravel(), z.ravel()])
    index = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)).ravel()
    b, c, d = index + 1, index + nx + 1, index + nx
    faces = np.vstack([np.column_stack([index, b, c]), np.column_stack([index, c, d])])[:, ::-1]
    return trimesh.Trimesh(points, faces, process=False)


def _surface_samples(mesh: trimesh.Trimesh) -> np.ndarray:
    """确定性表面采样：顶点 + 三边中点 + 面心（弦长误差 ~O(edge²/8R)，入报告）。"""

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    corners = vertices[faces]
    return np.vstack(
        [
            vertices,
            0.5 * (corners[:, 0] + corners[:, 1]),
            0.5 * (corners[:, 1] + corners[:, 2]),
            0.5 * (corners[:, 2] + corners[:, 0]),
            corners.mean(axis=1),
        ]
    )


def bidirectional_min_distance(mesh_a: trimesh.Trimesh, mesh_b: trimesh.Trimesh) -> dict[str, Any]:
    """双向独立最近距离（KD-tree 点集采样；规划书 §3.2 验收）。"""

    samples_a = _surface_samples(mesh_a)
    samples_b = _surface_samples(mesh_b)
    a_to_b = float(cKDTree(samples_b).query(samples_a, workers=-1)[0].min())
    b_to_a = float(cKDTree(samples_a).query(samples_b, workers=-1)[0].min())
    return {
        "min_mm": min(a_to_b, b_to_a),
        "a_to_b_mm": a_to_b,
        "b_to_a_mm": b_to_a,
        "samples_a": int(len(samples_a)),
        "samples_b": int(len(samples_b)),
    }
