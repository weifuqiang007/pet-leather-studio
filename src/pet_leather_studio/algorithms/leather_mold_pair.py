"""皮革阴阳模数值核心（MOLD-PAIR 规划书 §3）；纯数值 + 确定性网格工具。

关键口径：
- 阴模内表面 = 阳模接触面的**球形偏置上包络**（离散 Minkowski 膨胀）：
  球心取自三角面**重心细分格**（不只网格顶点），每球心对半径内节点取
  z + √(R²−d²) 的最大值。凸脊被圆化，处处欧氏距离 ≥ 目标——不是局部
  t/n_z 的平面近似（规划书 §3.2）。
- 梯度一律**单侧最大差分**（与 P2 slope_report 同口径），断崖不折半（§3.3）。
- 平坦止口 = 版边余量 − 源母版过渡带宽；不足时**模具侧平铺扩边**，
  原核心像素逐位不变（×1.0 精确），新增区域平滑落地到 0 后接纯平止口（§3.4）。
- 独立验收（M1-R1）：两面各自重心细分采样后，对每个采样点计算到**另一张
  三角网格的精确点到三角面距离**（Ericson 最近点 + 质心 KD-tree 候选 +
  半径证书兜底），双向都测；不再用采样点之间的点到点 KD-tree 冒充连续
  距离，也不得用包络公式回填自证（§3.2 验收）。
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
SUBDIVISION_ORDER = 4  # 重心细分阶数：包络球心与验收采样同一口径（每面 15 点）
DISTANCE_METHOD = (
    "barycentric-subdivision sampling + exact point-to-triangle distance "
    "(centroid KD-tree candidates + radius certificate)"
)
_DISTANCE_CANDIDATES = 96  # 质心 KD-tree 候选数 k（半径证书：第 k 近质心 − 外接半径）
_DISTANCE_EXACT_SLOTS = 8  # 先只对最近 8 个候选精确算距（证书不满足再球查询兜底）
_DISTANCE_CHUNK = 32768  # 点-三角精确距离的分块点数（控内存）


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


def _cell_sample_patterns(order: int) -> list[tuple[float, float, float, float, float, float]]:
    """单元内两三角的重心细分格 → (w00,w10,w01,w11, lx, ly)。

    三角剖分与 grid_surface_trimesh 同构（对角线 (0,0)-(1,1)）；权重是对应
    三角顶点的重心系数（另一角为 0），保证 σ 值 = 分片线性表面的精确插值。
    lx/ly 为单元内位置（0..1，单位为格距）。对角线上的公共点按权重去重。
    """

    corner_slot = {(0.0, 0.0): 0, (1.0, 0.0): 1, (0.0, 1.0): 2, (1.0, 1.0): 3}
    triangles = (((0, 0), (1, 0), (1, 1)), ((0, 0), (0, 1), (1, 1)))
    patterns: dict[tuple[float, float, float, float], tuple[float, ...]] = {}
    for v0, v1, v2 in triangles:
        for i in range(order + 1):
            for j in range(order + 1 - i):
                k = order - i - j
                weights = [0.0, 0.0, 0.0, 0.0]
                for vertex, coefficient in ((v0, i), (v1, j), (v2, k)):
                    weights[corner_slot[vertex]] += coefficient / order
                lx = (i * v0[0] + j * v1[0] + k * v2[0]) / order
                ly = (i * v0[1] + j * v1[1] + k * v2[1]) / order
                key = (weights[0], weights[1], weights[2], weights[3])
                patterns.setdefault(key, (*key, lx, ly))
    return [tuple(pattern) for pattern in patterns.values()]


def spherical_envelope(
    surface_mm: np.ndarray,
    dx_mm: float,
    dy_mm: float,
    radius_mm: float,
    *,
    subdivision_order: int = SUBDIVISION_ORDER,
) -> tuple[np.ndarray, dict[str, Any]]:
    """球形偏置上包络（§3.2）：以三角面重心细分采样为球心取上半最大值。

    球心不只放在网格顶点：单元两三角按重心细分格离散连续曲面（与独立验收
    采样同一口径），每个球心对水平距离 ≤ radius 的节点 deposit
    z_sample + √(R²−d²)（d 为球心到节点的精确水平距离）。核心性质保持：
    每个节点是某单元角 σ，(0,0) 偏移 lift = R ⇒ envelope ≥ surface + R 处处。
    radius_mm = t_effective + discretization_guard_mm（由调用方决定 guard 并记录）。
    """

    surface = np.asarray(surface_mm, dtype=np.float64)
    if radius_mm <= 0.0:
        raise ValueError("包络半径必须为正")
    if subdivision_order < 1:
        raise ValueError("subdivision_order 必须 ≥ 1")
    ny, nx = surface.shape
    if ny < 2 or nx < 2:
        raise ValueError("包络需要 ≥ 2×2 高度场（否则不存在三角面）")
    patterns = _cell_sample_patterns(subdivision_order)
    z00, z10 = surface[:-1, :-1], surface[:-1, 1:]
    z01, z11 = surface[1:, :-1], surface[1:, 1:]
    radius_sq = radius_mm**2
    envelope = np.full((ny, nx), -np.inf)
    used_offsets: set[tuple[int, int]] = set()
    for w00, w10, w01, w11, lx, ly in patterns:
        field = w00 * z00 + w10 * z10 + w01 * z01 + w11 * z11
        k_min = -int(math.floor((radius_mm + lx * dx_mm) / dx_mm)) - 1
        k_max = int(math.floor((radius_mm + (1.0 - lx) * dx_mm) / dx_mm)) + 1
        l_min = -int(math.floor((radius_mm + ly * dy_mm) / dy_mm)) - 1
        l_max = int(math.floor((radius_mm + (1.0 - ly) * dy_mm) / dy_mm)) + 1
        for k in range(k_min, k_max + 1):
            d2x = ((k - lx) * dx_mm) ** 2
            if d2x > radius_sq:
                continue
            for row_offset in range(l_min, l_max + 1):
                d2 = d2x + ((row_offset - ly) * dy_mm) ** 2
                if d2 > radius_sq:
                    continue
                # 目标节点 = 单元原点 + (k, row_offset)，须落在 0..n-1；源单元行 0..n-2
                sr0, sr1 = max(0, -row_offset), min(ny - 1, ny - row_offset)
                sc0, sc1 = max(0, -k), min(nx - 1, nx - k)
                if sr0 >= sr1 or sc0 >= sc1:
                    continue
                lift = math.sqrt(radius_sq - d2)
                used_offsets.add((k, row_offset))
                view = envelope[sr0 + row_offset : sr1 + row_offset, sc0 + k : sc1 + k]
                np.maximum(view, field[sr0:sr1, sc0:sc1] + lift, out=view)
    if not np.isfinite(envelope).all():  # 角点 σ 的 (0,0) 偏移保证不会发生
        raise ValueError("包络计算出现未覆盖单元")
    report = {
        "radius_mm": float(radius_mm),
        "subdivision_order": int(subdivision_order),
        "samples_per_cell": len(patterns),
        "surface_samples": int(len(patterns) * (ny - 1) * (nx - 1)),
        "offsets": len(used_offsets),
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


def _barycentric_samples(mesh: trimesh.Trimesh, order: int) -> np.ndarray:
    """确定性重心细分采样（每面 (m+1)(m+2)/2 点，含三顶点；不去重）。"""

    corners = np.asarray(mesh.vertices, dtype=np.float64)[
        np.asarray(mesh.faces, dtype=np.int64)
    ]  # (F,3,3)
    lattice = (
        np.array(
            [(i, j, order - i - j) for i in range(order + 1) for j in range(order + 1 - i)],
            dtype=np.float64,
        )
        / order
    )  # (L,3)
    return (corners[:, None, :, :] * lattice[None, :, :, None]).sum(axis=2).reshape(-1, 3)


def _closest_point_distances(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """点到三角面精确距离（Ericson《Real-Time Collision Detection》5.1.5 向量化）。

    points (N,3)、triangles (N,K,3,3) → (N,K) 距离；退化三角（面积 0）回退
    三顶点最近点，不产生 NaN。高度场网格间距恒正，正常输入不会退化。
    """

    a, b, c = triangles[..., 0, :], triangles[..., 1, :], triangles[..., 2, :]
    ab, ac = b - a, c - a
    p = points[:, None, :]
    ap, bp, cp = p - a, p - b, p - c
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4

    def _edge(base: np.ndarray, vector: np.ndarray, num: np.ndarray, den: np.ndarray) -> np.ndarray:
        safe = den != 0.0
        t = np.clip(np.where(safe, num / np.where(safe, den, 1.0), 0.0), 0.0, 1.0)
        return np.linalg.norm(p - (base + t[..., None] * vector), axis=-1)

    face_den = va + vb + vc
    non_degenerate = face_den > 0.0
    v = np.where(non_degenerate, vb / np.where(face_den != 0.0, face_den, 1.0), 0.0)
    w = np.where(non_degenerate, vc / np.where(face_den != 0.0, face_den, 1.0), 0.0)
    face_distance = np.where(
        non_degenerate,
        np.linalg.norm(p - (a + v[..., None] * ab + w[..., None] * ac), axis=-1),
        np.inf,
    )
    vertex_min = np.minimum(
        np.linalg.norm(ap, axis=-1),
        np.minimum(np.linalg.norm(bp, axis=-1), np.linalg.norm(cp, axis=-1)),
    )
    region_distance = np.select(
        [
            (d1 <= 0.0) & (d2 <= 0.0),  # A 顶点区
            (d3 >= 0.0) & (d4 <= d3),  # B 顶点区
            (d6 >= 0.0) & (d5 <= d6),  # C 顶点区
            (vc <= 0.0) & (d1 >= 0.0) & (d3 <= 0.0),  # AB 边区
            (vb <= 0.0) & (d2 >= 0.0) & (d6 <= 0.0),  # AC 边区
            (va <= 0.0) & (d4 - d3 >= 0.0) & (d5 - d6 >= 0.0),  # BC 边区
        ],
        [
            np.linalg.norm(ap, axis=-1),
            np.linalg.norm(bp, axis=-1),
            np.linalg.norm(cp, axis=-1),
            _edge(a, ab, d1, d1 - d3),
            _edge(a, ac, d2, d2 - d6),
            _edge(b, c - b, d4 - d3, (d4 - d3) + (d5 - d6)),
        ],
        default=face_distance,
    )
    return np.where(non_degenerate, region_distance, vertex_min)


def _exact_mesh_distance(
    points: np.ndarray, mesh: trimesh.Trimesh, *, candidates: int = _DISTANCE_CANDIDATES
) -> tuple[np.ndarray, dict[str, Any]]:
    """每个采样点到整张三角网格的精确最近距离。

    质心 KD-tree 取前 candidates 个候选，先只对最近 _DISTANCE_EXACT_SLOTS 个
    精确算距（真距离的上界）；用"第 k 近质心距离 − 外接半径 ≥ 上界"作证书——
    成立时上界 ≥ 真值 ≥ 下界 ≥ 上界，三者相等即精确值。不满足的点用
    上界 + 外接半径做球查询，对面内全部三角矢量化重算——此后结果按构造精确。
    """

    corners = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces, dtype=np.int64)]
    centroids = corners.mean(axis=1)
    circum_max = float(np.linalg.norm(corners - centroids[:, None, :], axis=2).max())
    tree = cKDTree(centroids)
    k = int(min(candidates, len(corners)))
    slots = min(_DISTANCE_EXACT_SLOTS, k)
    best = np.empty(len(points), dtype=np.float64)
    kth_last = np.empty(len(points), dtype=np.float64)
    for start in range(0, len(points), _DISTANCE_CHUNK):
        stop = min(start + _DISTANCE_CHUNK, len(points))
        kth, idx = tree.query(points[start:stop], k=k, workers=-1)
        if k == 1:
            kth, idx = kth[:, None], idx[:, None]
        best[start:stop] = _closest_point_distances(
            points[start:stop], corners[idx[:, :slots]]
        ).min(axis=1)
        kth_last[start:stop] = kth[:, -1]
    uncertain = (kth_last - circum_max) < best - 1e-12
    refined = int(uncertain.sum())
    if refined:
        sub = points[uncertain]
        radii = best[uncertain] + circum_max + 1e-12
        lists = tree.query_ball_point(sub, radii)
        counts = np.fromiter((len(ids) for ids in lists), dtype=np.int64, count=len(lists))
        point_index = np.repeat(np.arange(len(sub)), counts)
        flat_faces = (
            np.concatenate([np.asarray(ids, dtype=np.int64) for ids in lists])
            if counts.sum()
            else np.empty(0, dtype=np.int64)
        )
        pair_best = np.empty(len(point_index), dtype=np.float64)
        for start in range(0, len(point_index), _DISTANCE_CHUNK):
            stop = min(start + _DISTANCE_CHUNK, len(point_index))
            pair_best[start:stop] = _closest_point_distances(
                sub[point_index[start:stop]], corners[flat_faces[start:stop]][:, None, :]
            )[:, 0]
        exact = np.full(len(sub), np.inf)
        np.minimum.at(exact, point_index, pair_best)
        best[uncertain] = np.minimum(best[uncertain], exact)
    stats = {
        "candidate_faces": k,
        "fast_exact_faces": slots,
        "circumradius_max_mm": circum_max,
        "certificate_refined_points": refined,
    }
    return best, stats


def _max_edge_mm(mesh: trimesh.Trimesh) -> float:
    corners = np.asarray(mesh.vertices, dtype=np.float64)[np.asarray(mesh.faces, dtype=np.int64)]
    edges = np.stack(
        [
            corners[:, 1] - corners[:, 0],
            corners[:, 2] - corners[:, 1],
            corners[:, 0] - corners[:, 2],
        ]
    )
    return float(np.linalg.norm(edges, axis=-1).max())


def bidirectional_min_distance(
    mesh_a: trimesh.Trimesh,
    mesh_b: trimesh.Trimesh,
    *,
    subdivision_order: int = SUBDIVISION_ORDER,
) -> dict[str, Any]:
    """双向独立最近距离（M1-R1）：细分采样 → 精确点到三角面（§3.2 验收）。

    报告的 min_mm 是连续三角面最小距离的可复算上界：两面各自按重心细分格
    采样，每个采样点到对面网格的距离精确；采样密度误差由 sampling_bound_mm
    （最大棱长 / (√3 × 细分阶)，子三角外接半径）给出，conservative_min_mm
    = min − bound 是真实间隙的证书化下界。不读包络公式场，不以公式自证。
    """

    samples_a = _barycentric_samples(mesh_a, subdivision_order)
    samples_b = _barycentric_samples(mesh_b, subdivision_order)
    dist_a, stats_a = _exact_mesh_distance(samples_a, mesh_b)
    dist_b, stats_b = _exact_mesh_distance(samples_b, mesh_a)
    a_to_b, b_to_a = float(dist_a.min()), float(dist_b.min())
    bound = max(_max_edge_mm(mesh_a), _max_edge_mm(mesh_b)) / (math.sqrt(3.0) * subdivision_order)
    return {
        "method": DISTANCE_METHOD,
        "min_mm": min(a_to_b, b_to_a),
        "a_to_b_mm": a_to_b,
        "b_to_a_mm": b_to_a,
        "samples_a": int(len(samples_a)),
        "samples_b": int(len(samples_b)),
        "points_per_face": (subdivision_order + 1) * (subdivision_order + 2) // 2,
        "subdivision_order": int(subdivision_order),
        "sampling_bound_mm": bound,
        "conservative_min_mm": min(a_to_b, b_to_a) - bound,
        "certified": True,  # 半径证书兜底后每点精确（见 _exact_mesh_distance）
        "certificate": {
            "a_to_b": stats_a,
            "b_to_a": stats_b,
        },
    }
