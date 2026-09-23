"""本地 GUI 回归（PH02 GUI 部分）：画笔落点、撤销/重做、缩放映射、阈值初稿。

需要真实 Qt 会话（仅真机运行，CI 不执行 tests/gui）。
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt

from pet_leather_studio.bootstrap import environment

environment.apply_local_env()

from pet_leather_studio.domain.photo_relief import MaskMethod  # noqa: E402
from pet_leather_studio.presentation.mask_editor import (  # noqa: E402
    MASK_TINT_RGBA,
    REMOVED_VEIL_RGBA,
    MaskEditorDialog,
    overlay_rgba,
)

DARK_ROWS = slice(18, 42)
DARK_COLS = slice(26, 54)


@pytest.fixture()
def work_png(tmp_path: Path) -> Path:
    arr = np.full((60, 80, 3), 235, dtype=np.uint8)
    arr[DARK_ROWS, DARK_COLS] = (60, 50, 45)  # 深色主体（浅背景假设成立）
    path = tmp_path / "work.png"
    Image.fromarray(arr).save(path)
    return path


def _shown(qtbot, dialog: MaskEditorDialog) -> MaskEditorDialog:
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.canvas.width() > 100 and dialog.canvas.height() > 100)
    return dialog


def _click(qtbot, dialog: MaskEditorDialog, x: float, y: float) -> None:
    qtbot.mousePress(dialog.canvas, Qt.MouseButton.LeftButton, pos=QPoint(int(x), int(y)))


def test_brush_undo_redo_exact_restore(qtbot, work_png: Path) -> None:
    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    dialog.radius.setValue(6)
    canvas = dialog.canvas
    assert np.count_nonzero(canvas.buffer.mask) == 0

    ix, iy = 40, 30
    widget_x, widget_y = canvas.mapper().image_to_widget(ix, iy)
    _click(qtbot, dialog, widget_x, widget_y)
    assert canvas.buffer.mask[iy, ix] == 255
    assert canvas.manual_painted is True
    painted = canvas.buffer.mask.copy()
    assert np.count_nonzero(painted) > 10

    dialog._undo()
    assert np.array_equal(canvas.buffer.mask, np.zeros_like(painted))  # 逐像素恢复
    dialog._redo()
    assert np.array_equal(canvas.buffer.mask, painted)


def test_embedded_alpha_initial_mask_records_its_provenance(qtbot, work_png: Path) -> None:
    initial = np.zeros((60, 80), dtype=np.uint8)
    initial[10:50, 20:60] = 255
    dialog = _shown(qtbot, MaskEditorDialog(work_png, initial, initial_from_alpha=True))
    assert dialog.mask_method == MaskMethod.EMBEDDED_ALPHA
    assert "透明通道" in dialog.status.text()
    assert tuple(dialog._base[0, 0]) == (218, 218, 218)  # 透明背景显示为棋盘格而非白色


def test_zoomed_click_lands_within_one_pixel(qtbot, work_png: Path) -> None:
    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    dialog.radius.setValue(4)
    canvas = dialog.canvas
    canvas._scale = 3.25  # 模拟滚轮放大后的任意视口
    canvas._offset = (13.5, -7.25)
    ix, iy = 30, 20
    widget_x, widget_y = canvas.mapper().image_to_widget(ix, iy)
    _click(qtbot, dialog, widget_x, widget_y)

    ys, xs = np.nonzero(canvas.buffer.mask)
    assert abs(float(xs.mean()) - ix) <= 1.0  # PH02：误差 ≤1 工作像素
    assert abs(float(ys.mean()) - iy) <= 1.0


def test_pan_mode_moves_canvas_without_painting(qtbot, work_png: Path) -> None:
    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    canvas = dialog.canvas
    before = canvas._offset
    dialog.pan_mode.setChecked(True)

    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(150, 160))
    qtbot.mouseMove(canvas, QPoint(235, 255))
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(235, 255))

    assert canvas._offset == pytest.approx((before[0] + 85, before[1] + 95))
    assert np.count_nonzero(canvas.buffer.mask) == 0


def test_threshold_draft_coverage_and_method(qtbot, work_png: Path) -> None:
    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    dialog.threshold_level.setValue(128)
    dialog._threshold_draft()

    mask = dialog.canvas.buffer.mask
    expected_area = (DARK_ROWS.stop - DARK_ROWS.start) * (DARK_COLS.stop - DARK_COLS.start)
    assert abs(float((mask > 127).mean()) - expected_area / 4800) < 0.01
    assert dialog.init_threshold_level == 128
    assert dialog.mask_method is MaskMethod.THRESHASSISTED  # 未手工修改：如实记录

    dialog.radius.setValue(3)
    widget_x, widget_y = dialog.canvas.mapper().image_to_widget(70, 50)
    _click(qtbot, dialog, widget_x, widget_y)  # 手工补一笔
    assert dialog.mask_method is MaskMethod.MANUAL


def test_erase_mode_removes_pixels(qtbot, work_png: Path) -> None:
    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    dialog.radius.setValue(6)
    widget_x, widget_y = dialog.canvas.mapper().image_to_widget(40, 30)
    _click(qtbot, dialog, widget_x, widget_y)
    assert dialog.canvas.buffer.mask[30, 40] == 255

    dialog.erase_mode.setChecked(True)
    dialog._sync_brush()
    _click(qtbot, dialog, widget_x, widget_y)
    assert dialog.canvas.buffer.mask[30, 40] == 0


def test_overlay_veil_makes_erase_visible() -> None:
    """布局重做回归：保留区红色薄纱、已擦除/未选区深色遮罩——擦除结果必须可辨。"""

    mask = np.zeros((10, 12), dtype=np.uint8)
    mask[2:5, 3:7] = 255
    rgba = overlay_rgba(mask)
    assert tuple(rgba[3, 5]) == MASK_TINT_RGBA  # 保留：红色薄纱
    assert tuple(rgba[0, 0]) == REMOVED_VEIL_RGBA  # 已擦除/未选：深色遮罩


def test_photoshop_layout_canvas_dominates(qtbot, work_png: Path) -> None:
    """布局重做回归：左侧窄工具栏、右侧大画布（画布占窗口主要宽度）。"""

    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    assert dialog.canvas.width() > 0.6 * dialog.width()
    assert dialog.pan_mode.isChecked() is False  # 默认落在画笔，不会误拖画布


def test_space_drag_pans_without_painting(qtbot, work_png: Path) -> None:
    """布局重做回归：空格+左键拖动 = 临时拖动图片（Photoshop 习惯），不落笔。"""

    dialog = _shown(qtbot, MaskEditorDialog(work_png))
    canvas = dialog.canvas
    canvas.setFocus()
    before = canvas._offset
    qtbot.keyPress(canvas, Qt.Key.Key_Space)
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    qtbot.mouseMove(canvas, QPoint(160, 140))
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(160, 140))
    qtbot.keyRelease(canvas, Qt.Key.Key_Space)
    assert canvas._offset == pytest.approx((before[0] + 60, before[1] + 40))
    assert np.count_nonzero(canvas.buffer.mask) == 0
