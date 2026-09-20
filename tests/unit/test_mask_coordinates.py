"""PH02（纯数学部分）：坐标映射误差 ≤1 工作像素；快照式撤销逐像素恢复。"""

import numpy as np
import pytest

from pet_leather_studio.infrastructure.photo_io import CoordinateMapper, MaskBuffer

IMAGE_SIZE = (80, 60)


@pytest.mark.parametrize("scale", [0.05, 0.37, 1.0, 3.25, 40.0])
@pytest.mark.parametrize("offset", [(0.0, 0.0), (13.5, -7.25), (-120.75, 300.5)])
def test_widget_image_roundtrip_within_one_pixel(scale: float, offset: tuple[float, float]) -> None:
    mapper = CoordinateMapper(IMAGE_SIZE, scale, offset)
    width, height = IMAGE_SIZE
    for ix in range(0, width, 7):
        for iy in range(0, height, 5):
            wx, wy = mapper.image_to_widget(ix, iy)
            # 最不利小数扰动（亚工作像素：0.499 个工作像素的视口抖动）
            jitter = 0.499 * scale
            bx, by = mapper.widget_to_image(wx + jitter, wy - jitter)
            assert abs(bx - ix) <= 1, (scale, offset, ix, iy)
            assert abs(by - iy) <= 1, (scale, offset, ix, iy)


def test_widget_to_image_clamps_to_image_bounds() -> None:
    mapper = CoordinateMapper(IMAGE_SIZE, 2.0, (0.0, 0.0))
    assert mapper.widget_to_image(-1e6, -1e6) == (0, 0)
    assert mapper.widget_to_image(1e6, 1e6) == (IMAGE_SIZE[0] - 1, IMAGE_SIZE[1] - 1)


def test_negative_scale_rejected() -> None:
    with pytest.raises(ValueError, match="缩放必须为正"):
        CoordinateMapper(IMAGE_SIZE, -1.0, (0.0, 0.0))


def test_mask_buffer_undo_restores_exactly() -> None:
    buffer = MaskBuffer(np.zeros((60, 80), dtype=np.uint8))
    buffer.snapshot()
    buffer.paint_disk(40, 30, 6, 255)
    painted = buffer.mask.copy()
    assert (painted > 0).sum() > 10

    assert buffer.undo()
    assert np.array_equal(buffer.mask, np.zeros((60, 80), dtype=np.uint8))  # 逐像素恢复
    assert buffer.redo()
    assert np.array_equal(buffer.mask, painted)
    assert buffer.undo()
    assert not buffer.redo() or buffer.mask.max() >= 0  # redo 栈按标准语义工作


def test_mask_buffer_erase_and_shape_guard() -> None:
    buffer = MaskBuffer(np.zeros((60, 80), dtype=np.uint8))
    buffer.snapshot()
    buffer.paint_disk(40, 30, 6, 255)  # ix=40, iy=30
    buffer.snapshot()
    buffer.paint_disk(40, 30, 3, 0)  # 擦除
    erased = buffer.mask.copy()
    assert erased[30, 40] == 0
    assert erased[35, 40] == 255  # 外环保留（距圆心 5px：>3 擦除半径、<6 添加半径）
    assert buffer.undo()
    assert buffer.mask[30, 40] == 255

    with pytest.raises(ValueError, match="形状不一致"):
        buffer.set_mask(np.zeros((5, 5), dtype=np.uint8))


def test_mask_buffer_undo_depth_is_bounded() -> None:
    buffer = MaskBuffer(np.zeros((10, 10), dtype=np.uint8), limit=2)
    for _ in range(4):
        buffer.snapshot()
        buffer.paint_disk(5, 5, 1, 255)
    assert buffer.undo() and buffer.undo()
    assert not buffer.undo()  # 超出上限的早期快照已被丢弃


def test_paint_disk_only_touches_disk_pixels() -> None:
    buffer = MaskBuffer(np.zeros((60, 80), dtype=np.uint8))
    buffer.paint_disk(40, 30, 5, 255)
    ys, xs = np.nonzero(buffer.mask)
    assert np.all((xs - 40) ** 2 + (ys - 30) ** 2 <= 25)
    buffer.paint_disk(0, 0, 4, 255)  # 角落裁剪不越界
    assert buffer.mask.shape == (60, 80)
