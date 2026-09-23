"""照片母版原生高度场 → 皮革阴阳模修订文件（MOLD-PAIR M1）。

不重新射线采样：直接读母版 heightfield.npz（native 路径，细节逐位保留）。
外部 OBJ/STL/PLY 仍走 MeshGeometry 兼容路径（legacy candidate，不在此实现）。
发布前验证：双实体重读水密/体积/边界/逐列上下表面（≤1e-4 mm）、
双向独立最近距离（细分采样 + 精确点到三角面 + 半径证书）≥ t_effective − 容差
（guard 自动加密重算，超出档位拒绝发布）、
Z 向间隙处处为正；任一失败抛错，由应用层丢弃 staging。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
import trimesh

from pet_leather_studio.algorithms.leather_mold_pair import (
    bidirectional_min_distance,
    distance_tolerance_mm,
    expand_heightfield,
    grid_surface_trimesh,
    normal_clearance_field,
    one_sided_slope,
    spherical_envelope,
)
from pet_leather_studio.algorithms.mold_solids import solid_between
from pet_leather_studio.algorithms.relief_height import background_clearance_mm
from pet_leather_studio.domain.leather_molds import (
    EXTERNAL_JIG_NOTE,
    MOLD_ALGORITHM,
    LeatherMoldParameters,
    effective_thickness_mm,
)
from pet_leather_studio.infrastructure.revisions import file_hash

GEOM_TOL_MM = 1e-4  # 重读边界/逐列表面误差门（与照片母版同口径）
GUARD_STEPS = (0.0, 1.0, 2.0)  # 离散 guard = step × distance_tolerance_mm，逐级重算
FLAT_STOP_EPS_MM = 1e-9  # 判定"纯平止口"的高度容差（构造上背景恒 0）


def _polydata_from_trimesh(mesh: trimesh.Trimesh) -> pv.PolyData:
    faces = np.asarray(mesh.faces, dtype=np.int64)
    flat = np.column_stack([np.full(len(faces), 3), faces]).ravel()
    return pv.PolyData(np.asarray(mesh.vertices, dtype=np.float64), flat)


def _surface_polydata(z_mm: np.ndarray, width_mm: float, height_mm: float) -> pv.PolyData:
    return _polydata_from_trimesh(grid_surface_trimesh(z_mm, width_mm, height_mm))


def _valid_padded(valid: np.ndarray, expansion: Mapping[str, Any], ny: int, nx: int) -> np.ndarray:
    """有效主体蒙版平移到扩边后网格（核心范围对位；未扩边即原样）。"""

    if not expansion.get("expanded"):
        return valid
    result = np.zeros((ny, nx), dtype=bool)
    rows, cols = expansion["core_rows"], expansion["core_cols"]
    result[rows[0] : rows[1], cols[0] : cols[1]] = valid
    return result


def _verify_solid_reload(
    path: Path,
    solid: trimesh.Trimesh,
    lower_mm: np.ndarray,
    upper_mm: np.ndarray,
    width_mm: float,
    height_mm: float,
) -> float:
    """重读导出网格并校验：水密、正体积、边界、逐列下/上表面；返回最大误差 mm。"""

    reloaded = trimesh.load_mesh(path, process=True)
    if not reloaded.is_watertight:
        raise ValueError(f"{path.name} 重新读入不是水密实体")
    if reloaded.volume <= 0 or abs(reloaded.volume - solid.volume) > solid.volume * 5e-6 + 1e-9:
        raise ValueError(
            f"{path.name} 体积校验失败（重读 {reloaded.volume} vs 导出 {solid.volume}）"
        )
    ny, nx = lower_mm.shape
    expected = np.array(
        [
            [0.0, 0.0, float(lower_mm.min())],
            [width_mm, height_mm, float(upper_mm.max())],
        ]
    )
    if np.abs(np.asarray(reloaded.bounds) - expected).max() > GEOM_TOL_MM:
        raise ValueError(f"{path.name} 边界与预期不符：{list(reloaded.bounds)}")

    raw = trimesh.load_mesh(path, process=False)
    vertices = np.asarray(raw.vertices, dtype=np.float64).reshape(-1, 3)
    dx, dy = width_mm / (nx - 1), height_mm / (ny - 1)
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
    bottoms = np.full((ny, nx), np.inf)
    tops = np.full((ny, nx), -np.inf)
    np.minimum.at(bottoms, (indices_j[on_grid], indices_i[on_grid]), vertices[on_grid, 2])
    np.maximum.at(tops, (indices_j[on_grid], indices_i[on_grid]), vertices[on_grid, 2])
    if not np.isfinite(bottoms).all() or not np.isfinite(tops).all():
        raise ValueError(f"{path.name} 存在采样列缺失顶点")
    error = float(max(np.abs(bottoms - lower_mm).max(), np.abs(tops - upper_mm).max()))
    if error > GEOM_TOL_MM:
        raise ValueError(f"{path.name} 表面误差 {error:.3e} mm 超过 {GEOM_TOL_MM} mm")
    return error


def _readme_text(parameters: LeatherMoldParameters, metadata: dict[str, Any]) -> str:
    expansion = metadata["expansion"]
    expansion_note = (
        f"（已扩边：过渡 {expansion['transition_mm']:.1f} mm + 纯平止口）"
        if expansion.get("expanded")
        else ""
    )
    return "\n".join(
        [
            f"皮革压制阴阳模候选 · 源母版 {str(metadata['master_revision_id'])[:8]}",
            f"算法 {MOLD_ALGORITHM}；单位 mm；manufacturing_validated=false（实物未验证）",
            f"参数：{parameters.to_dict()}",
            f"有效皮厚 t_eff = {metadata['target_effective_thickness_mm']:.3f} mm；"
            f"独立实测最小距离 {metadata['clearance_independent']['min_mm']:.3f} mm"
            f"（点到三角面双向，容差 {metadata['distance_tolerance_mm']:.3f} mm，"
            f"采样界 {metadata['clearance_independent']['sampling_bound_mm']:.3f} mm）",
            f"版面：{metadata['plate']['final_width_mm']:.1f} × "
            f"{metadata['plate']['final_height_mm']:.1f} mm{expansion_note}",
            f"几何校验：{metadata['geometry_checks']}",
            "文件：male.obj/.stl/.vtp、female.obj/.stl/.vtp、mold_pair.npz、"
            "assembly_preview.vtp、manifest.json",
            f"警告：{metadata['warnings']}",
            EXTERNAL_JIG_NOTE,
            "试压前须知：润湿植鞣革需记录批次/厚度/闭模量/保压/结果；"
            "几何配对不等于压制工艺已验证。",
        ]
    )


class LeatherMoldGeometry:
    """LeatherMoldGeometryPort 实现：原生高度场 → 配对模具修订文件。"""

    def generate_leather_molds(
        self,
        heightfield_npz: Path,
        master_metadata: Mapping[str, Any],
        parameters: LeatherMoldParameters,
        stage: Path,
    ) -> dict[str, Any]:
        parameters.validate()
        t_effective = effective_thickness_mm(parameters)
        with np.load(heightfield_npz) as data:
            source_heights = np.asarray(data["heights_mm"], dtype=np.float64)
            valid = np.asarray(data["valid"], dtype=bool)
            dx = float(data["dx_mm"])
            dy = float(data["dy_mm"])
            width = float(data["width_mm"])
            height = float(data["height_mm"])
        if not np.isfinite(source_heights).all() or source_heights.min() < 0.0:
            raise ValueError("母版高度场含非有限值或负值，拒绝生成模具")

        # 平坦止口 = 版边余量 − 源母版过渡带宽（贴边 → 0；裙边占用不可忽略，§3.4）
        band_mm = float((master_metadata.get("falloff") or {}).get("band_mm") or 0.0)
        clearance = background_clearance_mm(valid, dx, dy)
        existing_flat = 0.0 if math.isinf(clearance) else max(0.0, clearance - band_mm)
        heights, expansion = expand_heightfield(
            source_heights,
            dx,
            dy,
            existing_flat_mm=existing_flat,
            edge_margin_mm=parameters.edge_margin_mm,
            max_plate_mm=parameters.max_plate_mm,
            plate_width_mm=width,
            plate_height_mm=height,
        )
        ny, nx = heights.shape
        final_width = width + 2 * expansion.get("pad_x_px", 0) * dx
        final_height = height + 2 * expansion.get("pad_y_px", 0) * dy
        male_contact = heights + float(parameters.backing_mm)

        # 球形偏置上包络 + 独立距离验收；离散不足时 guard 逐级加密重算（§3.2）
        tolerance = distance_tolerance_mm(dx, dy)
        female_inner: np.ndarray | None = None
        kernel_report: dict[str, Any] | None = None
        clearance_check: dict[str, Any] | None = None
        for step in GUARD_STEPS:
            guard = step * tolerance
            female_inner, kernel_report = spherical_envelope(
                male_contact, dx, dy, t_effective + guard
            )
            male_surface = grid_surface_trimesh(male_contact, final_width, final_height)
            female_surface = grid_surface_trimesh(female_inner, final_width, final_height)
            clearance_check = bidirectional_min_distance(male_surface, female_surface)
            clearance_check["guard_mm"] = guard
            if clearance_check["min_mm"] >= t_effective - tolerance:
                break
        if female_inner is None or kernel_report is None or clearance_check is None:
            raise ValueError("包络/验收计算未执行（内部错误）")
        if clearance_check["min_mm"] < t_effective - tolerance:
            raise ValueError(
                f"独立最近距离 {clearance_check['min_mm']:.4f} mm < "
                f"t_eff−容差 {t_effective - tolerance:.4f} mm（guard 已试 "
                f"{[step * tolerance for step in GUARD_STEPS]} mm）；拒绝发布"
            )

        axial_gap = female_inner - male_contact
        if float(axial_gap.min()) <= 0.0:
            raise ValueError("Z 向间隙存在非正点，模具相交")
        normal_field = normal_clearance_field(axial_gap, male_contact, dx, dy)
        slope = one_sided_slope(heights, dx, dy)

        male_solid = solid_between(np.zeros_like(heights), male_contact, final_width, final_height)
        female_top = float(female_inner.max()) + float(parameters.backing_mm)
        female_solid = solid_between(
            female_inner, np.full_like(female_inner, female_top), final_width, final_height
        )
        solids = {
            "male": (male_solid, np.zeros_like(heights), male_contact),
            "female": (female_solid, female_inner, np.full_like(female_inner, female_top)),
        }
        errors: dict[str, float] = {}
        for name, (solid, lower, upper) in solids.items():
            solid.export(stage / f"{name}.stl")
            solid.export(stage / f"{name}.obj", digits=8)
            errors[name] = _verify_solid_reload(
                stage / f"{name}.obj", solid, lower, upper, final_width, final_height
            )
            errors[name + "_stl"] = _verify_solid_reload(
                stage / f"{name}.stl", solid, lower, upper, final_width, final_height
            )
        _surface_polydata(male_contact, final_width, final_height).save(stage / "male.vtp")
        _surface_polydata(female_inner, final_width, final_height).save(stage / "female.vtp")
        assembly = pv.merge(
            [
                _polydata_from_trimesh(male_solid),
                _polydata_from_trimesh(female_solid),
            ],
            merge_points=False,
        )
        assembly.save(stage / "assembly_preview.vtp")

        core_rows = expansion.get("core_rows", [0, ny])
        core_cols = expansion.get("core_cols", [0, nx])
        core_slice = (slice(core_rows[0], core_rows[1]), slice(core_cols[0], core_cols[1]))
        np.savez_compressed(
            stage / "mold_pair.npz",
            male_contact_mm=male_contact,
            female_inner_mm=female_inner,
            axial_gap_mm=axial_gap,
            normal_clearance_mm=normal_field,
            target_effective_thickness_mm=t_effective,
            independent_min_distance_mm=clearance_check["min_mm"],
            independent_a_to_b_mm=clearance_check["a_to_b_mm"],
            independent_b_to_a_mm=clearance_check["b_to_a_mm"],
            independent_sampling_bound_mm=clearance_check["sampling_bound_mm"],
            subdivision_order=clearance_check["subdivision_order"],
            distance_method=np.array(clearance_check["method"]),
            independent_stats=np.array(
                [clearance_check["samples_a"], clearance_check["samples_b"]]
            ),
            dx_mm=dx,
            dy_mm=dy,
            width_mm=final_width,
            height_mm=final_height,
            valid_subject=_valid_padded(valid, expansion, ny, nx),
            flat_stop=heights <= FLAT_STOP_EPS_MM,
            core_rows=np.asarray(core_rows),
            core_cols=np.asarray(core_cols),
            schema_version=2,
        )

        warnings = [
            EXTERNAL_JIG_NOTE,
            "几何配对候选，未经实物试压与制造验证（manufacturing_validated=false）",
        ]
        if parameters.sampling_feature_mm < 4.0 * max(dx, dy):
            warnings.append(
                f"源分辨率不足：母版采样间距 max(dx,dy)={max(dx, dy):.3f} mm > "
                f"sampling_feature_mm/4={parameters.sampling_feature_mm / 4:.3f} mm；"
                "native 只保证不降采样，不能凭空获得更小物理细节"
            )
        if float(slope["max_deg"]) > 45.0:
            warnings.append(
                f"阳模接触面单侧最陡 {slope['max_deg']:.1f}°（源母版残余断层继承）；"
                "压制时皮革在陡坡处贴敷性受限，风险自担"
            )

        metadata: dict[str, Any] = {
            "schema_version": 1,
            "algorithm": MOLD_ALGORITHM,
            "units": "mm",
            "master_revision_id": master_metadata.get("id"),
            "heightfield_sha256": file_hash(heightfield_npz),
            "master_falloff_band_mm": band_mm,
            "border_clearance_mm": None if math.isinf(clearance) else float(clearance),
            "existing_flat_stop_mm": existing_flat,
            "expansion": expansion,
            "plate": {
                "source_width_mm": width,
                "source_height_mm": height,
                "final_width_mm": float(final_width),
                "final_height_mm": float(final_height),
                "grid": [int(ny), int(nx)],
                "dx_mm": dx,
                "dy_mm": dy,
            },
            "parameters": parameters.to_dict(),
            "target_effective_thickness_mm": t_effective,
            "distance_tolerance_mm": tolerance,
            "envelope_kernel": kernel_report,
            "clearance_independent": clearance_check,
            "axial_gap_min_mm": float(axial_gap.min()),
            "slope": slope,
            "geometry_checks": {
                "watertight": True,
                "volume_male_mm3": float(male_solid.volume),
                "volume_female_mm3": float(female_solid.volume),
                "surface_max_error_mm": max(errors.values()),
            },
            "manufacturing_validated": False,
            "warnings": warnings,
            "core_bitwise_preserved": bool(np.array_equal(heights[core_slice], source_heights)),
        }
        (stage / "README.txt").write_text(_readme_text(parameters, metadata), encoding="utf-8")
        return metadata
