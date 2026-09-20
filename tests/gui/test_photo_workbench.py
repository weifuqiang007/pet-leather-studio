"""本地 GUI 回归（PH10）：四种视图、双光照、未知种类不崩溃；截图存证 runtime/evidence/。

需要真实 Qt/VTK 会话（仅真机运行，CI 不执行 tests/gui）。
"""

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pet_leather_studio.bootstrap import environment

environment.apply_local_env()

from pet_leather_studio.application.photo_workbench import PhotoWorkbench  # noqa: E402
from pet_leather_studio.bootstrap.environment import data_root  # noqa: E402
from pet_leather_studio.domain.photo_relief import MaskMethod  # noqa: E402
from pet_leather_studio.infrastructure.photo_io import PhotoIO  # noqa: E402
from pet_leather_studio.infrastructure.revisions import RevisionStore  # noqa: E402
from pet_leather_studio.presentation.photo_panel import (  # noqa: E402
    VIEW_3D,
    VIEW_DEPTH,
    VIEW_MASK,
    VIEW_PHOTO,
    PhotoWorkbenchWindow,
)


class StubInference:
    """测试桩（仅 tests/）：确定性梯度深度，不联网不加载权重。"""

    def run_and_stage(
        self, image: Path, mask: Path, model_dir: Path, stage: Path
    ) -> dict[str, Any]:
        with Image.open(mask) as mask_image:
            valid = np.asarray(mask_image.convert("L")) > 127
        height, width = valid.shape
        depth = np.repeat(np.linspace(0.2, 0.8, height, dtype=np.float32)[:, None], width, axis=1)
        depth[~valid] = 0.0
        np.savez_compressed(stage / "depth.npz", depth=depth, valid=valid)
        return {
            "schema_version": 2,
            "depth_shape": [height, width],
            "depth_dtype": "float32",
            "depth_semantics": "relative_larger_nearer",
            "valid_coverage": float(valid.mean()),
            "mask_used_for_inference": False,
            "model": {"model_id": "stub-test"},
            "runtime": {
                "device": "stub",
                "elapsed_s": 0.01,
                "torch": None,
                "implementation": "stub",
            },
            "warnings": [],
        }


class StubRegistry:
    def locate(self, model_id: str | None) -> Path:
        return Path("/stub-model-dir")


def _photo_png(path: Path) -> Path:
    arr = np.zeros((60, 80, 3), dtype=np.uint8)
    arr[10:50, 16:64] = (120, 90, 60)
    Image.fromarray(arr).save(path, format="PNG")
    return path


def _mask_png(path: Path) -> Path:
    arr = np.zeros((60, 80), dtype=np.uint8)
    arr[12:48, 20:60] = 255
    Image.fromarray(arr, mode="L").save(path)
    return path


def _build_chain(tmp_path: Path) -> tuple[RevisionStore, PhotoWorkbench, str]:
    project = tmp_path / "proj"
    store = RevisionStore(project)
    service = PhotoWorkbench(store, PhotoIO(), StubInference(), StubRegistry())
    photo = service.import_photo(_photo_png(tmp_path / "pet.png"))
    mask = service.save_mask(
        photo.revision_id, _mask_png(tmp_path / "mask.png"), MaskMethod.MANUAL, notes="GUI 测试"
    )
    depth = service.estimate_depth(photo.revision_id, mask.revision_id)
    return store, service, depth.revision_id


def test_views_lighting_unknown_kind(qtbot, tmp_path: Path) -> None:
    store, service, depth_id = _build_chain(tmp_path)
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.viewer.renderer is not None)
    window.versions.setCurrentIndex(window.versions.findData(depth_id))

    evidence = data_root() / "runtime" / "evidence" / "photo-p1"
    evidence.mkdir(parents=True, exist_ok=True)
    for index, (label, view) in enumerate(
        [(VIEW_PHOTO, "photo"), (VIEW_MASK, "mask"), (VIEW_DEPTH, "depth"), (VIEW_3D, "3d")]
    ):
        window.view.setCurrentText(label)
        assert len(window.viewer.renderer.actors) > 0
        window.viewer.render()
        window.grab().save(str(evidence / f"ph10-view-{index}-{view}.png"))  # 截图存证
        assert "预览失败" not in window.details.toPlainText()

    window.view.setCurrentText(VIEW_DEPTH)
    assert "相机视角" in window.details.toPlainText()  # 未评审边界界面明示

    for light_index in (1, 0):  # 头部单光源 / 三点光组来回切换
        window.lighting.setCurrentIndex(light_index)
        assert len(window.viewer.renderer.lights) >= 1
    assert "预览失败" not in window.details.toPlainText()

    stage = store.begin()
    (stage / "note.txt").write_text("mystery")
    mystery = store.publish(stage, {"kind": "mystery"})
    window.refresh()
    window.versions.setCurrentIndex(window.versions.findData(mystery["id"]))
    assert "未知修订种类" in window.details.toPlainText()  # 不崩溃、历史不动
    assert len(store.history()) == 4
    window.close()
