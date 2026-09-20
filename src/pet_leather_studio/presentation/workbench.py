"""Review imported geometry and versioned mold candidates. Heavy jobs run in QProcess."""

from __future__ import annotations

import sys
from pathlib import Path

import pyvista as pv
from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
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

from pet_leather_studio.application.mold_workbench import MoldWorkbench


class WorkbenchWindow(QMainWindow):
    def __init__(self, service: MoldWorkbench, project: Path):
        super().__init__()
        self.service, self.project = service, project
        self.process = None
        self.close_after_job = False
        self.setWindowTitle("Pet Leather Studio · v0.1 母版与模具候选")
        self.resize(1280, 850)
        content = QWidget()
        layout = QVBoxLayout(content)
        notice = QLabel(
            "当前：导入精细母版 → 查看 → 阴阳模候选。照片自动重建尚未实现。\n"
            "投影/皮厚为近似，所有导出均未验证实际压制效果。旧区域凸起仅保留作历史实验。"
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addWidget(QLabel(f"工程：{project}"))
        split = QSplitter()
        panel = QWidget()
        controls = QVBoxLayout(panel)
        self.import_button = QPushButton("导入浮雕母版 OBJ / STL / PLY")
        self.import_button.clicked.connect(self.import_master)
        controls.addWidget(self.import_button)
        form = QFormLayout()
        self.fields = {}
        for key, label, value, low, high in (
            ("width", "目标宽度 mm", 60, 5, 300),
            ("depth", "最大起伏 mm", 2, 0.05, 20),
            ("gap", "Z 向间隙 mm（试验值）", 1, 0.05, 10),
            ("backing", "背板厚 mm（未验强度）", 3, 1, 30),
            ("feature", "需保留最小特征 mm", 0.5, 0.05, 5),
        ):
            control = QDoubleSpinBox()
            control.setRange(low, high)
            control.setDecimals(2)
            control.setValue(value)
            self.fields[key] = control
            form.addRow(label, control)
        self.grid = QComboBox()
        self.grid.addItems(["64", "128", "256", "512"])
        self.grid.setCurrentText("128")
        form.addRow("候选采样长边（非精度保证）", self.grid)
        controls.addLayout(form)
        self.consent = QCheckBox("我确认主体正面朝 +Z，接受忽略背面/倒扣")
        controls.addWidget(self.consent)
        self.generate_button = QPushButton("从当前激活版本生成阴阳模候选")
        self.generate_button.clicked.connect(self.generate)
        controls.addWidget(self.generate_button)
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.clicked.connect(self.cancel_job)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.cancel_button)
        controls.addWidget(QLabel("历史版本（选中仅预览；激活才回退）"))
        self.versions = QComboBox()
        self.versions.currentIndexChanged.connect(self.show_selected)
        controls.addWidget(self.versions)
        self.activate_button = QPushButton("激活选中版本 / 回退（保留所有历史）")
        self.activate_button.clicked.connect(self.activate)
        controls.addWidget(self.activate_button)
        self.open_button = QPushButton("打开选中版本文件夹")
        self.open_button.clicked.connect(self.open_folder)
        controls.addWidget(self.open_button)
        self.mode = QComboBox()
        self.mode.addItems(["装配（上模半透明）", "阳模", "阴模"])
        self.mode.currentIndexChanged.connect(self.show_selected)
        controls.addWidget(self.mode)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        controls.addWidget(self.details)
        split.addWidget(panel)
        self.viewer = QtInteractor(split)
        self.viewer.set_background("#343b45")
        split.addWidget(self.viewer.interactor)
        split.setSizes([370, 900])
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
        self.status = QLabel("就绪；母版默认以无贴图中性材质显示")
        layout.addWidget(self.status)
        self.setCentralWidget(content)
        self.refresh()

    def refresh(self):
        self.versions.blockSignals(True)
        self.versions.clear()
        history = self.service.store.history()
        active = self.service.store.get()["id"] if history else None
        for row in history:
            prefix = "当前 " if row["id"] == active else ""
            self.versions.addItem(
                f"{prefix}{row['kind']} {row['created_at'][:19]} {row['id'][:8]}", row["id"]
            )
        if active:
            self.versions.setCurrentIndex(self.versions.findData(active))
        self.versions.blockSignals(False)
        self.show_selected()

    def show_selected(self):
        revision_id = self.versions.currentData()
        if not revision_id:
            return
        try:
            data = self.service.store.get(revision_id)
            folder = self.service.store.directory(revision_id)
            self.viewer.clear()
            self.viewer.enable_lightkit()
            if data["kind"] == "master":
                self.viewer.add_mesh(
                    pv.read(folder / "preview.vtp"), color="ivory", smooth_shading=True
                )
                message = (
                    f"导入母版：{data['source_name']}\n"
                    f"原网格三角形：{data['triangles']:,}\n预览为降采样；生成使用完整母版。\n"
                    "单位未确认；生成时通过目标宽度定义尺度。\n此版本不是照片重建结果。"
                )
            else:
                mode = self.mode.currentIndex()
                for name, color, visible in (
                    ("male", "#dcbb84", mode != 2),
                    ("female", "#80bdda", mode != 1),
                ):
                    if visible:
                        mesh = pv.read(folder / f"{name}.stl")
                        self.viewer.add_mesh(
                            mesh,
                            color=color,
                            smooth_shading=True,
                            opacity=0.35 if name == "female" and mode == 0 else 1,
                        )
                message = (
                    f"候选模具 · {data['nx']}×{data['ny']}\n"
                    f"网格间距 {data['dx_mm']:.3f} / {data['dy_mm']:.3f} mm\n"
                    f"覆盖率 {data['coverage']:.1%}\n"
                    f"采样初筛：{'初筛通过，需验细节' if data['sampling_sufficient'] else '不足'}\n"
                    + "\n".join(data["warnings"])
                )
            self.details.setPlainText(message)
            self.viewer.view_xy(negative=data["kind"] == "mold" and self.mode.currentIndex() == 2)
            self.viewer.reset_camera()
        except (ValueError, OSError, RuntimeError) as exc:
            self.details.setPlainText(f"预览失败：{exc}")

    def import_master(self):
        name, _ = QFileDialog.getOpenFileName(
            self,
            "选择浮雕主体；边框/挂环请另行确认",
            str(self.project.parent),
            "几何 (*.obj *.stl *.ply)",
        )
        if name:
            self.start_job(["import-master", name])

    def generate(self):
        if not self.consent.isChecked():
            QMessageBox.warning(self, "需要确认加工方向", "请先确认 +Z 朝向与上表面投影限制。")
            return
        if not self.versions.count():
            QMessageBox.warning(self, "缺少母版", "请先导入母版。")
            return
        arguments = ["generate", "--accept-top-projection", "--grid", self.grid.currentText()]
        for name, widget in self.fields.items():
            arguments.extend([f"--{name}", str(widget.value())])
        self.start_job(arguments)

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
        for widget in (self.import_button, self.generate_button, self.activate_button):
            widget.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("计算中（独立进程）；不覆盖当前版本，可取消…")
        process.start()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.job_finished(-1, QProcess.ExitStatus.CrashExit)

    def cancel_job(self):
        if self.process is not None:
            self.process.kill()
            self.status.setText("正在取消；历史成功版本保持不变")

    def job_finished(self, code, status):
        process = self.process
        if process is None:
            return
        errors = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        self.process = None
        process.deleteLater()
        for widget in (self.import_button, self.generate_button, self.activate_button):
            widget.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status.setText(
            "完成，新版本已保存" if code == 0 else "任务结束异常/已取消；请查看历史，旧文件保持不变"
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
                data = self.service.store.get()
                parameters = data.get("parameters", {})
                for name, widget in self.fields.items():
                    if f"{name}_mm" in parameters:
                        widget.setValue(parameters[f"{name}_mm"])
                if "grid_size" in parameters:
                    self.grid.setCurrentText(str(parameters["grid_size"]))
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
