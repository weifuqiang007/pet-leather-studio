"""局部结构调整编辑器（P2）：在高度色图上刷选区域，逐区域给定偏移/过渡。

底图为高度色图（调用方生成），红色叠加为当前区域蒙版；区域列表增/删/切换，
撤销/重做/清空走 MaskBuffer 快照栈（合同"参数与区域可撤销"）。
返回 .regions = [(mask, offset_mm, transition_mm, label)]，空区域自动丢弃。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pet_leather_studio.domain.photo_relief import (
    LOCAL_OFFSET_MM_RANGE,
    TRANSITION_MM_RANGE,
)
from pet_leather_studio.infrastructure.photo_io import MaskBuffer
from pet_leather_studio.presentation.mask_editor import MASK_OFF, MASK_ON, MaskCanvas

DEFAULT_OFFSET_MM = 0.5
DEFAULT_TRANSITION_MM = 2.0


class HeightAdjustDialog(QDialog):
    """每区域 = 刷选蒙版 + 偏移 + 过渡；画布即当前区域的编辑现场。"""

    def __init__(self, base_rgb: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("局部结构调整（刷选区域 · 偏移/过渡 · 撤销/重做）")
        self.resize(1000, 720)
        self._shape = tuple(base_rgb.shape[:2])
        self._regions: list[dict] = []
        self._current = -1
        self.canvas = MaskCanvas(base_rgb, np.zeros(self._shape, dtype=np.uint8), None)

        layout = QHBoxLayout(self)
        layout.addWidget(self.canvas, stretch=3)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        layout.addWidget(side, stretch=2)

        side_layout.addWidget(QLabel("区域列表（选中即编辑；红色叠加为选中区域）"))
        self.region_list = QListWidget()
        self.region_list.currentRowChanged.connect(self._on_list_row)
        side_layout.addWidget(self.region_list)

        params = QFormLayout()
        self.label_edit = QLineEdit()
        self.label_edit.textChanged.connect(self._sync_params)
        params.addRow("区域名称", self.label_edit)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(LOCAL_OFFSET_MM_RANGE[0], LOCAL_OFFSET_MM_RANGE[1])
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setValue(DEFAULT_OFFSET_MM)
        self.offset_spin.valueChanged.connect(self._sync_params)
        params.addRow("偏移 mm（+ 抬高 / − 压低）", self.offset_spin)
        self.transition_spin = QDoubleSpinBox()
        self.transition_spin.setRange(TRANSITION_MM_RANGE[0], TRANSITION_MM_RANGE[1])
        self.transition_spin.setDecimals(1)
        self.transition_spin.setSingleStep(0.5)
        self.transition_spin.setValue(DEFAULT_TRANSITION_MM)
        self.transition_spin.valueChanged.connect(self._sync_params)
        params.addRow("过渡半径 mm（防尖峰）", self.transition_spin)
        side_layout.addLayout(params)

        region_buttons = QHBoxLayout()
        for label, handler in (
            ("新增区域", self._add_region),
            ("删除选中区域", self._remove_region),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            region_buttons.addWidget(button)
        side_layout.addLayout(region_buttons)

        brush_row = QFormLayout()
        self.radius = QSpinBox()
        self.radius.setRange(1, 64)
        self.radius.setValue(max(4, min(16, min(self._shape) // 12)))
        self.radius.valueChanged.connect(self._sync_brush)
        brush_row.addRow("画笔半径（工作像素）", self.radius)
        side_layout.addLayout(brush_row)
        modes = QHBoxLayout()
        self.add_mode = QRadioButton("刷选")
        self.erase_mode = QRadioButton("擦除")
        self.add_mode.setChecked(True)
        self.add_mode.toggled.connect(self._sync_brush)
        modes.addWidget(self.add_mode)
        modes.addWidget(self.erase_mode)
        side_layout.addLayout(modes)

        canvas_buttons = QHBoxLayout()
        for label, handler in (
            ("撤销", self._undo),
            ("重做", self._redo),
            ("清空当前区域", self._clear),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            canvas_buttons.addWidget(button)
        side_layout.addLayout(canvas_buttons)

        side_layout.addStretch(1)
        finish = QHBoxLayout()
        ok = QPushButton("确定")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        finish.addWidget(ok)
        finish.addWidget(cancel)
        side_layout.addLayout(finish)

        self.status = QLabel()
        side_layout.addWidget(self.status)
        self._add_region()

    # ---- 区域管理 ----

    def _add_region(self) -> None:
        self._commit_current()
        self._regions.append(
            {
                "label": f"区域 {len(self._regions) + 1}",
                "mask": np.zeros(self._shape, dtype=np.uint8),
                "offset": DEFAULT_OFFSET_MM,
                "transition": DEFAULT_TRANSITION_MM,
            }
        )
        self._select_region(len(self._regions) - 1)

    def _remove_region(self) -> None:
        if not self._regions:
            return
        self._commit_current()
        removed = self._current
        self._regions.pop(removed)
        if not self._regions:
            self._add_region()
        else:
            self._select_region(min(removed, len(self._regions) - 1))

    def _select_region(self, index: int) -> None:
        self._current = index
        region = self._regions[index]
        # 整体替换缓冲：切换区域后撤销栈不跨区域串改
        self.canvas.buffer = MaskBuffer(region["mask"])
        self.canvas.update_overlay()
        self.label_edit.setText(region["label"])
        self.offset_spin.setValue(region["offset"])
        self.transition_spin.setValue(region["transition"])
        self._refresh_list()
        self._refresh_status()

    def _on_list_row(self, row: int) -> None:
        if 0 <= row < len(self._regions) and row != self._current:
            self._commit_current()
            self._select_region(row)

    def _commit_current(self) -> None:
        if 0 <= self._current < len(self._regions):
            self._regions[self._current]["mask"] = self.canvas.buffer.mask.copy()

    def _sync_params(self) -> None:
        if 0 <= self._current < len(self._regions):
            region = self._regions[self._current]
            region["label"] = self.label_edit.text() or f"区域 {self._current + 1}"
            region["offset"] = self.offset_spin.value()
            region["transition"] = self.transition_spin.value()
            self._refresh_list()

    def _refresh_list(self) -> None:
        self.region_list.blockSignals(True)
        self.region_list.clear()
        for region in self._regions:
            pixels = int((region["mask"] > 127).sum())
            self.region_list.addItem(
                f"{region['label']} · {region['offset']:+.2f}mm / "
                f"过渡 {region['transition']:.1f}mm · {pixels}px"
            )
        self.region_list.setCurrentRow(self._current)
        self.region_list.blockSignals(False)

    def _refresh_status(self) -> None:
        current = self._regions[self._current] if 0 <= self._current < len(self._regions) else None
        if current is None:
            self.status.setText("无区域")
            return
        coverage = float((current["mask"] > 127).mean())
        self.status.setText(
            f"共 {len(self._regions)} 个区域；当前区域覆盖 {coverage:.1%}；"
            "偏移经高斯过渡作用在刷选区域内，上限限幅不静默"
        )

    # ---- 画布 ----

    def _sync_brush(self) -> None:
        self.canvas.brush_radius = self.radius.value()
        self.canvas.brush_value = MASK_OFF if self.erase_mode.isChecked() else MASK_ON

    def _undo(self) -> None:
        self.canvas.buffer.undo()
        self.canvas.update_overlay()
        self._refresh_status()

    def _redo(self) -> None:
        self.canvas.buffer.redo()
        self.canvas.update_overlay()
        self._refresh_status()

    def _clear(self) -> None:
        self.canvas.apply_array(np.zeros(self._shape, dtype=np.uint8))
        self._refresh_list()
        self._refresh_status()

    @property
    def regions(self) -> list[tuple[np.ndarray, float, float, str]]:
        """非空区域列表 (mask, offset_mm, transition_mm, label)；空区域丢弃。"""
        self._commit_current()
        return [
            (region["mask"], region["offset"], region["transition"], region["label"])
            for region in self._regions
            if (region["mask"] > 127).any()
        ]
