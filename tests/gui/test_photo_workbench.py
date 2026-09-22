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
from pet_leather_studio.domain.photo_relief import (  # noqa: E402
    LocalAdjustment,
    MaskMethod,
    ReliefParameters,
)
from pet_leather_studio.infrastructure.photo_geometry import PhotoGeometry  # noqa: E402
from pet_leather_studio.infrastructure.photo_io import PhotoIO  # noqa: E402
from pet_leather_studio.infrastructure.reference_profile import (  # noqa: E402
    ReferenceProfileStore,
)
from pet_leather_studio.infrastructure.revisions import RevisionStore  # noqa: E402
from pet_leather_studio.presentation.height_adjust_dialog import (  # noqa: E402
    HeightAdjustDialog,
)
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
    service = PhotoWorkbench(
        store,
        PhotoIO(),
        StubInference(),
        StubRegistry(),
        PhotoGeometry(),
        ReferenceProfileStore(tmp_path / "profiles"),
    )
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
        # QWidget.grab() 抓不到 VTK 的 OpenGL 内容（会得到空白图），
        # 证据必须用渲染窗口自身截图。
        window.viewer.screenshot(str(evidence / f"ph10-view-{index}-{view}.png"))
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


def test_view_switching_auto_uses_latest_chain(qtbot, tmp_path: Path) -> None:
    """选中 photo 修订后切蒙版/深度/三维视图：自动补链渲染，不再空白。"""
    store, service, depth_id = _build_chain(tmp_path)
    photo_id = next(row["id"] for row in store.history() if row["kind"] == "photo")
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.viewer.renderer is not None)
    window.versions.setCurrentIndex(window.versions.findData(photo_id))

    for label in (VIEW_MASK, VIEW_DEPTH, VIEW_3D):
        window.view.setCurrentText(label)
        assert len(window.viewer.renderer.actors) > 0  # 画布有内容
        assert "预览失败" not in window.details.toPlainText()
    assert "已用同照片最新修订预览" in window.details.toPlainText()
    window.close()


def test_cancel_job_stops_kill_timer_and_survives_window(qtbot, tmp_path: Path) -> None:
    """F1：取消后任务结束即停止受控 kill 定时器；等过 5s 兜底窗口不得再触碰
    已销毁的 QProcess（pytest-qt 会把槽内异常直接判为失败）。"""
    store, service, depth_id = _build_chain(tmp_path)
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    png = _photo_png(tmp_path / "cancel.png")
    window.start_job(["import-photo", str(png)])
    assert window.process is not None
    window.cancel_job()
    assert window.kill_timer is not None  # 取消时定时器确实武装（任务仍在运行）
    qtbot.waitUntil(lambda: window.process is None, timeout=30000)
    assert window.kill_timer is None  # job_finished 已停止并清空
    qtbot.wait(5600)  # 覆盖 5s 兜底窗口：旧实现此处触发已删除 C++ 对象访问
    assert window.process is None
    window.close()


def test_close_window_during_job_cancels_then_closes(qtbot, tmp_path: Path) -> None:
    """F1：任务进行中关窗 → 先取消任务，结束后自动关闭；无残留定时器。"""
    store, service, depth_id = _build_chain(tmp_path)
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.show()
    png = _photo_png(tmp_path / "close.png")
    window.start_job(["import-photo", str(png)])
    window.close()  # closeEvent：取消并推迟关闭
    assert window.close_after_job is True
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=30000)
    assert window.process is None
    assert window.kill_timer is None
    window.close()


def test_start_job_during_pending_cancel_is_ignored(qtbot, tmp_path: Path) -> None:
    """F1：取消尚未完成时不得并发起第二个任务进程；取消结束后可正常起新任务。"""
    store, service, depth_id = _build_chain(tmp_path)
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    png = _photo_png(tmp_path / "double.png")
    window.start_job(["import-photo", str(png)])
    first = window.process
    window.cancel_job()
    assert window.kill_timer is not None  # 取消尚未完成
    window.start_job(["import-photo", str(png)])  # 旧进程仍在：直接返回
    assert window.process is first
    qtbot.waitUntil(lambda: window.process is None, timeout=30000)
    assert window.import_button.isEnabled()

    window.start_job(["import-photo", str(png)])  # 取消结束后可正常起新任务
    qtbot.waitUntil(lambda: window.process is None, timeout=30000)
    assert "完成" in window.status.text()
    window.close()


def _write_reference_obj(path: Path) -> None:
    """合成参考 OBJ：0 底 + 4mm 方凸 + 6mm 尖点（percentile 99 裁掉尖点）。"""
    import trimesh

    xs = np.linspace(0.0, 10.0, 11)
    xx, yy = np.meshgrid(xs, xs)
    zz = np.zeros_like(xx)
    zz[4:7, 4:7] = 4.0
    zz[5, 5] = 6.0
    index = (np.arange(10)[:, None] * 11 + np.arange(10)).ravel()
    b, c, d = index + 1, index + 12, index + 11
    faces = np.vstack([np.column_stack([index, b, c]), np.column_stack([index, c, d])])
    points = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
    trimesh.Trimesh(points, faces, process=False).export(path)


def test_master_form_ratio_requires_profile(qtbot, tmp_path: Path, monkeypatch) -> None:
    """P2：ratio 模式未选标定时拒绝生成（不暗用参考比例），显式深度旋钮禁用。"""
    store, service, depth_id = _build_chain(tmp_path)
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.versions.setCurrentIndex(window.versions.findData(depth_id))
    window.height_mode.setCurrentIndex(1)  # 参考比例
    assert not window.master_depth.isEnabled()
    assert "先完成参考标定" in window.ratio_hint.text()

    warned: list[tuple[str, str]] = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warned.append((title, text))
        return None

    monkeypatch.setattr(
        "pet_leather_studio.presentation.photo_panel.QMessageBox.warning", fake_warning
    )
    window.build_master()
    assert warned and "参考比例缺标定" in warned[0][0]
    assert window.process is None  # 未起任务
    window.close()


def test_build_master_argument_assembly(qtbot, tmp_path: Path) -> None:
    """P2：生成母版的 CLI 参数由表单与待提交局部调整拼装（含 --adjustment）。"""
    store, service, depth_id = _build_chain(tmp_path)
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.versions.setCurrentIndex(window.versions.findData(depth_id))
    window.master_width.setValue(42.5)
    window.master_depth.setValue(1.25)
    window.smoothing.setValue(1.5)
    window.base_thickness.setValue(4.0)
    window._pending_adjustments = [
        LocalAdjustment(
            label="鼻尖", region_png="/tmp/region.png", offset_mm=0.5, transition_mm=2.0
        )
    ]
    captured: list[list[str]] = []

    def capture(arguments):
        captured.append(list(arguments))

    window.start_job = capture
    window.build_master()
    assert captured == [
        [
            "build-master",
            "--depth",
            depth_id,
            "--width-mm",
            "42.5",
            "--height-mode",
            "explicit_depth",
            "--depth-mm",
            "1.25",
            "--base-mm",
            "4",
            "--falloff-mm",
            "2.5",
            "--smoothing-mm",
            "1.5",
            "--adjustment",
            "/tmp/region.png:0.5:2:鼻尖",
        ]
    ]
    window.close()


def test_master_view_dispatch(qtbot, tmp_path: Path) -> None:
    """P2：photo_reconstruction 母版 → preview.vtp 渲染 + 母版详情；上游视图可达。"""
    store, service, depth_id = _build_chain(tmp_path)
    master = service.build_master(
        depth_id, ReliefParameters(width_mm=40.0, depth_mm=1.5, base_thickness_mm=2.0)
    )
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.viewer.renderer is not None)
    window.versions.setCurrentIndex(window.versions.findData(master.revision_id))
    window.view.setCurrentText(VIEW_3D)
    assert len(window.viewer.renderer.actors) > 0
    text = window.details.toPlainText()
    assert "母版" in text and "photo_reconstruction" in text
    assert "正面起伏" in text and "重读校验" in text
    assert "边缘过渡" in text  # R1：非矩形主体的过渡带统计须展示

    window.view.setCurrentText(VIEW_PHOTO)  # 母版上游链可达
    assert len(window.viewer.renderer.actors) > 0
    window.close()


def test_height_adjust_dialog_regions_and_undo(qtbot) -> None:
    """P2：区域刷选 + 偏移/过渡参数 + 撤销；空区域在结果中丢弃。"""
    base = np.zeros((32, 40, 3), dtype=np.uint8)
    dialog = HeightAdjustDialog(base)
    qtbot.addWidget(dialog)
    dialog.offset_spin.setValue(0.75)
    dialog.transition_spin.setValue(3.0)
    dialog.canvas.buffer.snapshot()
    dialog.canvas.buffer.paint_disk(20, 16, 5, 255)
    regions = dialog.regions
    assert len(regions) == 1
    mask, offset, transition, label = regions[0]
    assert (mask > 127).sum() > 0
    assert offset == 0.75 and transition == 3.0

    dialog._add_region()  # 第二区域：负向偏移
    dialog.offset_spin.setValue(-1.0)
    dialog.canvas.buffer.snapshot()
    dialog.canvas.buffer.paint_disk(5, 5, 3, 255)
    assert len(dialog.regions) == 2
    assert dialog.regions[1][1] == -1.0

    dialog.canvas.buffer.undo()  # 撤销第二区域笔画 → 变空被丢弃
    assert len(dialog.regions) == 1


def test_excluded_points_view_and_ratio_hint(qtbot, tmp_path: Path) -> None:
    """P2：标定下拉 → 排除点红点视图 + 被裁统计；ratio 换算提示实时显示。"""
    from pet_leather_studio.infrastructure.reference_profile import measure_reference

    obj = tmp_path / "reference.obj"
    _write_reference_obj(obj)
    profile = measure_reference(obj, percentile=99.0)
    store_dir = tmp_path / "profiles"
    ReferenceProfileStore(store_dir).save(profile)

    store, service, depth_id = _build_chain(tmp_path)  # profiles 根同为 tmp/profiles
    window = PhotoWorkbenchWindow(service, tmp_path / "proj")
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.viewer.renderer is not None)
    index = window.profile_combo.findData(profile.profile_id)
    assert index >= 0
    window.profile_combo.setCurrentIndex(index)
    window.show_excluded_points()
    assert len(window.viewer.renderer.actors) > 0
    text = window.details.toPlainText()
    assert "排除点" in text and "被裁 1 点" in text
    assert "真实最高 6.0" in text

    window.height_mode.setCurrentIndex(1)
    assert "⇒ 深度" in window.ratio_hint.text()
    window.close()
