"""Read actual meshes and ray-sample the +Z envelope. No photo reconstruction is claimed."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pyvista as pv
import trimesh
from vtkmodules.vtkCommonCore import mutable
from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator

from pet_leather_studio.algorithms.mold_solids import mold_pair
from pet_leather_studio.domain.molds import MoldParameters
from pet_leather_studio.infrastructure.revisions import file_hash


class MeshGeometry:
    def import_master(self, source: Path, destination: Path):
        if source.suffix.lower() not in (".obj", ".stl", ".ply"):
            raise ValueError("只支持 OBJ/STL/PLY 几何")
        copied = destination / ("source" + source.suffix.lower())
        shutil.copyfile(source, copied)
        mesh = pv.read(copied).extract_surface(algorithm="dataset_surface").triangulate()
        if not mesh.n_cells or not np.isfinite(mesh.points).all():
            raise ValueError("空网格或无效坐标")
        mesh.clear_data()  # no RGB/texture may masquerade as geometric detail
        mesh.save(destination / "master.vtp")
        preview = mesh.clean(tolerance=0.0)
        if mesh.n_cells > 150_000:
            preview = preview.decimate(1 - 150_000 / mesh.n_cells)
        preview.save(destination / "preview.vtp")
        return {
            "algorithm": "imported-geometry-v2",
            "source_name": source.name,
            "source_hash": file_hash(copied),
            "source_unit": "unconfirmed",
            "points": mesh.n_points,
            "triangles": mesh.n_cells,
            "bounds_source_units": list(mesh.bounds),
            "preview_only_lod": True,
            "photo_reconstruction": False,
        }

    def generate(self, source: Path, destination: Path, parameters: MoldParameters):
        parameters.validate()
        mesh = pv.read(source)
        x0, x1, y0, y1, z0, z1 = mesh.bounds
        if x1 <= x0 or y1 <= y0:
            raise ValueError("XY 投影无有效面积，请先确认母版朝向")
        width = parameters.width_mm
        height = width * (y1 - y0) / (x1 - x0)
        n = parameters.grid_size
        nx = max(2, round(n * width / max(width, height)))
        ny = max(2, round(n * height / max(width, height)))
        locator = vtkStaticCellLocator()
        locator.SetDataSet(mesh)
        locator.BuildLocator()
        hit = np.full((ny, nx), np.nan)
        margin = max(x1 - x0, y1 - y0, z1 - z0, 1.0)
        t, sub_id, cell_id = mutable(0.0), mutable(0), mutable(0)
        position, pcoords = [0.0] * 3, [0.0] * 3
        for j, y in enumerate(np.linspace(y0, y1, ny)):
            for i, x in enumerate(np.linspace(x0, x1, nx)):
                found = locator.IntersectWithLine(
                    (x, y, z1 + margin),
                    (x, y, z0 - margin),
                    margin * 1e-8,
                    t,
                    position,
                    pcoords,
                    sub_id,
                    cell_id,
                )
                if found:
                    hit[j, i] = position[2]
        mask = np.isfinite(hit)
        if mask.mean() < 0.1:
            raise ValueError("+Z 覆盖不足 10%，请检查模型朝向与主体")
        low, high = float(hit[mask].min()), float(hit[mask].max())
        if high - low <= margin * 1e-9:
            h = np.zeros_like(hit)
        else:
            h = (np.nan_to_num(hit, nan=low) - low) / (high - low) * parameters.depth_mm
        dx, dy = width / (nx - 1), height / (ny - 1)
        sufficient = max(dx, dy) <= parameters.feature_mm / 4
        np.savez_compressed(destination / "heightfield.npz", height_mm=h, coverage=mask)
        male, female = mold_pair(h, width, height, parameters.gap_mm, parameters.backing_mm)
        for name, solid in (("male", male), ("female", female)):
            path = destination / f"{name}.stl"
            solid.export(path)
            verified = trimesh.load_mesh(path, process=True)
            if not verified.is_watertight or verified.volume <= 0:
                raise ValueError(f"{name} STL 重新读入检查失败")
        return {
            "algorithm": "z-envelope-mold-candidate-v1",
            "units": "mm",
            "height_mm": height,
            "nx": nx,
            "ny": ny,
            "dx_mm": dx,
            "dy_mm": dy,
            "coverage": float(mask.mean()),
            "sampling_sufficient": sufficient,
            "manufacturing_validated": False,
            "undercut_checked": False,
            "geometry_status": "candidate_only",
            "mold_gap_type": "axial_z",
            "warnings": [
                "仅 +Z 上表面；背面/倒扣未保留、未验证",
                "缺采样区补齐为矩形平背景",
                "无定位销、无材料/承载/压制验证；不是生产合格模具",
                "Z 起伏按指定深度映射，可能改变原模型比例",
            ]
            + ([] if sufficient else ["采样不足以保留指定最小特征，仅低精度候选"]),
        }
