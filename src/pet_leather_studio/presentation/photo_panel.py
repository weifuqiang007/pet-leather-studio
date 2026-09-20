"""P1 照片工作台：导入 → 人工蒙版 → 真实深度（隔离进程）→ 中性几何预览。

预览与后续母版共用同一数值管线（algorithms.relief_height）；
深度语义为相机视角相对前后关系，未做姿态归一化（P1 边界，界面明示）。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
from PIL import Image
from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor

from pet_leather_studio.algorithms.relief_height import (
    cap_to_mm,
    image_to_geometry_rows,
    unit_height,
)
from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.domain.photo_relief import DepthSemantics
from pet_leather_studio.presentation.mask_editor import MaskEditorDialog

VIEW_PHOTO = "原图"
VIEW_MASK = "蒙版"
VIEW_DEPTH = "深度图"
VIEW_3D = "三维中性预览"
PREVIEW_WIDTH_MM = 80.0

_COLORMAP_ANCHORS = np.array(
    [
        [30, 20, 70],
        [55, 80, 170],
        [35, 160, 190],
        [140, 210, 110],
        [250, 220, 90],
        [240, 110, 50],
    ],
    dtype=np.float64,
)


class PhotoWorkbenchWindow(QMainWindow):
    def __init__(self, service: PhotoWorkbench, project: Path) -> None:
        super().__init__()
        self.service, self.project = service, project
        self.process = None
        self.close_after_job = False
        self.setWindowTitle("照片 → 浮雕 · P1（人工蒙版 + 真实深度 · 相机视角）")
        self.resize(1320, 860)
        content = QWidget()
        layout = QVBoxLayout(content)
        notice = QLabel(
            "流程：导入照片 → 人工蒙版 → 隔离环境真实深度推理（DA2-Small）→ 中性预览。\n"
            "深度为相机视角相对前后关系，未做姿态归一化；预览/深度均未通过视觉评审，"
            "不能当作已完成母版。模型未安装时推理会给出明确指引（产品路径不联网）。"
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addWidget(QLabel(f"工程：{project}"))
        split = QSplitter()
        panel = QWidget()
        controls = QVBoxLayout(panel)

        self.import_button = QPushButton("导入照片 JPG/PNG")
        self.import_button.clicked.connect(self.import_photo)
        controls.addWidget(self.import_button)
        self.mask_button = QPushButton("编辑蒙版（人工画笔/擦除/撤销）")
        self.mask_button.clicked.connect(self.edit_mask)
        controls.addWidget(self.mask_button)
        self.depth_button = QPushButton("深度推理（真实模型 · 隔离进程）")
        self.depth_button.clicked.connect(self.run_depth)
        controls.addWidget(self.depth_button)
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.clicked.connect(self.cancel_job)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.cancel_button)

        form = QFormLayout()
        self.view = QComboBox()
        self.view.addItems([VIEW_PHOTO, VIEW_MASK, VIEW_DEPTH, VIEW_3D])
        self.view.currentIndexChanged.connect(self.show_selected)
        form.addRow("视图", self.view)
        self.lighting = QComboBox()
        self.lighting.addItems(["三点光组", "头部单光源"])
        self.lighting.currentIndexChanged.connect(self.show_selected)
        form.addRow("光照", self.lighting)
        self.preview_depth = QDoubleSpinBox()
        self.preview_depth.setRange(0.05, 20.0)
        self.preview_depth.setDecimals(2)
        self.preview_depth.setValue(2.0)
        self.preview_depth.valueChanged.connect(self.show_selected)
        form.addRow("预览起伏上限 mm（explicit_depth）", self.preview_depth)
        controls.addLayout(form)

        controls.addWidget(QLabel("历史版本（选中仅预览；激活才回退）"))
        self.versions = QComboBox()
        self.versions.currentIndexChanged.connect(self.show_selected)
        controls.addWidget(self.versions)
        self.activate_button = QPushButton("激活选中版本（保留历史）")
        self.activate_button.clicked.connect(self.activate)
        controls.addWidget(self.activate_button)
        self._job_widgets = (
            self.import_button,
            self.mask_button,
            self.depth_button,
            self.activate_button,
        )
        self.open_button = QPushButton("打开选中版本文件夹")
        self.open_button.clicked.connect(self.open_folder)
        controls.addWidget(self.open_button)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        controls.addWidget(self.details)
        split.addWidget(panel)
        self.viewer = QtInteractor(split)
        self.viewer.set_background("#2b3038")
        split.addWidget(self.viewer.interactor)
        split.setSizes([400, 900])
        layout.addWidget(split)
        views = QHBoxLayout()
        for label, method in (
            ("正视 +Z", "view_xy"),
            ("侧视", "view_xz"),
            ("斜视", "view_isometric"),
            ("复位", "reset_camera"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, name=method: getattr(self.viewer, name)())
            views.addWidget(button)
        layout.addLayout(views)
        self.status = QLabel("就绪")
        layout.addWidget(self.status)
        self.setCentralWidget(content)
        self.refresh()

    # ---- 版本列表与链路 ----

    def refresh(self):
        self.versions.blockSignals(True)
        self.versions.clear()
        try:
            history = self.service.store.history()
        except (ValueError, OSError):
            history = []
        for row in history:
            self.versions.addItem(
                f"{row['kind']} {row['created_at'][:19]} {row['id'][:8]}", row["id"]
            )
        try:
            active = self.service.store.get()["id"]
            index = self.versions.findData(active)
            if index >= 0:
                self.versions.setCurrentIndex(index)
        except (ValueError, OSError):
            pass
        self.versions.blockSignals(False)
        self.show_selected()

    def _selected(self) -> dict[str, Any] | None:
        revision_id = self.versions.currentData()
        if not revision_id:
            return None
        try:
            return self.service.store.get(revision_id)
        except (ValueError, OSError):
            return None

    def _chain(
        self, data: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict | None, dict | None]:
        kind = data.get("kind")
        try:
            if kind == "photo":
                return data, None, None
            if kind == "mask":
                return self.service.store.get(str(data["photo_id"])), data, None
            if kind == "depth":
                photo = self.service.store.get(str(data["photo_id"]))
                mask = self.service.store.get(str(data["mask_id"]))
                return photo, mask, data
        except (ValueError, OSError):
            return None, None, None
        return None, None, None

    def _latest_mask(self, photo_id: str) -> dict[str, Any] | None:
        for row in self.service.store.history():
            if row.get("kind") == "mask" and row.get("photo_id") == photo_id:
                return row
        return None

    def _latest_depth(self, photo_id: str) -> dict[str, Any] | None:
        for row in self.service.store.history():
            if row.get("kind") == "depth" and row.get("photo_id") == photo_id:
                return row
        return None

    def _preview_chain(
        self, data: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict | None, dict | None]:
        """预览链：以选中修订所属照片为锚，缺失环节自动取该照片最新修订。

        避免选中 photo 修订后切蒙版/深度/三维视图时画布空白无解释；
        自动补链会在详情文本中注明，编辑/推理按钮仍走严格链路。
        """
        photo, mask, depth = self._chain(data)
        if photo is not None:
            if mask is None:
                latest = self._latest_mask(str(photo["id"]))
                mask = self.service.store.get(str(latest["id"])) if latest else None
            if depth is None:
                latest = self._latest_depth(str(photo["id"]))
                depth = self.service.store.get(str(latest["id"])) if latest else None
        return photo, mask, depth

    # ---- 显示 ----

    def show_selected(self):
        data = self._selected()
        self._apply_lighting()
        if data is None:
            self.details.setPlainText("暂无版本；请先导入照片。")
            self.viewer.reset_camera()
            return
        kind = str(data.get("kind"))
        photo, mask, depth = self._preview_chain(data)
        strict = self._chain(data)
        auto_filled = (mask is not None and strict[1] is None) or (
            depth is not None and strict[2] is None
        )
        target = self.view.currentText()
        try:
            if kind not in ("photo", "mask", "depth"):
                if kind in ("master", "mold"):
                    message = "该修订属于模具工作台（python -m pet_leather_studio）预览。"
                else:
                    message = f"未知修订种类 {kind!r}；已跳过预览，文件与历史不变。"
                self.details.setPlainText(message)
                self.viewer.reset_camera()
                return
            if target == VIEW_PHOTO and photo is not None:
                self._add_image_plane(self.service.store.directory(photo["id"]) / "work.png")
                message = self._photo_text(photo)
            elif target == VIEW_MASK and mask is not None:
                self._add_image_plane(self.service.store.directory(mask["id"]) / "mask.png")
                message = self._mask_text(mask)
            elif target == VIEW_DEPTH and depth is not None:
                png = self._depth_colormap_png(depth)
                self._add_image_plane(png)
                message = self._depth_text(depth)
            elif target == VIEW_3D and depth is not None:
                self._add_depth_mesh(depth)
                message = self._depth_text(depth)
            else:
                message = "当前工程尚无该视图所需数据；请先生成蒙版或运行深度推理。"
            if auto_filled:
                message += (
                    "\n（注：所选修订缺该环节，已用同照片最新修订预览；编辑/推理以所选链路为准。）"
                )
            self.details.setPlainText(message)
            self.viewer.reset_camera()
        except (ValueError, OSError, RuntimeError) as exc:
            self.details.setPlainText(f"预览失败：{exc}")

    def _apply_lighting(self) -> None:
        self.viewer.clear()
        if self.lighting.currentText() == "头部单光源":
            self.viewer.remove_all_lights()
            headlight = pv.Light(position=(0, 0, 3), color="white")
            headlight.set_headlight()  # 跟随相机，正对浮雕面
            self.viewer.add_light(headlight)
        else:
            self.viewer.enable_lightkit()

    def _add_image_plane(self, png: Path) -> None:
        with Image.open(png) as image:
            width_px, height_px = image.size
        long_edge = max(width_px, height_px)
        plane = pv.Plane(
            i_resolution=1,
            j_resolution=1,
            direction=(0, 0, 1),
        )
        plane.scale(
            [
                PREVIEW_WIDTH_MM * width_px / long_edge,
                PREVIEW_WIDTH_MM * height_px / long_edge,
                1.0,
            ],
            inplace=True,
            transform_all_input_vectors=False,
        )
        self.viewer.add_mesh(plane, texture=pv.Texture(str(png)), smooth_shading=False)
        self.viewer.view_xy()

    def _add_depth_mesh(self, depth: dict[str, Any]) -> None:
        data = np.load(self.service.store.directory(depth["id"]) / "depth.npz")
        unit = unit_height(data["depth"], data["valid"], DepthSemantics(depth["depth_semantics"]))
        heights = image_to_geometry_rows(cap_to_mm(unit, self.preview_depth.value()))
        ny, nx = heights.shape
        height_mm = PREVIEW_WIDTH_MM * ny / nx
        xx, yy = np.meshgrid(
            np.linspace(0.0, PREVIEW_WIDTH_MM, nx), np.linspace(0.0, height_mm, ny)
        )
        grid = pv.StructuredGrid(xx, yy, heights)
        self.viewer.add_mesh(grid, color="ivory", smooth_shading=True)

    def _depth_colormap_png(self, depth: dict[str, Any]) -> Path:
        data = np.load(self.service.store.directory(depth["id"]) / "depth.npz")
        values, valid = data["depth"], data["valid"]
        unit = unit_height(values, valid, DepthSemantics(depth["depth_semantics"]))
        positions = np.linspace(0.0, 1.0, len(_COLORMAP_ANCHORS))
        colored = np.stack(
            [np.interp(unit, positions, _COLORMAP_ANCHORS[:, channel]) for channel in range(3)],
            axis=-1,
        ).astype(np.uint8)
        out = Path(self.service.store.root) / "tmp" / f"depth-{depth['id'][:8]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(colored, mode="RGB").save(out)
        return out

    @staticmethod
    def _photo_text(photo: dict[str, Any]) -> str:
        warnings = "\n".join(photo.get("warnings", []))
        return (
            f"照片 · {photo.get('source_name')}\n"
            f"原始 {photo.get('width_px')}×{photo.get('height_px')}px；"
            f"工作 {photo.get('work_width_px')}×{photo.get('work_height_px')}px；"
            f"EXIF {photo.get('exif_orientation')} → {photo.get('coordinate_transform')}\n"
            f"{warnings}"
        )

    @staticmethod
    def _mask_text(mask: dict[str, Any]) -> str:
        level = mask.get("threshold_level")
        threshold_note = f"（阈值 {level}）" if level is not None else ""
        return (
            f"蒙版 · {mask.get('mask_method')}{threshold_note}\n"
            f"覆盖率 {mask.get('coverage', 0.0):.1%}；对应照片 {str(mask.get('photo_id'))[:8]}"
        )

    @staticmethod
    def _depth_text(depth: dict[str, Any]) -> str:
        runtime = depth.get("runtime", {})
        return (
            f"深度 · {depth.get('depth_semantics')}；"
            f"设备 {runtime.get('device')}；实现 {runtime.get('implementation')}\n"
            f"有效覆盖 {depth.get('valid_coverage', 0.0):.1%}；"
            f"推理耗时 {runtime.get('elapsed_s')}s\n" + "\n".join(depth.get("warnings", []))
        )

    # ---- 任务（CLI 子进程，GUI 不直接写库） ----

    def import_photo(self):
        name, _ = QFileDialog.getOpenFileName(
            self,
            "选择宠物照片（原图不会被修改）",
            str(self.project.parent),
            "照片 (*.jpg *.jpeg *.png)",
        )
        if name:
            self.start_job(["import-photo", name])

    def edit_mask(self):
        data = self._selected()
        if data is None or data.get("kind") not in ("photo", "mask", "depth"):
            QMessageBox.warning(self, "缺少照片", "请先选择照片链上的修订（photo/mask/depth）。")
            return
        photo, _, _ = self._chain(data)
        if photo is None:
            QMessageBox.warning(self, "缺少照片", "未能定位照片修订。")
            return
        photo_id = str(photo["id"])
        work_png = self.service.store.directory(photo_id) / "work.png"
        initial = None
        latest = self._latest_mask(photo_id)
        if latest is not None:
            with Image.open(self.service.store.directory(latest["id"]) / "mask.png") as image:
                initial = np.asarray(image, dtype=np.uint8)
        dialog = MaskEditorDialog(work_png, initial, self)
        if dialog.exec() != MaskEditorDialog.DialogCode.Accepted:
            return
        from pet_leather_studio.bootstrap.environment import data_root

        draft = data_root() / "runtime" / "tmp" / f"mask-draft-{uuid.uuid4().hex}.png"
        draft.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(dialog.mask, mode="L").save(draft)
        arguments = [
            "save-mask",
            "--photo",
            photo_id,
            "--mask",
            str(draft),
            "--method",
            dialog.mask_method.value,
        ]
        if dialog.init_threshold_level is not None:
            arguments.extend(["--threshold-level", str(dialog.init_threshold_level)])
        self.start_job(arguments)

    def run_depth(self):
        data = self._selected()
        if data is None or data.get("kind") not in ("photo", "mask", "depth"):
            QMessageBox.warning(self, "缺少照片", "请先选择照片链上的修订。")
            return
        photo, _, depth = self._chain(data)
        if photo is None:
            QMessageBox.warning(self, "缺少照片", "未能定位照片修订。")
            return
        photo_id = str(photo["id"])
        if depth is not None:
            self.start_job(["estimate-depth", "--photo", photo_id, "--mask", str(depth["mask_id"])])
            return
        latest = self._latest_mask(photo_id)
        if latest is None:
            QMessageBox.warning(self, "缺少蒙版", "请先编辑并保存人工蒙版，再运行深度推理。")
            return
        self.start_job(["estimate-depth", "--photo", photo_id, "--mask", str(latest["id"])])

    def start_job(self, arguments):
        if self.process is not None:
            return
        process = QProcess(self)
        self.process = process
        process.setProgram(sys.executable)
        process.setArguments(
            ["-m", "pet_leather_studio", "--project", str(self.project), *arguments]
        )
        process.finished.connect(self.job_finished)
        process.errorOccurred.connect(self.process_error)
        for widget in self._job_widgets:
            widget.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("计算中（独立进程）；失败不产生新版本，可取消…")
        process.start()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.job_finished(-1, QProcess.ExitStatus.CrashExit)

    def cancel_job(self):
        if self.process is None:
            return
        process = self.process
        # 先 SIGTERM：CLI 收到后会整组回收推理 worker（SIGKILL 杀不到孙进程）；
        # 5 秒未退出再兜底 SIGKILL，防止 TERM 被忽略导致任务挂死。
        process.terminate()
        self.status.setText("正在取消（先 TERM 再兜底 KILL）；历史成功版本保持不变")
        QTimer.singleShot(
            5000,
            lambda: process.kill() if process.state() != QProcess.ProcessState.NotRunning else None,
        )

    def job_finished(self, code, status):
        process = self.process
        if process is None:
            return
        errors = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        self.process = None
        process.deleteLater()
        for widget in self._job_widgets:
            widget.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status.setText(
            "完成，新版本已保存" if code == 0 else "任务结束异常/已取消；旧版本保持不变"
        )
        self.refresh()
        if code != 0 and errors:
            self.details.append(errors[-3000:])
        if self.close_after_job:
            QTimer.singleShot(0, self.close)

    def activate(self):
        revision_id = self.versions.currentData()
        if revision_id:
            try:
                self.service.store.activate(revision_id)
                self.refresh()
                self.status.setText("已切换当前版本；所有历史文件保留")
            except (ValueError, OSError) as exc:
                QMessageBox.warning(self, "回退失败", str(exc))

    def open_folder(self):
        revision_id = self.versions.currentData()
        if revision_id:
            folder = self.service.store.directory(revision_id)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event: QCloseEvent):
        if self.process is not None:
            self.close_after_job = True
            self.cancel_job()
            event.ignore()
            return
        self.viewer.close()
        event.accept()
