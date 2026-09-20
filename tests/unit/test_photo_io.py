"""PH01：照片输入检查——原图逐字节不变、EXIF 归一化、坏文件明确失败、蒙版纯校验。"""

import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pet_leather_studio.domain.photo_relief import MaskMethod
from pet_leather_studio.infrastructure.photo_io import PhotoIO, threshold_draft


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def photo_file(tmp_path: Path) -> Path:
    arr = np.zeros((60, 80, 3), dtype=np.uint8)
    arr[10:50, 20:60] = (120, 90, 60)
    path = tmp_path / "pet.jpg"
    Image.fromarray(arr).save(path, format="JPEG")
    return path


def _stage(tmp_path: Path, name: str) -> Path:
    stage = tmp_path / name
    stage.mkdir()
    return stage


def test_import_preserves_original_and_writes_work_png(tmp_path: Path, photo_file: Path) -> None:
    before = _sha256(photo_file)
    metadata = PhotoIO().prepare_import(photo_file, _stage(tmp_path, "s"))
    assert _sha256(photo_file) == before  # 原图永不被修改
    assert _sha256(tmp_path / "s" / "original.jpg") == before  # 副本逐字节一致
    with Image.open(tmp_path / "s" / "work.png") as work:
        assert work.size == (80, 60) and work.mode == "RGB"
    assert (tmp_path / "s" / "original.jpg").stat().st_mode & 0o222 == 0  # 只读副本
    assert metadata["width_px"] == 80 and metadata["work_width_px"] == 80
    assert metadata["coordinate_transform"] == "none"
    assert metadata["schema_version"] == 2
    assert any("低于建议" in w for w in metadata["warnings"])  # 80px < 800px 建议值


def test_exif_orientation_transposes_work_image(tmp_path: Path) -> None:
    arr = np.zeros((30, 40, 3), dtype=np.uint8)
    arr[:, :10] = (250, 10, 10)
    path = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[274] = 6  # 顺时针 90°
    Image.fromarray(arr).save(path, format="JPEG", exif=exif)

    metadata = PhotoIO().prepare_import(path, _stage(tmp_path, "s"))
    assert (metadata["width_px"], metadata["height_px"]) == (40, 30)
    assert (metadata["work_width_px"], metadata["work_height_px"]) == (30, 40)
    assert metadata["coordinate_transform"] == "exif_transpose"
    with Image.open(tmp_path / "s" / "work.png") as work:
        assert work.size == (30, 40)
        corner = np.asarray(work)[0, 0]  # 原左侧红条旋转后位于图像顶部
        assert corner[0] > 180 and corner[1] < 90 and corner[2] < 90


def test_rejects_garbage_and_unsupported_suffix(tmp_path: Path) -> None:
    garbage = tmp_path / "bad.png"
    garbage.write_bytes(b"\x89PNG\r\n\x1a\n not a real image")
    with pytest.raises(ValueError, match="无法解码"):
        PhotoIO().prepare_import(garbage, _stage(tmp_path, "s1"))

    bitmap = tmp_path / "x.bmp"
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(bitmap, format="BMP")
    with pytest.raises(ValueError, match="只支持"):
        PhotoIO().prepare_import(bitmap, _stage(tmp_path, "s2"))

    with pytest.raises(ValueError, match="不存在"):
        PhotoIO().prepare_import(tmp_path / "ghost.jpg", _stage(tmp_path, "s3"))


def _photo_metadata(stage: Path, photo_file: Path) -> dict:
    return PhotoIO().prepare_import(photo_file, stage)


def test_prepare_mask_rejects_wrong_mode_size_and_empty(tmp_path: Path, photo_file: Path) -> None:
    io = PhotoIO()
    photo = _photo_metadata(_stage(tmp_path, "p"), photo_file)

    rgb_mask = tmp_path / "rgb.png"
    Image.fromarray(np.zeros((60, 80, 3), dtype=np.uint8)).save(rgb_mask)
    with pytest.raises(ValueError, match="单通道"):
        io.prepare_mask(_stage(tmp_path, "m1"), rgb_mask, photo, MaskMethod.MANUAL, None, None)

    small = tmp_path / "small.png"
    Image.fromarray(np.zeros((10, 10), dtype=np.uint8), mode="L").save(small)
    with pytest.raises(ValueError, match="不一致"):
        io.prepare_mask(_stage(tmp_path, "m2"), small, photo, MaskMethod.MANUAL, None, None)

    empty = tmp_path / "empty.png"
    Image.fromarray(np.zeros((60, 80), dtype=np.uint8), mode="L").save(empty)
    with pytest.raises(ValueError, match="空蒙版"):
        io.prepare_mask(_stage(tmp_path, "m3"), empty, photo, MaskMethod.MANUAL, None, None)


def test_prepare_mask_records_method_and_threshold(tmp_path: Path, photo_file: Path) -> None:
    io = PhotoIO()
    photo = _photo_metadata(_stage(tmp_path, "p"), photo_file)
    mask = tmp_path / "mask.png"
    arr = np.zeros((60, 80), dtype=np.uint8)
    arr[10:50, 20:60] = 255
    Image.fromarray(arr, mode="L").save(mask)

    metadata = io.prepare_mask(
        _stage(tmp_path, "m"), mask, photo, MaskMethod.THRESHASSISTED, 128, "测试初稿"
    )
    assert metadata["mask_method"] == "threshold_assisted"
    assert metadata["threshold_level"] == 128
    assert metadata["notes"] == "测试初稿"
    assert metadata["coverage"] == pytest.approx(40 * 40 / (80 * 60))
    with Image.open(tmp_path / "m" / "mask.png") as saved:
        assert saved.mode == "L" and saved.size == (80, 60)

    full = tmp_path / "full.png"
    Image.fromarray(np.full((60, 80), 255, dtype=np.uint8), mode="L").save(full)
    warned = io.prepare_mask(_stage(tmp_path, "m4"), full, photo, MaskMethod.MANUAL, None, None)
    assert any("背景" in w for w in warned["warnings"])


def test_threshold_draft_binarizes_by_luminance(tmp_path: Path) -> None:
    arr = np.full((60, 80, 3), 235, dtype=np.uint8)  # 浅色背景（初稿假设）
    arr[10:50, 20:60] = (60, 50, 45)  # 深色主体（亮度约 53）
    work = tmp_path / "work.png"
    Image.fromarray(arr).save(work)

    draft = threshold_draft(work, 128)
    assert draft.shape == (60, 80)
    assert draft[30, 40] == 255  # 深色主体被选中
    assert draft[0, 0] == 0  # 浅色背景排除
    with pytest.raises(ValueError, match="0–255"):
        threshold_draft(work, 300)
