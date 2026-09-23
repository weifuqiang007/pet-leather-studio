"""人工蒙版编辑：叠加显示、缩放、画笔添加/擦除、撤销/重做、阈值初稿。

坐标换算统一走 infrastructure.photo_io.CoordinateMapper（纯数学，独立单测）；
阈值初稿假设浅色背景，白毛白底需人工修正，保存时如实记录蒙版方式。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pet_leather_studio.domain.photo_relief import MaskMethod
from pet_leather_studio.infrastructure.photo_io import CoordinateMapper, MaskBuffer

MASK_ON = 255
MASK_OFF = 0


class MaskCanvas(QWidget):
    """缩放显示底图 + 半透明蒙版叠加；画笔经 CoordinateMapper 映射到工作像素。"""

    def __init__(self, base_rgb: np.ndarray, mask: np.ndarray, parent: QWidget | None) -> None:
        super().__init__(parent)
        height, width = base_rgb.shape[:2]
        self._base = QImage(
            np.ascontiguousarray(base_rgb).data, width, height, width * 3, QImage.Format_RGB888
        ).copy()
        self.buffer = MaskBuffer(mask)
        self.brush_radius = 8
        self.brush_value = MASK_ON
        self.pan_mode = False
        self.manual_painted = False  # 画笔手工修改标记（阈值初稿不算手工）
        self._scale = 1.0
        self._offset = (0.0, 0.0)
        self._pan_origin: tuple[float, float] | None = None
        self._pan_start_offset: tuple[float, float] | None = None
        self._overlay = self._build_overlay()
        self.setMouseTracking(True)
        self.setMinimumSize(420, 420)

    @property
    def image_size(self) -> tuple[int, int]:
        return (self._base.width(), self._base.height())

    def mapper(self) -> CoordinateMapper:
        return CoordinateMapper(self.image_size, self._scale, self._offset)

    def scale(self) -> float:
        return self._scale

    def _fit(self) -> None:
        margin = 16.0
        fit = min(
            (self.width() - 2 * margin) / max(1, self._base.width()),
            (self.height() - 2 * margin) / max(1, self._base.height()),
            40.0,
        )
        self._scale = max(0.05, fit)
        shown_w = self._base.width() * self._scale
        shown_h = self._base.height() * self._scale
        self._offset = (
            (self.width() - shown_w) / 2.0,
            (self.height() - shown_h) / 2.0,
        )

    def resizeEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        self._fit()
        super().resizeEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        factor = 1.12 if event.angleDelta().y() > 0 else 1.0 / 1.12
        new_scale = float(np.clip(self._scale * factor, 0.05, 20.0))
        anchor = (event.position().x(), event.position().y())
        image_point = self.mapper().widget_to_image(*anchor)
        self._scale = new_scale
        widget_point = self.mapper().image_to_widget(*image_point)
        self._offset = (
            self._offset[0] + anchor[0] - widget_point[0],
            self._offset[1] + anchor[1] - widget_point[1],
        )
        self.update()

    def reset_view(self) -> None:
        """恢复适应窗口的缩放与位置，便于从局部编辑回到全图。"""

        self._fit()
        self.update()

    def pan_by(self, delta_x: float, delta_y: float) -> None:
        """平移图像本身；画布控件的位置和大小保持不变。"""

        self._offset = (self._offset[0] + delta_x, self._offset[1] + delta_y)
        self.update()

    def _build_overlay(self) -> QImage:
        mask = self.buffer.mask
        height, width = mask.shape
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        selected = mask > 127
        rgba[selected] = (255, 70, 70, 110)
        return QImage(
            np.ascontiguousarray(rgba).data, width, height, width * 4, QImage.Format_RGBA8888
        ).copy()

    def update_overlay(self) -> None:
        self._overlay = self._build_overlay()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        painter = QPainter(self)
        shown_w = self._base.width() * self._scale
        shown_h = self._base.height() * self._scale
        painter.drawImage(
            int(self._offset[0]),
            int(self._offset[1]),
            self._base,
            0,
            0,
            int(shown_w),
            int(shown_h),
        )
        painter.drawImage(
            int(self._offset[0]),
            int(self._offset[1]),
            self._overlay,
            0,
            0,
            int(shown_w),
            int(shown_h),
        )
        painter.end()

    def _paint_at(self, x: float, y: float) -> None:
        ix, iy = self.mapper().widget_to_image(x, y)
        self.buffer.paint_disk(ix, iy, self.brush_radius, self.brush_value)
        self.manual_painted = True
        self.update_overlay()

    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        should_pan = event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self.pan_mode
        )
        if should_pan:
            self._pan_origin = (event.position().x(), event.position().y())
            self._pan_start_offset = self._offset
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.buffer.snapshot()
            self._paint_at(event.position().x(), event.position().y())
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        if self._pan_origin is not None and self._pan_start_offset is not None:
            self._offset = (
                self._pan_start_offset[0] + event.position().x() - self._pan_origin[0],
                self._pan_start_offset[1] + event.position().y() - self._pan_origin[1],
            )
            self.update()
            event.accept()
        elif event.buttons() & Qt.MouseButton.LeftButton and not self.pan_mode:
            self._paint_at(event.position().x(), event.position().y())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        if self._pan_origin is not None:
            self._pan_origin = None
            self._pan_start_offset = None
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def apply_array(self, arr: np.ndarray) -> None:
        self.buffer.set_mask(arr)
        self.update_overlay()


class MaskEditorDialog(QDialog):
    """返回人工编辑结果；保存时不做任何自动分割伪装。"""

    def __init__(
        self,
        work_png: Path,
        initial_mask: np.ndarray | None = None,
        initial_from_alpha: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("人工蒙版编辑（画笔添加/擦除 · 撤销/重做 · 滚轮缩放）")
        self.resize(860, 640)
        mask0 = (
            np.array(initial_mask, dtype=np.uint8)
            if initial_mask is not None
            else np.zeros(np.asarray(Image.open(work_png)).shape[:2], dtype=np.uint8)
        )
        base = np.asarray(Image.open(work_png).convert("RGB"))
        if initial_from_alpha:
            base = self._with_checkerboard_background(base, mask0)
        self._base = base
        self.canvas = MaskCanvas(base, mask0, None)
        self.init_threshold_level: int | None = None
        self.initial_from_alpha = initial_from_alpha

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        controls = QHBoxLayout()
        layout.addLayout(controls)

        radius_row = QFormLayout()
        self.radius = QSpinBox()
        self.radius.setRange(1, 64)
        self.radius.setValue(max(4, min(16, min(base.shape[:2]) // 12)))
        self.radius.valueChanged.connect(self._sync_brush)
        radius_row.addRow("画笔半径（工作像素）", self.radius)
        controls.addLayout(radius_row)

        self.add_mode = QRadioButton("添加")
        self.erase_mode = QRadioButton("擦除")
        self.add_mode.setChecked(True)
        self.add_mode.toggled.connect(self._sync_brush)
        self.pan_mode = QRadioButton("拖动画面")
        self.pan_mode.toggled.connect(self._sync_brush)
        controls.addWidget(self.add_mode)
        controls.addWidget(self.erase_mode)
        controls.addWidget(self.pan_mode)

        navigation = QFormLayout()
        navigation.addRow(
            "移动图片",
            self._navigation_buttons(),
        )
        controls.addLayout(navigation)

        for label, handler in (
            ("撤销", self._undo),
            ("重做", self._redo),
            ("清空", self._clear),
            ("适应窗口", self.canvas.reset_view),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)

        threshold_row = QFormLayout()
        self.threshold_level = QSpinBox()
        self.threshold_level.setRange(0, 255)
        self.threshold_level.setValue(128)
        threshold_row.addRow("阈值初稿（浅背景假设）", self.threshold_level)
        draft_button = QPushButton("生成阈值初稿")
        draft_button.clicked.connect(self._threshold_draft)
        threshold_row.addRow(draft_button)
        controls.addLayout(threshold_row)

        controls.addStretch(1)
        save = QPushButton("保存蒙版")
        save.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        controls.addWidget(save)
        controls.addWidget(cancel)

        self.status = QLabel()
        layout.addWidget(self.status)
        self._sync_brush()
        self._refresh_status()

    def _navigation_buttons(self) -> QWidget:
        """为触控板用户提供确定的平移入口，方向表示图片移动方向。"""

        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        for label, dx, dy in (("←", -80, 0), ("→", 80, 0), ("↑", 0, -80), ("↓", 0, 80)):
            button = QPushButton(label)
            button.setFixedWidth(28)
            button.clicked.connect(lambda _checked=False, x=dx, y=dy: self.canvas.pan_by(x, y))
            row.addWidget(button)
        return widget

    @staticmethod
    def _with_checkerboard_background(base: np.ndarray, alpha: np.ndarray) -> np.ndarray:
        """Alpha 初稿在编辑器显示为棋盘格，避免透明背景白底吞没水印边缘。"""

        height, width = alpha.shape
        yy, xx = np.indices((height, width))
        checker = np.where(((xx // 24) + (yy // 24)) % 2 == 0, 218, 176).astype(np.uint8)
        result = np.array(base, dtype=np.uint8, copy=True)
        result[alpha <= 127] = checker[alpha <= 127, None]
        return result

    def _sync_brush(self) -> None:
        self.canvas.brush_radius = self.radius.value()
        self.canvas.brush_value = MASK_OFF if self.erase_mode.isChecked() else MASK_ON
        self.canvas.pan_mode = self.pan_mode.isChecked()

    def _refresh_status(self) -> None:
        coverage = float((self.canvas.buffer.mask > 127).mean())
        self.status.setText(
            f"操作次数：{self.canvas.buffer.edits}；主体覆盖率：{coverage:.1%}；"
            + (
                "初稿来自图片透明通道；请检查耳尖、胡须和边缘后保存"
                if self.initial_from_alpha
                else "阈值初稿仅为辅助（浅背景假设），人工修正后按 manual 记录"
            )
            + "；拖动画面模式可左键拖拽，也可随时按住中键拖拽"
            + "；箭头按钮可移动图片；“适应窗口”可恢复全图"
        )

    def _undo(self) -> None:
        self.canvas.buffer.undo()
        self.canvas.update_overlay()
        self._refresh_status()

    def _redo(self) -> None:
        self.canvas.buffer.redo()
        self.canvas.update_overlay()
        self._refresh_status()

    def _clear(self) -> None:
        self.canvas.apply_array(np.zeros(self.canvas.buffer.mask.shape, dtype=np.uint8))
        self._refresh_status()

    def _threshold_draft(self) -> None:
        level = self.threshold_level.value()
        luminance = self._luminance()
        draft = np.where(luminance < level, np.uint8(MASK_ON), np.uint8(MASK_OFF))
        self.canvas.apply_array(draft)
        self.init_threshold_level = level
        self._refresh_status()

    def _luminance(self) -> np.ndarray:
        red, green, blue = (self._base[..., index].astype(np.float64) for index in range(3))
        return 0.299 * red + 0.587 * green + 0.114 * blue

    @property
    def mask(self) -> np.ndarray:
        return self.canvas.buffer.mask.copy()

    @property
    def mask_method(self) -> MaskMethod:
        if not self.canvas.manual_painted and self.init_threshold_level is not None:
            return MaskMethod.THRESHASSISTED
        if not self.canvas.manual_painted and self.initial_from_alpha:
            return MaskMethod.EMBEDDED_ALPHA
        return MaskMethod.MANUAL
