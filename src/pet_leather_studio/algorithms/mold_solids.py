"""Closed rectangular solids between two sampled surfaces; millimetres, right-handed XYZ."""

from __future__ import annotations

import numpy as np
import trimesh


def solid_between(lower, upper, width_mm: float, height_mm: float):
    """Build one closed solid; lower/upper have shape (ny,nx), increasing Y by row."""
    lower, upper = np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
    if lower.shape != upper.shape or lower.ndim != 2 or min(lower.shape) < 2:
        raise ValueError("曲面网格尺寸不匹配")
    if not np.isfinite(lower).all() or not np.isfinite(upper).all():
        raise ValueError("曲面包含非有限值")
    if np.any(upper <= lower) or width_mm <= 0 or height_mm <= 0:
        raise ValueError("实体必须有正厚度与宽高")
    ny, nx = lower.shape
    xx, yy = np.meshgrid(np.linspace(0, width_mm, nx), np.linspace(0, height_mm, ny))
    count = nx * ny
    points = np.vstack(
        [
            np.column_stack([xx.ravel(), yy.ravel(), lower.ravel()]),
            np.column_stack([xx.ravel(), yy.ravel(), upper.ravel()]),
        ]
    )
    a = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)).ravel()
    b, c, d = a + 1, a + nx + 1, a + nx
    top = np.vstack([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    faces = [top[:, ::-1], top + count]
    boundary = np.concatenate(
        [
            np.arange(nx),
            np.arange(2 * nx - 1, count, nx),
            np.arange(count - 2, count - nx - 1, -1),
            np.arange(count - 2 * nx, 0, -nx),
        ]
    )
    following = np.roll(boundary, -1)
    faces.extend(
        [
            np.column_stack([boundary, following, following + count]),
            np.column_stack([boundary, following + count, boundary + count]),
        ]
    )
    mesh = trimesh.Trimesh(points, np.vstack(faces), process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
        raise ValueError("生成实体未通过封闭/法向/体积检查")
    return mesh


def mold_pair(heightfield, width_mm: float, height_mm: float, gap_mm: float, backing_mm: float):
    """Return convex and concave candidates in the SAME assembly frame."""
    h = np.asarray(heightfield, dtype=float)
    if not np.isfinite(h).all() or h.min() < 0 or gap_mm <= 0 or backing_mm <= 0:
        raise ValueError("高度、间隙、背板参数无效")
    lower_contact = h + backing_mm
    upper_contact = lower_contact + gap_mm
    male = solid_between(np.zeros_like(h), lower_contact, width_mm, height_mm)
    female = solid_between(
        upper_contact, np.full_like(h, h.max() + 2 * backing_mm + gap_mm), width_mm, height_mm
    )
    return male, female
