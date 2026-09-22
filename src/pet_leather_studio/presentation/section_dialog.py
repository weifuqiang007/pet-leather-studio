"""母版侧面截面对话框（P2 复验 R2）：一条可读的顶面高度剖面。

读已发布 heightfield.npz（几何朝向、基准 0、底板另计），取穿过全域最高点
的一行画高度曲线：用户据此判断过渡带过窄（近垂直墙）或过宽（主体被糊开），
配合详情中的坡度统计使用。QPainter 自绘，不引入新绘图依赖。
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

_PLOT_MARGIN_PX = 34
_X_TICK_MM = 5.0


class _SectionCanvas(QWidget):
    """单条剖面曲线：横轴 mm、纵轴高度 mm；有效域与背景分段着色。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(560, 220)
        self._profile: np.ndarray | None = None
        self._valid: np.ndarray | None = None
        self._dx_mm = 1.0

    def set_profile(self, profile_mm: np.ndarray, valid: np.ndarray, dx_mm: float) -> None:
        self._profile = np.asarray(profile_mm, dtype=np.float64).copy()
        self._valid = np.asarray(valid, dtype=bool).copy()
        self._dx_mm = float(dx_mm)
        self.update()

    @property
    def span_mm(self) -> float:
        if self._profile is None or self._profile.size < 2:
            return 0.0
        return float(self._profile.size - 1) * self._dx_mm

    def _map(self, x_mm: float, z_mm: float, z_max: float) -> tuple[float, float]:
        width, height = self.width(), self.height()
        span = max(self.span_mm, 1e-6)
        z_top = max(z_max, 1e-6)
        px = _PLOT_MARGIN_PX + x_mm / span * (width - 2 * _PLOT_MARGIN_PX)
        py = height - _PLOT_MARGIN_PX - z_mm / z_top * (height - 2 * _PLOT_MARGIN_PX)
        return px, py

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._profile is None or self._profile.size < 2:
            return
        painter = QPainter(self)
        try:
            profile, valid = self._profile, self._valid
            z_max = max(float(profile.max()), 0.1)
            span = self.span_mm

            painter.setPen(QPen(QColor("#565f66"), 1))
            origin = self._map(0.0, 0.0, z_max)
            corner = self._map(span, z_max, z_max)
            painter.drawRect(
                int(origin[0]),
                int(corner[1]),
                int(corner[0] - origin[0]),
                int(origin[1] - corner[1]),
            )
            painter.setPen(QColor("#8b949e"))
            for tick in np.arange(0.0, span + 1e-9, _X_TICK_MM):
                px, base = self._map(float(tick), 0.0, z_max)
                painter.drawLine(int(px), int(base), int(px), int(base) + 4)
                painter.drawText(int(px) - 8, int(base) + 16, f"{tick:.0f}")
            for fraction in (0.5, 1.0):
                _, py = self._map(0.0, z_max * fraction, z_max)
                painter.drawText(4, int(py) + 4, f"{z_max * fraction:.1f}")

            # 分段折线：有效域象牙色，背景（过渡带落地区）灰色
            for value in (False, True):
                pen = QPen(QColor("#e6dcc3") if value else QColor("#6e7681"), 2)
                painter.setPen(pen)
                drawn = False
                previous = (0.0, 0.0)
                for index in range(profile.size):
                    if bool(valid[index]) is not value:
                        drawn = False
                        continue
                    point = self._map(index * self._dx_mm, float(profile[index]), z_max)
                    if drawn:
                        painter.drawLine(
                            int(previous[0]), int(previous[1]), int(point[0]), int(point[1])
                        )
                    previous, drawn = point, True
        finally:
            painter.end()


class CrossSectionDialog(QDialog):
    """穿过最高点的横截面高度曲线 + 截面内最陡坡度（读 heightfield.npz 数据）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("母版侧面截面（穿过最高点）")
        layout = QVBoxLayout(self)
        self.header = QLabel("（未加载截面）")
        self.header.setWordWrap(True)
        layout.addWidget(self.header)
        self.canvas = _SectionCanvas()
        layout.addWidget(self.canvas)

    def set_section(
        self, heights_mm: np.ndarray, valid: np.ndarray, dx_mm: float, dy_mm: float
    ) -> None:
        heights = np.asarray(heights_mm, dtype=np.float64)
        valid = np.asarray(valid, dtype=bool)
        if heights.shape != valid.shape:
            raise ValueError("heights 与 valid 形状不一致")
        row = int(np.unravel_index(int(np.argmax(heights)), heights.shape)[0])
        profile = heights[row]
        drops = np.abs(np.diff(profile)) / max(float(dx_mm), 1e-9)
        steepest = math.degrees(math.atan(float(drops.max()) if drops.size else 0.0))
        self.header.setText(
            f"截面 y = {row * float(dy_mm):.1f} mm（穿过最高点 {float(profile.max()):.2f} mm）；"
            f"截面内最陡 {steepest:.1f}°；象牙色 = 主体（有效域），灰色 = 背景过渡带"
        )
        self.canvas.set_profile(profile, valid[row], float(dx_mm))
