"""高度数据 → 母版几何（VTP/OBJ/STL + LOD）；PH06。

复用 mold_solids.solid_between 生成加底水密实体；正面母版（master.vtp，
浮雕基准 0、底板另计）与加底实体（master.obj/.stl）分开产出与记录。
发布前重读全部网格做封闭/体积/边界/逐列起伏校验（≤1e-4 mm），任一失败
抛错，由应用层丢弃 staging——形状或封闭性不满足时不得标为成功可用母版。
坐标：几何 X 右、Y 上、Z 越大越凸；工作图行序经 image_to_geometry_rows
显式翻转，禁止靠肉眼临时取反。
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
import trimesh
from PIL import Image

from pet_leather_studio.algorithms.mold_solids import solid_between
from pet_leather_studio.algorithms.relief_height import (
    controlled_heights_mm,
    image_to_geometry_rows,
)
from pet_leather_studio.domain.photo_relief import (
    RECOMMENDED_MAX_RELIEF_MM,
    DepthSemantics,
    HeightMode,
    LocalAdjustment,
    ReferenceProfile,
    ReliefParameters,
    slope_exceedances,
)
from pet_leather_studio.infrastructure.revisions import file_hash

MASTER_ALGORITHM = "photo-relief-master-v1"
PREVIEW_MAX_CELLS = 150_000  # 预览 LOD 上限（与导入母版同口径）
GEOM_TOL_MM = 1e-4  # PH06 门：重读后单位/边界/起伏误差上限
REGION_SELECTION_THRESHOLD = 127  # 局部调整区域 PNG 二值化阈值


def _load_region_masks(
    adjustments: Sequence[LocalAdjustment], shape: tuple[int, int]
) -> list[tuple[np.ndarray, float, float]]:
    masks: list[tuple[np.ndarray, float, float]] = []
    for adjustment in adjustments:
        with Image.open(adjustment.region_png) as image:
            region = np.asarray(image.convert("L"), dtype=np.uint8)
        if region.shape != shape:
            raise ValueError(
                f"局部调整区域 {adjustment.region_png} 形状 {region.shape} 与深度 {shape} 不一致"
            )
        selected = (region > REGION_SELECTION_THRESHOLD).astype(np.float64)
        masks.append((selected, adjustment.offset_mm, adjustment.transition_mm))
    return masks


def _top_surface_polydata(heights: np.ndarray, xx: np.ndarray, yy: np.ndarray) -> pv.PolyData:
    """正面母版表面：与加底实体的顶面逐点逐面一致（solid_between 的 top 面）。"""
    ny, nx = heights.shape
    index = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)).ravel()
    b, c, d = index + 1, index + nx + 1, index + nx
    triangles = np.vstack([np.column_stack([index, b, c]), np.column_stack([index, c, d])])[
        :, ::-1
    ]  # 顶面外法向 +Z（与 solid_between 同构）
    faces = np.column_stack([np.full(len(triangles), 3), triangles]).ravel()  # 平铺连通性
    points = np.column_stack([xx.ravel(), yy.ravel(), heights.ravel()])
    return pv.PolyData(points, faces)


def _verify_solid_reload(
    path: Path,
    solid: trimesh.Trimesh,
    heights: np.ndarray,
    base_mm: float,
    dx: float,
    dy: float,
) -> float:
    """重读导出网格并校验：封闭、正体积、边界、逐列顶面起伏；返回最大误差 mm。"""
    reloaded = trimesh.load_mesh(path, process=True)
    if not reloaded.is_watertight:
        raise ValueError(f"{path.name} 重新读入不是水密实体")
    if reloaded.volume <= 0 or abs(reloaded.volume - solid.volume) > solid.volume * 5e-6 + 1e-9:
        raise ValueError(
            f"{path.name} 体积校验失败（重读 {reloaded.volume} vs 导出 {solid.volume}）"
        )
    ny, nx = heights.shape
    expected_bounds = np.array(  # trimesh bounds 布局：每轴 (min, max)
        [[0.0, 0.0, 0.0], [dx * (nx - 1), dy * (ny - 1), base_mm + heights.max()]]
    )
    if np.abs(np.asarray(reloaded.bounds) - expected_bounds).max() > GEOM_TOL_MM:
        raise ValueError(f"{path.name} 边界与预期不符：{list(reloaded.bounds)}")

    # 逐列顶面：按网格索引吸附后取每列最大 z，应等于 base + heights
    raw = trimesh.load_mesh(path, process=False)
    vertices = np.asarray(raw.vertices, dtype=np.float64).reshape(-1, 3)
    snap_tol = max(1e-6, 1e-3 * min(dx, dy))
    indices_i = np.round(vertices[:, 0] / dx).astype(int)
    indices_j = np.round(vertices[:, 1] / dy).astype(int)
    on_grid = (
        (np.abs(vertices[:, 0] - indices_i * dx) <= snap_tol)
        & (np.abs(vertices[:, 1] - indices_j * dy) <= snap_tol)
        & (indices_i >= 0)
        & (indices_i < nx)
        & (indices_j >= 0)
        & (indices_j < ny)
    )
    if not on_grid.any():
        raise ValueError(f"{path.name} 顶点无法对齐采样网格")
    tops = np.full((ny, nx), -np.inf)
    np.maximum.at(tops, (indices_j[on_grid], indices_i[on_grid]), vertices[on_grid, 2])
    if not np.isfinite(tops).all():
        raise ValueError(f"{path.name} 存在采样列缺失顶面顶点")
    error = float(np.abs(tops - (base_mm + heights)).max())
    if error > GEOM_TOL_MM:
        raise ValueError(f"{path.name} 顶面起伏误差 {error:.3e} mm 超过 {GEOM_TOL_MM} mm")
    return error


class PhotoGeometry:
    """ReliefGeometryPort 实现：受控高度 → 母版修订文件（含重读校验）。"""

    def build_master(
        self,
        depth_npz: Path,
        depth_metadata: Mapping[str, Any],
        parameters: ReliefParameters,
        profile: ReferenceProfile | None,
        adjustments: Sequence[LocalAdjustment],
        stage: Path,
    ) -> dict[str, Any]:
        for adjustment in adjustments:
            adjustment.validate()
        with np.load(depth_npz) as data:
            depth = np.asarray(data["depth"], dtype=np.float64)
            valid = np.asarray(data["valid"], dtype=bool)
        if depth.shape != valid.shape or depth.ndim != 2 or min(depth.shape) < 2:
            raise ValueError("深度数据形状无效（须为二维且与有效域同形）")
        masks = _load_region_masks(adjustments, depth.shape)
        heights_work, report = controlled_heights_mm(
            depth,
            valid,
            DepthSemantics(depth_metadata.get("depth_semantics")),
            parameters,
            profile,
            masks,
        )
        heights = image_to_geometry_rows(heights_work)  # 工作图 y 向下 → 几何 y 向上
        valid_geom = image_to_geometry_rows(valid)
        ny, nx = heights.shape
        width_mm = float(parameters.width_mm)
        height_mm = width_mm * ny / nx
        dx, dy = width_mm / (nx - 1), height_mm / (ny - 1)
        base_mm = float(parameters.base_thickness_mm)
        if not np.isfinite(heights).all():
            raise ValueError("高度场含非有限值")

        solid = solid_between(np.zeros_like(heights), heights + base_mm, width_mm, height_mm)
        solid.export(stage / "master.stl")
        solid.export(stage / "master.obj", digits=8)
        xx, yy = np.meshgrid(np.linspace(0.0, width_mm, nx), np.linspace(0.0, height_mm, ny))
        surface = _top_surface_polydata(heights, xx, yy)
        surface.save(stage / "master.vtp")
        preview = surface.clean(tolerance=0.0)
        if surface.n_cells > PREVIEW_MAX_CELLS:
            preview = preview.decimate(1 - PREVIEW_MAX_CELLS / surface.n_cells)
        preview.save(stage / "preview.vtp")
        np.savez_compressed(
            stage / "heightfield.npz",
            heights_mm=heights,
            valid=valid_geom,
            dx_mm=dx,
            dy_mm=dy,
            width_mm=width_mm,
            height_mm=height_mm,
            base_thickness_mm=base_mm,
            datum_z_mm=0.0,
            orientation="geometry_y_up",
            schema_version=2,
        )
        adjustment_records = []
        for index, adjustment in enumerate(adjustments):
            copied = stage / f"adjustment-{index}.png"
            shutil.copyfile(adjustment.region_png, copied)
            adjustment_records.append(
                {
                    "file": copied.name,
                    "label": adjustment.label,
                    "offset_mm": adjustment.offset_mm,
                    "transition_mm": adjustment.transition_mm,
                    "region_sha256": file_hash(copied),
                }
            )

        errors = [
            _verify_solid_reload(stage / "master.obj", solid, heights, base_mm, dx, dy),
            _verify_solid_reload(stage / "master.stl", solid, heights, base_mm, dx, dy),
        ]
        if parameters.height_mode is HeightMode.REFERENCE_RATIO and profile is not None:
            height_resolution: dict[str, Any] = {
                "source": "reference_ratio",
                "profile_id": profile.profile_id,
                "effective_relief_mm": profile.effective_relief_mm,
                "reference_width_mm": profile.reference_width_mm,
                "width_mm": width_mm,
                "formula": "effective_relief_mm / reference_width_mm × width_mm",
                "resolved_depth_mm": report["resolved_depth_mm"],
            }
        else:
            height_resolution = {"source": "explicit_depth", "depth_mm": parameters.depth_mm}

        clamp = report["clamp"]
        warnings = []
        if clamp.get("clamped_points") or clamp.get("clamped_below_points"):
            warnings.append("限幅改变了局部调整结果，详见 clamp_report（不静默截断）")
        if parameters.detail_strength != 0.0:
            warnings.append("detail_strength 非 0，但细节增强属 P3 未实现，数值仅记录不生效")
        # P2 复验 R3：实测坡度超 45° 目标与起伏超产品建议上限都必须落 manifest
        # 警告（可审计），GUI 另有醒目展示——建议带宽公式不含输入深度断层。
        exceeded = slope_exceedances(report.get("slope") or {})
        if exceeded:
            warnings.append(
                f"坡度超限：{'、'.join(exceeded)} 超过 45° 目标"
                "（通常由输入深度固有断层主导；建议加平滑半径或降低起伏，加宽带宽无效）"
            )
        resolved_depth = float(report["resolved_depth_mm"])
        if resolved_depth > RECOMMENDED_MAX_RELIEF_MM:
            warnings.append(
                f"起伏 {resolved_depth:.2f} mm 超过建议上限 {RECOMMENDED_MAX_RELIEF_MM:.1f} mm"
                "（60 mm 级皮雕挂件工程启发值；建议改显式深度降低起伏或收窄宽度，"
                "而不是加宽裙边）"
            )
        return {
            "schema_version": 2,
            "algorithm": MASTER_ALGORITHM,
            "units": "mm",
            "width_mm": width_mm,
            "height_mm": height_mm,
            "dx_mm": dx,
            "dy_mm": dy,
            "grid": report["grid"],
            "parameters": {
                "width_mm": parameters.width_mm,
                "depth_mm": parameters.depth_mm,
                "height_mode": parameters.height_mode.value,
                "profile_id": parameters.profile_id,
                "smoothing_radius_mm": parameters.smoothing_radius_mm,
                "detail_strength": parameters.detail_strength,
                "base_thickness_mm": parameters.base_thickness_mm,
                "falloff_band_mm": parameters.falloff_band_mm,
            },
            "height_resolution": height_resolution,
            "smoothing": report.get("smoothing"),
            "falloff": report.get("falloff"),
            "slope": report.get("slope"),
            "adjustments": adjustment_records,
            "relief": {
                "datum_z_mm": 0.0,
                "front_relief_mm": float(heights.max()),
                "solid_thickness_mm": float(base_mm + heights.max()),
                "base_thickness_mm": base_mm,
            },
            "geometry_checks": {
                "obj_watertight": True,
                "stl_watertight": True,
                "volume_mm3": float(solid.volume),
                "bounds_mm": [0.0, width_mm, 0.0, height_mm, 0.0, float(base_mm + heights.max())],
                "top_surface_max_error_mm": max(errors),
            },
            "clamp_report": clamp,
            "warnings": warnings,
        }
