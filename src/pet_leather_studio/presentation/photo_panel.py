"""P2 照片工作台：导入 → 人工蒙版 → 真实深度 → 受控浮雕化母版（隔离进程）。

三维预览与母版导出共用同一数值管线 controlled_heights_mm（PH10 一致）；
深度语义为相机视角相对前后关系，未做姿态归一化（P1 边界，界面明示）。
"""

from __future__ import annotations

import math
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
    QInputDialog,
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
    background_clearance_mm,
    controlled_heights_mm,
    image_to_geometry_rows,
    unit_height,
)
from pet_leather_studio.application.photo_workbench import PhotoWorkbench
from pet_leather_studio.domain.errors import ResourceMissingError
from pet_leather_studio.domain.photo_relief import (
    BASE_THICKNESS_MM_RANGE,
    DEFAULT_FALLOFF_BAND_MM,
    DEPTH_MM_RANGE,
    FALLOFF_BAND_MM_RANGE,
    FALLOFF_BORDER_CLEARANCE_MM,
    FALLOFF_MAX_SLOPE,
    WIDTH_MM_RANGE,
    DepthSemantics,
    HeightMode,
    LocalAdjustment,
    ReliefParameters,
    suggested_falloff_band_mm,
)
from pet_leather_studio.infrastructure.reference_profile import (
    EXCLUDED_POINTS_LIMIT,
    excluded_points,
)
from pet_leather_studio.presentation.height_adjust_dialog import HeightAdjustDialog
from pet_leather_studio.presentation.mask_editor import MaskEditorDialog
from pet_leather_studio.presentation.section_dialog import CrossSectionDialog

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
        self.kill_timer = None
        self.close_after_job = False
        self._pending_adjustments: list[LocalAdjustment] = []
        self._pending_masks: list[tuple[np.ndarray, float, float]] = []
        self._job_clears_adjustments = False
        self._profiles_cache: list = []
        self._last_depth_shape: list[int] | None = None
        self._falloff_autoset: float | None = None  # 最近一次自动填入的建议带宽
        self._falloff_syncing = False  # 自动填入引发 valueChanged 的重入保护
        self._section_dialog: CrossSectionDialog | None = None
        self.setWindowTitle("照片 → 浮雕 · P2（人工蒙版 → 真实深度 → 受控浮雕化母版）")
        self.resize(1320, 860)
        content = QWidget()
        layout = QVBoxLayout(content)
        notice = QLabel(
            "流程：导入照片 → 人工蒙版 → 隔离环境真实深度推理（DA2-Small）→ 受控浮雕化母版。\n"
            "深度为相机视角相对前后关系，未做姿态归一化；预览与导出共用同一数值管线，"
            "母版仍需视觉评审通过后才能用于模具。模型未安装时推理会给出明确指引（产品路径不联网）。"
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
        controls.addLayout(form)

        controls.addWidget(QLabel("母版参数（预览与导出共用；生成前请先深度推理）"))
        master_form = QFormLayout()
        self.master_width = QDoubleSpinBox()
        self.master_width.setRange(WIDTH_MM_RANGE[0], WIDTH_MM_RANGE[1])
        self.master_width.setDecimals(1)
        self.master_width.setValue(60.0)
        self.master_width.valueChanged.connect(self._on_master_parameters_changed)
        master_form.addRow("宽度 mm（高度按图幅比）", self.master_width)
        self.height_mode = QComboBox()
        self.height_mode.addItem("显式深度 mm", HeightMode.EXPLICIT_DEPTH)
        self.height_mode.addItem("参考比例（需标定）", HeightMode.REFERENCE_RATIO)
        self.height_mode.currentIndexChanged.connect(self._sync_master_form)
        master_form.addRow("起伏上限来源", self.height_mode)
        self.master_depth = QDoubleSpinBox()
        self.master_depth.setRange(DEPTH_MM_RANGE[0], DEPTH_MM_RANGE[1])
        self.master_depth.setDecimals(2)
        self.master_depth.setValue(2.0)
        self.master_depth.valueChanged.connect(self.show_selected)
        master_form.addRow("起伏上限 mm（显式）", self.master_depth)
        self.ratio_hint = QLabel("—")
        self.ratio_hint.setWordWrap(True)
        master_form.addRow("参考比例换算", self.ratio_hint)
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._sync_master_form)
        master_form.addRow("参考标定", self.profile_combo)
        self.smoothing = QDoubleSpinBox()
        self.smoothing.setRange(0.0, 50.0)
        self.smoothing.setDecimals(1)
        self.smoothing.setValue(0.0)
        self.smoothing.valueChanged.connect(self._on_master_parameters_changed)
        master_form.addRow("平滑半径 mm（0=关）", self.smoothing)
        self.px_hint = QLabel("（待深度推理）")
        master_form.addRow("mm↔px 换算", self.px_hint)
        self.falloff_band = QDoubleSpinBox()
        self.falloff_band.setRange(FALLOFF_BAND_MM_RANGE[0], FALLOFF_BAND_MM_RANGE[1])
        self.falloff_band.setDecimals(1)
        self.falloff_band.setValue(DEFAULT_FALLOFF_BAND_MM)
        self.falloff_band.valueChanged.connect(self._on_master_parameters_changed)
        master_form.addRow("边缘过渡宽度 mm（0=关）", self.falloff_band)
        self.falloff_hint = QLabel("（待深度推理）")
        self.falloff_hint.setWordWrap(True)
        master_form.addRow("过渡带建议", self.falloff_hint)
        self.base_thickness = QDoubleSpinBox()
        self.base_thickness.setRange(BASE_THICKNESS_MM_RANGE[0], BASE_THICKNESS_MM_RANGE[1])
        self.base_thickness.setDecimals(1)
        self.base_thickness.setValue(3.0)
        master_form.addRow("底板厚度 mm（基准 0 另计）", self.base_thickness)
        controls.addLayout(master_form)

        self.adjust_button = QPushButton("局部调整…（刷选区域 · 偏移/过渡）")
        self.adjust_button.clicked.connect(self.edit_adjustments)
        controls.addWidget(self.adjust_button)
        self.adjust_status = QLabel("局部调整：0 处")
        controls.addWidget(self.adjust_status)
        self.master_button = QPushButton("生成母版（build-master · 隔离进程）")
        self.master_button.clicked.connect(self.build_master)
        controls.addWidget(self.master_button)
        self.calibrate_button = QPushButton("参考标定…（OBJ 测量有效起伏）")
        self.calibrate_button.clicked.connect(self.calibrate_reference)
        controls.addWidget(self.calibrate_button)
        self.excluded_button = QPushButton("查看参考排除点（红色标记被百分位裁掉的点）")
        self.excluded_button.clicked.connect(self.show_excluded_points)
        controls.addWidget(self.excluded_button)
        self.section_button = QPushButton("侧面截面…（穿过最高点的横截面）")
        self.section_button.clicked.connect(self.show_section)
        controls.addWidget(self.section_button)

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
            self.adjust_button,
            self.master_button,
            self.calibrate_button,
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
        self._refresh_profiles()
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
            if kind == "master" and data.get("input_method") == "photo_reconstruction":
                photo = self._maybe_get(data.get("photo_id"))
                mask = self._maybe_get(data.get("mask_id"))
                depth = self._maybe_get(data.get("depth_id"))
                return photo, mask, depth
        except (ValueError, OSError):
            return None, None, None
        return None, None, None

    def _maybe_get(self, revision_id: Any) -> dict[str, Any] | None:
        if not revision_id:
            return None
        try:
            return self.service.store.get(str(revision_id))
        except (ValueError, OSError):
            return None

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
        if depth is not None and depth.get("depth_shape"):
            self._last_depth_shape = [int(value) for value in depth["depth_shape"]]
            self._update_px_hint()
            self._update_falloff_hint()
        target = self.view.currentText()
        try:
            photo_master = kind == "master" and data.get("input_method") == "photo_reconstruction"
            if kind not in ("photo", "mask", "depth") and not photo_master:
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
            elif target == VIEW_3D and photo_master:
                self._add_master_mesh(data)
                message = self._master_text(data)
            elif target == VIEW_3D and depth is not None:
                self._add_depth_mesh(depth)
                message = self._depth_text(depth)
            else:
                message = "当前工程尚无该视图所需数据；请先生成蒙版或运行深度推理。"
            if photo_master and target != VIEW_3D:
                message = self._master_text(data)  # 母版详情始终展示（画布为所选上游视图）
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
        """三维中性预览：走 controlled_heights_mm（与导出同一数值管线，PH10 一致）。"""
        with np.load(self.service.store.directory(depth["id"]) / "depth.npz") as data:
            depths, valid = data["depth"], data["valid"]
        heights, _report = controlled_heights_mm(
            depths,
            valid,
            DepthSemantics(depth["depth_semantics"]),
            self._preview_parameters(),
            self._current_profile(),
            self._pending_masks,
        )
        heights = image_to_geometry_rows(heights)
        ny, nx = heights.shape
        width_mm = float(self.master_width.value())
        height_mm = width_mm * ny / nx
        xx, yy = np.meshgrid(np.linspace(0.0, width_mm, nx), np.linspace(0.0, height_mm, ny))
        grid = pv.StructuredGrid(xx, yy, heights)
        self.viewer.add_mesh(grid, color="ivory", smooth_shading=True)

    def _add_master_mesh(self, data: dict[str, Any]) -> None:
        mesh = pv.read(self.service.store.directory(data["id"]) / "preview.vtp")
        self.viewer.add_mesh(mesh, color="ivory", smooth_shading=True)

    def _preview_parameters(self) -> ReliefParameters:
        # StrEnum 经 QVariant 往返可能退化为 str，须用等值比较而非 is
        ratio = self.height_mode.currentData() == HeightMode.REFERENCE_RATIO
        profile_id = self.profile_combo.currentData() if ratio else None
        smoothing = self.smoothing.value()
        return ReliefParameters(
            width_mm=self.master_width.value(),
            depth_mm=self.master_depth.value(),
            height_mode=HeightMode.REFERENCE_RATIO if ratio else HeightMode.EXPLICIT_DEPTH,
            profile_id=profile_id,
            smoothing_radius_mm=smoothing if smoothing > 0.0 else None,
            base_thickness_mm=self.base_thickness.value(),
            falloff_band_mm=self.falloff_band.value(),
        )

    def _current_profile(self):
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return None
        for profile in self._profiles_cache:
            if profile.profile_id == profile_id:
                return profile
        return None

    def _refresh_profiles(self) -> None:
        """刷新参考标定下拉（损坏标定由 load 时显式报错，列表不静默混入）。"""
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("（未选择标定）", None)
        try:
            profiles = self.service.profiles.list_profiles()
        except (ValueError, OSError):
            profiles = []
        self._profiles_cache = list(profiles)
        for profile in self._profiles_cache:
            self.profile_combo.addItem(
                f"{profile.source_name} · 起伏 {profile.effective_relief_mm:.2f} / "
                f"参考宽 {profile.reference_width_mm:.1f} mm",
                profile.profile_id,
            )
        self.profile_combo.blockSignals(False)
        self._sync_master_form()

    def _sync_master_form(self) -> None:
        ratio = self.height_mode.currentData() == HeightMode.REFERENCE_RATIO
        self.master_depth.setEnabled(not ratio)
        profile = self._current_profile()
        if not ratio:
            self.ratio_hint.setText("—")
            return
        if profile is None:
            self.ratio_hint.setText("参考比例需先完成参考标定并在表单中选择。")
            return
        width = self.master_width.value()
        resolved = profile.effective_relief_mm / profile.reference_width_mm * width
        in_range = DEPTH_MM_RANGE[0] <= resolved <= DEPTH_MM_RANGE[1]
        hint = (
            f"有效起伏 {profile.effective_relief_mm:.2f} / 参考宽 "
            f"{profile.reference_width_mm:.1f} × 当前宽 {width:.1f} ⇒ 深度 {resolved:.2f} mm"
        )
        if not in_range:
            hint += "（超出工程范围，生成将被拒绝；请改显式深度）"
        self.ratio_hint.setText(hint)
        self._update_falloff_hint()

    def _update_falloff_hint(self) -> None:
        """R2：按解析起伏建议过渡带宽（未手动改过时自动填入），并受版边余量约束。"""
        if self._falloff_syncing:
            return
        mode = self.height_mode.currentData()
        if mode == HeightMode.REFERENCE_RATIO:
            profile = self._current_profile()
            if profile is None:
                self.falloff_hint.setText("（选标定后按解析深度给出建议带宽）")
                return
            depth = (
                profile.effective_relief_mm / profile.reference_width_mm * self.master_width.value()
            )
        else:
            depth = self.master_depth.value()
        suggested = suggested_falloff_band_mm(depth)
        cap_deg = math.degrees(math.atan(FALLOFF_MAX_SLOPE))
        note = f"按深度 {depth:.2f} mm 建议 ≥ {suggested:.1f} mm（最陡坡度 ≤{cap_deg:.0f}°）"
        valid = self._latest_depth_valid()
        if valid is not None and valid.any() and not valid.all():
            rows, cols = valid.shape
            dx = self.master_width.value() / max(cols - 1, 1)
            dy = dx * rows / max(rows - 1, 1)
            clearance = background_clearance_mm(valid, dx, dy)
            if math.isinf(clearance):
                note += "；主体已贴版边（版边本就不平；如需平边请修蒙版或加宽版面）"
            else:
                capped = clearance - FALLOFF_BORDER_CLEARANCE_MM
                if suggested > capped:
                    suggested = round(max(capped, 0.1), 1)  # 与 spin 小数位对齐，保自动跟随
                    note += (
                        f"；版边余量仅 {clearance:.1f} mm，收窄为 {suggested:.1f}"
                        f"（保留 {FALLOFF_BORDER_CLEARANCE_MM:.0f} mm 平边）"
                    )
                    if capped <= 0.1:
                        note += "——主体贴近版边，建议减小起伏或加宽版面"
                else:
                    note += f"；版边余量 {clearance:.1f} mm"
        if self.falloff_band.value() in (DEFAULT_FALLOFF_BAND_MM, self._falloff_autoset):
            self._falloff_syncing = True
            try:
                self.falloff_band.setValue(suggested)
            finally:
                self._falloff_syncing = False
            self._falloff_autoset = suggested
            note += "（已自动填入，可手改）"
        self.falloff_hint.setText(note)

    def _latest_depth_valid(self) -> np.ndarray | None:
        """当前照片最新深度修订的有效域（建议带宽的版边余量要用它）。"""
        data = self._selected()
        if data is None:
            return None
        _, _, depth = self._preview_chain(data)
        if depth is None:
            return None
        path = self.service.store.directory(depth["id"]) / "depth.npz"
        if not path.is_file():
            return None
        with np.load(path) as npz:
            return np.asarray(npz["valid"], dtype=bool)

    def _on_master_parameters_changed(self) -> None:
        self._sync_master_form()
        self._update_px_hint()
        self.show_selected()

    def _update_px_hint(self) -> None:
        shape = self._last_depth_shape
        if not shape or len(shape) != 2 or shape[1] < 2:
            self.px_hint.setText("（待深度推理）")
            return
        dx = self.master_width.value() / (shape[1] - 1)
        radius = self.smoothing.value()
        if radius <= 0.0:
            self.px_hint.setText(f"平滑关闭（dx={dx:.3f}mm）")
        else:
            self.px_hint.setText(f"σ≈{radius / dx:.1f}px（dx={dx:.3f}mm）")

    def _depth_colormap_png(self, depth: dict[str, Any]) -> Path:
        data = np.load(self.service.store.directory(depth["id"]) / "depth.npz")
        unit = unit_height(data["depth"], data["valid"], DepthSemantics(depth["depth_semantics"]))
        out = Path(self.service.store.root) / "tmp" / f"depth-{depth['id'][:8]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(self._height_colormap(unit), mode="RGB").save(out)
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

    @staticmethod
    def _master_text(data: dict[str, Any]) -> str:
        relief = data.get("relief", {})
        checks = data.get("geometry_checks", {})
        clamp = data.get("clamp_report", {})
        resolution = data.get("height_resolution", {})
        adjustments = data.get("adjustments", [])
        lines = [
            "母版 · photo_reconstruction；"
            f"宽 {data.get('width_mm')} × 高 {data.get('height_mm')} mm；"
            f"上游 depth {str(data.get('depth_id'))[:8]}",
            f"正面起伏 {relief.get('front_relief_mm')} mm；加底实体厚度 "
            f"{relief.get('solid_thickness_mm')} mm（底板 {relief.get('base_thickness_mm')} mm，"
            "浮雕基准 0）",
            f"起伏上限来源 {resolution.get('source')}"
            + (
                f"：{resolution.get('resolved_depth_mm')} mm"
                f"（标定 {str(resolution.get('profile_id'))[:12]}…）"
                if resolution.get("source") == "reference_ratio"
                else f"：{resolution.get('depth_mm')} mm"
            ),
            "重读校验：OBJ/STL 封闭；"
            f"顶面最大误差 {checks.get('top_surface_max_error_mm')} mm（门 1e-4）",
        ]
        falloff = data.get("falloff", {})
        if falloff.get("raised_points"):
            lines.append(
                f"边缘过渡：带宽 {falloff.get('band_mm')} mm；域外抬升 "
                f"{falloff.get('raised_points')} 点（最高 {falloff.get('max_raised_mm'):.2f} mm；"
                "主体内部高度未变，无垂直墙）"
            )
        slope = data.get("slope", {})
        if slope.get("max_overall_mm_per_mm") is not None:
            lines.append(
                f"坡度：全域最陡 {slope.get('max_overall_deg'):.1f}°；"
                f"边界过渡 {slope.get('boundary_max_deg'):.1f}°；"
                f"域内 {slope.get('interior_max_deg'):.1f}°"
                "（域内为输入深度固有断层，可用平滑半径缓解；建议带宽 ≥ 1.5×起伏）"
            )
        if clamp.get("clamped_points") or clamp.get("clamped_below_points"):
            lines.append(
                f"限幅改变：上限 {clamp.get('cap_mm')} mm；压顶 {clamp.get('clamped_points')} 点、"
                f"抬底 {clamp.get('clamped_below_points')} 点"
                f"（限幅前最大 {clamp.get('max_before_mm')} mm）"
            )
        if adjustments:
            summary = "；".join(
                f"{item.get('label')} {item.get('offset_mm'):+}mm"
                f"/过渡 {item.get('transition_mm')}mm"
                for item in adjustments
            )
            lines.append(f"局部调整 {len(adjustments)} 处：{summary}")
        lines.extend(data.get("warnings", []))
        return "\n".join(str(line) for line in lines if line)

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

    def edit_adjustments(self):
        data = self._selected()
        if data is None or data.get("kind") not in ("photo", "mask", "depth", "master"):
            QMessageBox.warning(self, "缺少深度", "请先选择照片链上的修订。")
            return
        _, _, depth = self._preview_chain(data)
        if depth is None:
            QMessageBox.warning(self, "缺少深度", "请先运行深度推理，再编辑局部调整。")
            return
        with np.load(self.service.store.directory(depth["id"]) / "depth.npz") as loaded:
            unit = unit_height(
                loaded["depth"], loaded["valid"], DepthSemantics(depth["depth_semantics"])
            )
        dialog = HeightAdjustDialog(self._height_colormap(unit), self)
        if dialog.exec() != HeightAdjustDialog.DialogCode.Accepted:
            return
        from pet_leather_studio.bootstrap.environment import data_root

        drafts = data_root() / "runtime" / "tmp"
        drafts.mkdir(parents=True, exist_ok=True)
        pending: list[LocalAdjustment] = []
        masks: list[tuple[np.ndarray, float, float]] = []
        for mask, offset, transition, label in dialog.regions:
            png = drafts / f"adjust-{uuid.uuid4().hex}.png"
            Image.fromarray(mask, mode="L").save(png)
            pending.append(
                LocalAdjustment(
                    label=label, region_png=str(png), offset_mm=offset, transition_mm=transition
                )
            )
            masks.append((mask, offset, transition))
        self._pending_adjustments = pending
        self._pending_masks = masks
        self._refresh_adjust_status()

    def _refresh_adjust_status(self) -> None:
        count = len(self._pending_adjustments)
        summary = "；".join(
            f"{item.label} {item.offset_mm:+.2f}mm" for item in self._pending_adjustments
        )
        self.adjust_status.setText(f"局部调整：{count} 处" + (f"（{summary}）" if summary else ""))

    def build_master(self):
        data = self._selected()
        if data is None or data.get("kind") not in ("photo", "mask", "depth", "master"):
            QMessageBox.warning(self, "缺少深度", "请先选择照片链上的修订。")
            return
        _, _, depth = self._preview_chain(data)
        if depth is None:
            QMessageBox.warning(self, "缺少深度", "请先运行深度推理，再生成母版。")
            return
        parameters = self._preview_parameters()
        if parameters.height_mode is HeightMode.REFERENCE_RATIO and not parameters.profile_id:
            QMessageBox.warning(
                self,
                "参考比例缺标定",
                "reference_ratio 需先完成参考标定（参考标定…）并在表单中选择；不会暗用参考比例。",
            )
            return
        try:
            parameters.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "参数无效", str(exc))
            return
        arguments = [
            "build-master",
            "--depth",
            str(depth["id"]),
            "--width-mm",
            f"{parameters.width_mm:g}",
            "--height-mode",
            parameters.height_mode.value,
            "--depth-mm",
            f"{parameters.depth_mm:g}",
            "--base-mm",
            f"{parameters.base_thickness_mm:g}",
            "--falloff-mm",
            f"{parameters.falloff_band_mm:g}",
        ]
        if parameters.smoothing_radius_mm is not None:
            arguments.extend(["--smoothing-mm", f"{parameters.smoothing_radius_mm:g}"])
        if parameters.profile_id:
            arguments.extend(["--profile", parameters.profile_id])
        for adjustment in self._pending_adjustments:
            arguments.extend(
                [
                    "--adjustment",
                    f"{adjustment.region_png}:{adjustment.offset_mm:g}"
                    f":{adjustment.transition_mm:g}:{adjustment.label}",
                ]
            )
        self._job_clears_adjustments = bool(self._pending_adjustments)
        self.start_job(arguments)

    def calibrate_reference(self):
        name, _ = QFileDialog.getOpenFileName(
            self,
            "选择参考实物 OBJ（相机正面假设；OBJ 无单位，默认按 mm 假设并记录）",
            str(self.project.parent),
            "OBJ (*.obj)",
        )
        if not name:
            return
        percentile, ok = QInputDialog.getDouble(
            self,
            "分位百分位",
            "percentile（99 为稳健默认；被裁点可用排除点视图核查）",
            99.0,
            0.1,
            100.0,
            1,
        )
        if not ok:
            return
        self.start_job(["calibrate-reference", "--obj", name, "--percentile", f"{percentile:g}"])

    def show_excluded_points(self):
        profile = self._current_profile()
        if profile is None:
            QMessageBox.warning(self, "缺少标定", "请先完成参考标定并在表单中选择。")
            return
        try:
            points = excluded_points(Path(profile.source_path), profile)
        except (ResourceMissingError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "无法核查排除点", str(exc))
            return
        self._apply_lighting()
        cloud = pv.PolyData(points)
        self.viewer.add_mesh(
            cloud, color="red", point_size=5, render_points_as_spheres=True, smooth_shading=False
        )
        self.viewer.view_xy()
        self.details.setPlainText(
            f"参考排除点（红色）· {profile.source_name}\n"
            f"百分位 {profile.percentile}；被裁 {profile.excluded_point_count} 点"
            f"（{profile.exclusion_fraction:.2%}）；"
            f"显示 {len(points)} 点（≤{EXCLUDED_POINTS_LIMIT}）\n"
            f"真实最高 {profile.true_max_z} mm、超出分位切面 {profile.true_excess_mm} mm"
            "（如鼻尖被裁：必要时提高百分位、换区域或改显式深度）\n"
            f"基准 {profile.datum_method} z={profile.datum_z}；区域 {profile.region_basis} "
            f"{tuple(round(value, 2) for value in profile.region)}"
        )

    def show_section(self) -> None:
        """R2：选中照片母版修订 → 侧面截面对话框（读已发布 heightfield.npz）。"""
        data = self._selected()
        if (
            not data
            or data.get("kind") != "master"
            or data.get("input_method") != "photo_reconstruction"
        ):
            QMessageBox.information(self, "侧面截面", "请先在历史中选中照片母版（master）修订。")
            return
        path = self.service.store.directory(data["id"]) / "heightfield.npz"
        if not path.is_file():
            QMessageBox.warning(self, "侧面截面", f"缺少 heightfield.npz：{path}")
            return
        with np.load(path) as npz:
            heights, valid = npz["heights_mm"], npz["valid"]
            dx_mm, dy_mm = float(npz["dx_mm"]), float(npz["dy_mm"])
        dialog = CrossSectionDialog(self)
        dialog.set_section(heights, valid, dx_mm, dy_mm)
        dialog.show()  # 非模态：可与三维视图并排对照
        self._section_dialog = dialog  # 持引用防回收

    def _height_colormap(self, unit: np.ndarray) -> np.ndarray:
        positions = np.linspace(0.0, 1.0, len(_COLORMAP_ANCHORS))
        colored = np.stack(
            [np.interp(unit, positions, _COLORMAP_ANCHORS[:, channel]) for channel in range(3)],
            axis=-1,
        ).astype(np.uint8)
        return colored

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
        # 受控定时器：任务结束时停止并释放。不能用 QTimer.singleShot 捕获 process——
        # 任务正常结束后 deleteLater，延迟回调再访问已销毁的 C++ 对象会抛异常。
        if self.kill_timer is not None:
            self.kill_timer.stop()
            self.kill_timer.deleteLater()
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(lambda: self._escalate_kill(process))
        self.kill_timer.start(5000)

    def _escalate_kill(self, process):
        # 只处理仍是当前任务的进程；已结束或已换任务的旧对象一律不碰
        if self.process is not process:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()

    def job_finished(self, code, status):
        process = self.process
        if process is None:
            return
        if self.kill_timer is not None:
            self.kill_timer.stop()
            self.kill_timer.deleteLater()
            self.kill_timer = None
        errors = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        self.process = None
        process.deleteLater()
        for widget in self._job_widgets:
            widget.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status.setText(
            "完成，新版本已保存" if code == 0 else "任务结束异常/已取消；旧版本保持不变"
        )
        if code == 0 and self._job_clears_adjustments:
            # 局部调整已随母版修订持久化（adjustment-*.png + region_sha256）
            self._pending_adjustments = []
            self._pending_masks = []
            self._job_clears_adjustments = False
            self._refresh_adjust_status()
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
