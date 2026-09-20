"""Pillow 解码、EXIF 方向归一化、蒙版校验、阈值初稿与坐标映射；无网络无 UI。"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from pet_leather_studio.domain.photo_relief import MaskMethod
from pet_leather_studio.infrastructure.revisions import file_hash

SUPPORTED_SUFFIXES = (".jpg", ".jpeg", ".png")
RECOMMENDED_LONG_EDGE_PX = 800
MASK_BINARY_THRESHOLD = 127


class PhotoIO:
    def prepare_import(self, source: Path, stage: Path) -> dict[str, Any]:
        """复制源文件（只读）、生成 EXIF 归一化工作图；原图永不被修改。"""
        suffix = source.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(
                f"只支持 {'/'.join(SUPPORTED_SUFFIXES)} 照片输入，收到 {suffix or '(无后缀)'}"
            )
        if not source.is_file():
            raise ValueError(f"照片文件不存在：{source}")
        original = stage / f"original{suffix}"
        shutil.copyfile(source, original)
        try:
            with Image.open(original) as probe:
                probe.verify()
            with Image.open(original) as image:
                width_px, height_px = image.size
                orientation = int(image.getexif().get(274, 1) or 1)
                work = ImageOps.exif_transpose(image).convert("RGB")
            work.save(stage / "work.png")
        except Exception as exc:
            raise ValueError(f"无法解码照片（{original.name}）：{exc}") from exc
        original.chmod(0o444)
        warnings: list[str] = []
        if max(width_px, height_px) < RECOMMENDED_LONG_EDGE_PX:
            warnings.append(
                f"输入分辨率 {width_px}×{height_px}px 低于建议 {RECOMMENDED_LONG_EDGE_PX}px；"
                "放大不会增加原始细节，精细验收需更高清原图"
            )
        return {
            "schema_version": 2,
            "source_name": source.name,
            "source_hash": file_hash(original),
            "source_bytes": original.stat().st_size,
            "format": suffix,
            "width_px": width_px,
            "height_px": height_px,
            "work_width_px": work.width,
            "work_height_px": work.height,
            "exif_orientation": orientation,
            "coordinate_transform": "exif_transpose" if orientation != 1 else "none",
            "warnings": warnings,
        }

    def prepare_mask(
        self,
        stage: Path,
        mask_png: Path,
        photo_metadata: Mapping[str, Any],
        method: MaskMethod,
        threshold_level: int | None,
        notes: str | None,
    ) -> dict[str, Any]:
        """校验并保存蒙版；尺寸必须与照片工作图一致，空蒙版拒绝。"""
        expected = (int(photo_metadata["work_width_px"]), int(photo_metadata["work_height_px"]))
        with Image.open(mask_png) as image:
            if image.mode != "L":
                raise ValueError(f"蒙版必须是单通道 8bit 灰度（L），收到 {image.mode}")
            if image.size != expected:
                raise ValueError(
                    f"蒙版尺寸 {image.size[0]}×{image.size[1]} 与照片工作尺寸 "
                    f"{expected[0]}×{expected[1]} 不一致"
                )
            arr = np.asarray(image, dtype=np.uint8).copy()
        coverage = float((arr > MASK_BINARY_THRESHOLD).mean())
        if coverage <= 0.0:
            raise ValueError("空蒙版：没有任何主体像素")
        warnings: list[str] = []
        if coverage >= 0.999:
            warnings.append("蒙版几乎覆盖整幅图像，可能包含大量背景")
        Image.fromarray(arr, mode="L").save(stage / "mask.png")
        metadata: dict[str, Any] = {
            "schema_version": 2,
            "mask_method": method.value,
            "coverage": coverage,
            "width_px": expected[0],
            "height_px": expected[1],
            "binary_threshold": MASK_BINARY_THRESHOLD,
            "warnings": warnings,
        }
        if threshold_level is not None:
            metadata["threshold_level"] = int(threshold_level)
        if notes:
            metadata["notes"] = str(notes)
        return metadata


def threshold_draft(work_png: Path, level: int) -> np.ndarray:
    """亮度阈值蒙版初稿（假设浅色背景、深色主体）。

    仅是初稿：白毛白底会失效，必须允许人工修正；不得标记为 AI 分割。
    """
    if not 0 <= level <= 255:
        raise ValueError("阈值必须在 0–255 范围")
    luminance = np.asarray(Image.open(work_png).convert("L"))
    return np.where(luminance < level, np.uint8(255), np.uint8(0))


class CoordinateMapper:
    """视图坐标 ↔ 工作图像素（纯数学，无 Qt 依赖；供蒙版画笔与独立测试共用）。"""

    def __init__(
        self, image_size: tuple[int, int], scale: float, offset: tuple[float, float]
    ) -> None:
        if scale <= 0:
            raise ValueError("缩放必须为正")
        self.image_width, self.image_height = image_size
        self.scale = float(scale)
        self.offset_x, self.offset_y = float(offset[0]), float(offset[1])

    def widget_to_image(self, x: float, y: float) -> tuple[int, int]:
        ix = int((x - self.offset_x) / self.scale)
        iy = int((y - self.offset_y) / self.scale)
        return (
            min(max(ix, 0), self.image_width - 1),
            min(max(iy, 0), self.image_height - 1),
        )

    def image_to_widget(self, ix: int, iy: int) -> tuple[float, float]:
        return (ix * self.scale + self.offset_x, iy * self.scale + self.offset_y)


class MaskBuffer:
    """画笔撤销/重做栈（快照式）：撤销后保证逐像素完全恢复。"""

    def __init__(self, mask: np.ndarray, limit: int = 64) -> None:
        self._mask = np.array(mask, dtype=np.uint8)
        self._undo: list[np.ndarray] = []
        self._redo: list[np.ndarray] = []
        self._limit = limit
        self.edits = 0

    @property
    def mask(self) -> np.ndarray:
        return self._mask

    def snapshot(self) -> None:
        """一次操作（笔画/初稿/清空）开始前调用。"""
        self._undo.append(self._mask.copy())
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()
        self.edits += 1

    def paint_disk(self, ix: int, iy: int, radius: int, value: int) -> None:
        if radius < 0:
            raise ValueError("画笔半径不能为负")
        height, width = self._mask.shape
        x0, x1 = max(0, ix - radius), min(width, ix + radius + 1)
        y0, y1 = max(0, iy - radius), min(height, iy + radius + 1)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disk = (xx - ix) ** 2 + (yy - iy) ** 2 <= radius * radius
        self._mask[y0:y1, x0:x1][disk] = value

    def set_mask(self, arr: np.ndarray) -> None:
        if arr.shape != self._mask.shape:
            raise ValueError("替换蒙版形状不一致")
        self.snapshot()
        self._mask = np.array(arr, dtype=np.uint8)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._mask.copy())
        self._mask = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._mask.copy())
        self._mask = self._redo.pop()
        return True
