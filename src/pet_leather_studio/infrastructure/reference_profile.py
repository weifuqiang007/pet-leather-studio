"""参考 OBJ 标定（PH05）：有效正面区域内的显式口径测量与标定文件。

不把包围盒 Z 跨度直接等同有效浮雕高度——bbox 数字分开记录、仅作历史
对照；分位数只是选定"有效正面区域/基准"之后的稳健统计，真实极值必须
保留，被百分位裁掉的点（如鼻尖）由 excluded_points() 供界面标出核查。
正面 = 相机正面假设（+Z 朝观察者）；基准 = 区域内最低点平面（v1 口径，
全部以字符串落盘可审计；交互式正面/基准选择延后）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyvista as pv

from pet_leather_studio.domain.errors import ResourceMissingError
from pet_leather_studio.domain.photo_relief import (
    DEFAULT_PERCENTILE,
    ReferenceProfile,
)

MEASUREMENT_ALGORITHM = "reference-profile-v1"
REGION_BASIS_FULL = "full_xy_bounds_v1"
REGION_BASIS_CLI = "cli_override"
DATUM_METHOD_MIN_Z = "min_z_plane"
PROFILE_ID_PREFIX = "ref-"
EXCLUDED_POINTS_LIMIT = 50_000  # 界面 glyph 子采样上限（确定性等距取样）


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_id(
    source_sha256: str, region: tuple[float, float, float, float], percentile: float
) -> str:
    payload = "|".join(
        (source_sha256, ",".join(f"{value:.6f}" for value in region), f"{percentile:.3f}")
    )
    return PROFILE_ID_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _region_of(
    bounds: tuple[float, ...],
    region: tuple[float, float, float, float] | None,
) -> tuple[tuple[float, float, float, float], str]:
    if region is None:
        return (bounds[0], bounds[1], bounds[2], bounds[3]), REGION_BASIS_FULL
    xmin, xmax, ymin, ymax = region
    if not np.all(np.isfinite(region)) or not xmin < xmax or not ymin < ymax:
        raise ValueError("region 必须满足 xmin<xmax 且 ymin<ymax（有限值）")
    return region, REGION_BASIS_CLI


def measure_reference(
    obj_path: Path,
    percentile: float = DEFAULT_PERCENTILE,
    region: tuple[float, float, float, float] | None = None,
    source_units: str = "assumed_mm",
) -> ReferenceProfile:
    """测量参考 OBJ 并返回标定结果（不落盘；由 ReferenceProfileStore.save 持久化）。"""
    if not obj_path.is_file():
        raise ResourceMissingError(f"参考 OBJ 不存在：{obj_path}")
    if not 0.0 < percentile <= 100.0:
        raise ValueError("percentile 必须在 (0, 100] 范围")
    mesh = pv.read(obj_path)
    points = np.asarray(mesh.points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 3 or len(points) == 0:
        raise ValueError("参考 OBJ 无可用顶点")
    if not np.isfinite(points).all():
        raise ValueError("参考 OBJ 含非有限坐标")
    bounds = mesh.bounds
    chosen_region, region_basis = _region_of(bounds, region)
    xmin, xmax, ymin, ymax = chosen_region
    inside = (
        (points[:, 0] >= xmin)
        & (points[:, 0] <= xmax)
        & (points[:, 1] >= ymin)
        & (points[:, 1] <= ymax)
    )
    if not inside.any():
        raise ValueError("指定区域内没有顶点，请检查 region")
    z_inside = points[inside, 2]
    datum_z = float(z_inside.min())
    z_cut = float(np.percentile(z_inside, percentile))
    effective_relief = z_cut - datum_z
    if effective_relief <= 0.0:
        raise ValueError("区域内分位裁剪后起伏为零，无法建立参考比例")
    excluded = z_inside > z_cut
    bbox_x_span = max(bounds[1] - bounds[0], 1e-12)
    source_sha256 = _sha256_file(obj_path)
    return ReferenceProfile(
        profile_id=_profile_id(source_sha256, chosen_region, percentile),
        source_name=obj_path.name,
        source_path=str(obj_path.resolve()),
        source_sha256=source_sha256,
        source_units=source_units,
        region=chosen_region,
        region_basis=region_basis,
        datum_method=DATUM_METHOD_MIN_Z,
        datum_z=datum_z,
        percentile=float(percentile),
        exclusion_fraction=float(excluded.mean()),
        effective_relief_mm=float(effective_relief),
        reference_width_mm=float(xmax - xmin),
        true_min_z=float(points[:, 2].min()),
        true_max_z=float(points[:, 2].max()),
        true_excess_mm=float(max(points[:, 2].max() - z_cut, 0.0)),
        excluded_point_count=int(excluded.sum()),
        bbox_z_span=float(bounds[5] - bounds[4]),
        bbox_z_span_ratio=float((bounds[5] - bounds[4]) / bbox_x_span),
        measurement_algorithm=MEASUREMENT_ALGORITHM,
        created_at=datetime.now(UTC).isoformat(),
    )


def excluded_points(
    obj_path: Path,
    profile: ReferenceProfile,
    verify_hash: bool = True,
    limit: int = EXCLUDED_POINTS_LIMIT,
) -> np.ndarray:
    """区域内 z>z_cut 的子采样点云（界面红色 glyph 核查"鼻尖被裁"）。

    按同口径重算 z_cut；源缺失或内容与标定时不一致（sha256）显式报错，
    不静默降级。子采样为确定性等距取样，可重复。
    """
    if not obj_path.is_file():
        raise ResourceMissingError(f"参考 OBJ 不存在，无法核查排除点：{obj_path}")
    if verify_hash and _sha256_file(obj_path) != profile.source_sha256:
        raise ResourceMissingError(
            f"参考 OBJ 与标定时内容不一致（sha256 不匹配）：{obj_path}；请重新标定"
        )
    points = np.asarray(pv.read(obj_path).points, dtype=np.float64)
    xmin, xmax, ymin, ymax = profile.region
    inside = (
        (points[:, 0] >= xmin)
        & (points[:, 0] <= xmax)
        & (points[:, 1] >= ymin)
        & (points[:, 1] <= ymax)
    )
    z_inside = points[inside, 2]
    z_cut = float(np.percentile(z_inside, profile.percentile))
    excess = points[inside][z_inside > z_cut]
    if len(excess) > limit:
        excess = excess[np.linspace(0, len(excess) - 1, limit).astype(int)]
    return excess


class ReferenceProfileStore:
    """data_root()/profiles/<profile_id>.json 读写与列举（app 级，跨工程复用）。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, profile_id: str) -> Path:
        if (
            not profile_id.strip()
            or "/" in profile_id
            or "\\" in profile_id
            or profile_id.startswith(".")
        ):
            raise ValueError(f"非法 profile_id：{profile_id!r}")
        return self.root / f"{profile_id}.json"

    def save(self, profile: ReferenceProfile) -> Path:
        profile.validate()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(profile.profile_id)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(profile.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)  # 原子替换，避免半写文件被当成有效标定
        return path

    def load(self, profile_id: str) -> ReferenceProfile:
        path = self._path(profile_id)
        if not path.is_file():
            raise ResourceMissingError(
                f"参考标定 {profile_id} 不存在：{path}；请先 calibrate-reference 完成标定"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ResourceMissingError(f"标定文件无法解析：{path}；请重新标定覆盖该文件") from error
        try:
            return ReferenceProfile.from_mapping(data)
        except (KeyError, TypeError, ValueError) as error:
            raise ResourceMissingError(
                f"标定文件字段不完整或非法：{path}；请重新标定覆盖该文件"
            ) from error

    def list_profiles(self) -> list[ReferenceProfile]:
        """列举全部有效标定；单个损坏文件不阻塞列举（load 该 id 时显式报错）。"""
        if not self.root.is_dir():
            return []
        profiles: list[ReferenceProfile] = []
        for path in sorted(self.root.glob(f"{PROFILE_ID_PREFIX}*.json")):
            try:
                profiles.append(self.load(path.stem))
            except ResourceMissingError:
                continue
        return profiles
