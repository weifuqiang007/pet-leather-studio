"""人工蒙版编辑：Photoshop 式布局（左工具栏 · 右大画布）、可见擦除、撤销/重做。

画布（视口）位置固定：拖动/缩放只移动画布内的图片，空余处显示深色工作区，
图片带描边——能明确看出"图片在固定画布内移动"，而不是整个相框被拖走。
擦除可见：保留区红色薄纱、已擦除/未选区深色遮罩，画笔光标为彩色圆环。
坐标换算统一走 infrastructure.photo_io.CoordinateMapper（纯数学，独立单测）；
阈值初稿假设浅色背景，白毛白底需人工修正，保存时如实记录蒙版方式。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
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
MASK_TINT_RGBA = (255, 70, 70, 110)  # 保留区：红色薄纱（半透明，底图可辨）
REMOVED_VEIL_RGBA = (8, 8, 14, 120)  # 已擦除/未选区：深色遮罩（擦除结果立即可见）
WORKSPACE_COLOR = (38, 38, 44)  # 画布工作区底色（固定不动的部分）
BORDER_COLOR = (110, 110, 122)  # 图片描边（随图移动，与固定画布区分）
ADD_CURSOR_COLOR = (255, 96, 96)
ERASE_CURSOR_COLOR = (90, 220, 255)


def overlay_rgba(mask: np.ndarray) -> np.ndarray:
    """蒙版 → 叠加层 RGBA：保留区红色薄纱，其余深色遮罩（擦除可见）。"""

    height, width = mask.shape
    rgba = np.full((height, width, 4), REMOVED_VEIL_RGBA, dtype=np.uint8)
    rgba[mask > 127] = MASK_TINT_RGBA
    return rgba


class MaskCanvas(QWidget):
    """固定视口 + 深色工作区；图片在其中平移/缩放；画笔彩色圆环光标。"""

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
        self._space_pan = False  # 按住空格临时切到拖动（Photoshop 习惯）
        self._hover: tuple[float, float] | None = None
        self._overlay = self._build_overlay()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(560, 520)

    @property
    def image_size(self) -> tuple[int, int]:
        return (self._base.width(), self._base.height())

    def mapper(self) -> CoordinateMapper:
        return CoordinateMapper(self.image_size, self._scale, self._offset)

    def scale(self) -> float:
        return self._scale

    def _fit(self) -> None:
        margin = 24.0
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

    def _build_overlay(self) -> QImage:
        rgba = overlay_rgba(self.buffer.mask)
        height, width = rgba.shape[:2]
        return QImage(
            np.ascontiguousarray(rgba).data, width, height, width * 4, QImage.Format_RGBA8888
        ).copy()

    def update_overlay(self) -> None:
        self._overlay = self._build_overlay()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(*WORKSPACE_COLOR))
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
        # 图片描边：随图移动，与固定画布（工作区底色）一眼可分
        painter.setPen(QPen(QColor(*BORDER_COLOR), 1))
        painter.drawRect(
            int(self._offset[0]),
            int(self._offset[1]),
            int(shown_w),
            int(shown_h),
        )
        self._draw_brush_ring(painter)
        painter.end()

    def _draw_brush_ring(self, painter: QPainter) -> None:
        """画笔模式下的圆环光标：红色=添加，青色=擦除；拖动模式不画。"""

        if self._hover is None or self._effective_pan():
            return
        color = ADD_CURSOR_COLOR if self.brush_value == MASK_ON else ERASE_CURSOR_COLOR
        radius = max(2.0, self.brush_radius * self._scale)
        painter.setPen(QPen(QColor(*color), 1))
        painter.drawEllipse(QPointF(self._hover[0], self._hover[1]), radius, radius)

    def _paint_at(self, x: float, y: float) -> None:
        ix, iy = self.mapper().widget_to_image(x, y)
        self.buffer.paint_disk(ix, iy, self.brush_radius, self.brush_value)
        self.manual_painted = True
        self.update_overlay()

    def _effective_pan(self) -> bool:
        return self.pan_mode or self._space_pan

    def _update_cursor(self) -> None:
        if self._pan_origin is not None:
            return  # 拖拽中保持抓手
        if self._effective_pan():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.BlankCursor)  # 只显示圆环光标

    def keyPressEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        if event.key() == Qt.Key.Key_Space and not self._space_pan:
            self._space_pan = True
            self._update_cursor()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        if event.key() == Qt.Key.Key_Space:
            self._space_pan = False
            self._update_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        should_pan = event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._effective_pan()
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
        self._hover = (event.position().x(), event.position().y())
        if self._pan_origin is not None and self._pan_start_offset is not None:
            self._offset = (
                self._pan_start_offset[0] + event.position().x() - self._pan_origin[0],
                self._pan_start_offset[1] + event.position().y() - self._pan_origin[1],
            )
            self.update()
            event.accept()
        else:
            self.update()  # 刷新圆环光标位置
            if event.buttons() & Qt.MouseButton.LeftButton and not self._effective_pan():
                self._paint_at(event.position().x(), event.position().y())
            else:
                super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        if self._pan_origin is not None:
            self._pan_origin = None
            self._pan_start_offset = None
            self._update_cursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001 - Qt 签名
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def apply_array(self, arr: np.ndarray) -> None:
        self.buffer.set_mask(arr)
        self.update_overlay()


class MaskEditorDialog(QDialog):
    """Photoshop 式布局：左侧工具栏，右侧大画布；返回人工编辑结果。"""

    def __init__(
        self,
        work_png: Path,
        initial_mask: np.ndarray | None = None,
        initial_from_alpha: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("人工蒙版编辑（左侧工具 · 右侧画布；B 添加 / E 擦除 / H 拖动图片）")
        self.resize(1120, 720)
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

        outer = QVBoxLayout(self)
        main = QHBoxLayout()
        main.addWidget(self._tool_panel(), 0)
        main.addWidget(self.canvas, 1)
        outer.addLayout(main, 1)

        self.status = QLabel()
        outer.addWidget(self.status)
        self._sync_brush()
        self._refresh_status()

    def _tool_panel(self) -> QWidget:
        """左侧工具栏（Photoshop 习惯：工具在左，画布在右）。"""

        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(8, 8, 8, 8)

        tools = QGroupBox("工具")
        tools_layout = QVBoxLayout(tools)
        self.add_mode = QRadioButton("画笔添加 (B)")
        self.erase_mode = QRadioButton("擦除 (E)")
        self.pan_mode = QRadioButton("拖动图片 (H / 空格)")
        self.add_mode.setChecked(True)
        self.add_mode.setShortcut(QKeySequence("B"))
        self.erase_mode.setShortcut(QKeySequence("E"))
        self.pan_mode.setShortcut(QKeySequence("H"))
        for mode in (self.add_mode, self.erase_mode, self.pan_mode):
            mode.toggled.connect(self._sync_brush)
            tools_layout.addWidget(mode)
        column.addWidget(tools)

        brush = QGroupBox("画笔")
        brush_form = QFormLayout(brush)
        self.radius = QSpinBox()
        self.radius.setRange(1, 64)
        self.radius.setValue(max(4, min(16, min(self._base.shape[:2]) // 12)))
        self.radius.valueChanged.connect(self._sync_brush)
        brush_form.addRow("半径（工作像素）", self.radius)
        column.addWidget(brush)

        editing = QGroupBox("编辑")
        editing_grid = QHBoxLayout(editing)
        for label, handler in (
            ("撤销", self._undo),
            ("重做", self._redo),
            ("清空", self._clear),
            ("适应窗口", self.canvas.reset_view),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            editing_grid.addWidget(button)
        column.addWidget(editing)

        draft = QGroupBox("阈值初稿（浅背景假设）")
        draft_form = QFormLayout(draft)
        self.threshold_level = QSpinBox()
        self.threshold_level.setRange(0, 255)
        self.threshold_level.setValue(128)
        draft_form.addRow("阈值", self.threshold_level)
        draft_button = QPushButton("生成阈值初稿")
        draft_button.clicked.connect(self._threshold_draft)
        draft_form.addRow(draft_button)
        column.addWidget(draft)

        column.addStretch(1)
        save = QPushButton("保存蒙版")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addWidget(save)
        actions.addWidget(cancel)
        column.addLayout(actions)
        panel.setFixedWidth(230)
        return panel

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
        self.canvas._update_cursor()

    def _refresh_status(self) -> None:
        coverage = float((self.canvas.buffer.mask > 127).mean())
        self.status.setText(
            f"操作次数：{self.canvas.buffer.edits}；主体覆盖率：{coverage:.1%}；"
            + (
                "初稿来自图片透明通道；请检查耳尖、胡须和边缘后保存"
                if self.initial_from_alpha
                else "阈值初稿仅为辅助（浅背景假设），人工修正后按 manual 记录"
            )
            + "；红色薄纱=保留，深色遮罩=已擦除/未选"
            + "；画布固定，拖动/滚轮只移动图片（H 或空格+左键、或中键拖动；滚轮以光标缩放）"
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
