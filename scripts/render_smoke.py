"""Qt + VTK 真机交互冒烟测试（PRD 3.2）。

流程：启动 → 显示测试网格 → 程序驱动的连续旋转/缩放/改窗口尺寸 →
周期性更新网格 → 到时后正常关闭。记录动作与异常日志到
runtime/logs/smoke-<tag>.log；正常退出码 0，任何异常/崩溃非 0。

用法：
  python scripts/render_smoke.py --duration 300 --tag long
  python scripts/render_smoke.py --duration 15 --tag quick3
"""

from __future__ import annotations

import argparse
import faulthandler
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RESULT_MARKER = "SMOKE_CLEAN_EXIT"


def build_test_mesh(step: int):  # noqa: ANN201 - pyvista PolyData，避免 UI 类型进签名
    """按步骤交替生成测试网格，覆盖网格更新路径。"""
    import pyvista as pv

    if step % 2 == 0:
        return pv.Sphere(radius=40.0)
    return pv.Cone(radius=30.0, height=80.0, resolution=64)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=300.0, help="交互时长（秒）")
    parser.add_argument("--tag", default="run", help="日志标签")
    args = parser.parse_args()

    log_dir = REPO_ROOT / "runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fault_file = log_dir / f"smoke-{args.tag}.fault"
    log_file = log_dir / f"smoke-{args.tag}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )
    logging.getLogger().handlers[0].formatter.converter = __import__("time").gmtime  # type: ignore[attr-defined]
    log = logging.getLogger("render_smoke")

    with fault_file.open("w") as fh:
        faulthandler.enable(file=fh)
        log.info("启动：duration=%ss tag=%s", args.duration, args.tag)

        try:
            import pyvista as pv
            import pyvistaqt
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication, QMainWindow

            log.info(
                "版本: PySide6=%s VTK=%s PyVista=%s pyvistaqt=%s Python=%s",
                __import__("PySide6").__version__,
                pv.vtk_version_info,
                pv.__version__,
                pyvistaqt.__version__,
                sys.version.split()[0],
            )

            app = QApplication(sys.argv[:1])
            win = QMainWindow()
            win.setWindowTitle(f"Pet Leather Studio 渲染冒烟 {args.tag}")
            plotter = pyvistaqt.QtInteractor(win)
            win.setCentralWidget(plotter)

            state = {"step": 0, "rot": 0.0, "phase": 0}

            def update_mesh() -> None:
                state["step"] += 1
                mesh = build_test_mesh(state["step"])
                plotter.clear_actors()
                plotter.add_mesh(mesh, color="burlywood", smooth_shading=True)
                log.info("网格更新 #%d", state["step"])

            update_mesh()  # 初始网格

            def rotate() -> None:
                plotter.camera.azimuth(2.5)
                plotter.camera.elevation(0.8 if (state["rot"] // 360) % 2 == 0 else -0.8)
                state["rot"] += 2.5
                plotter.render()

            def zoom_cycle() -> None:
                state["phase"] = (state["phase"] + 1) % 3
                factor = (1.15, 0.87, 1.0)[state["phase"]]
                plotter.camera.zoom(factor)
                plotter.render()
                log.info("缩放 phase=%d", state["phase"])

            def resize_cycle() -> None:
                sizes = ((1280, 800), (900, 600), (1100, 900))
                w, h = sizes[state["phase"] % len(sizes)]
                win.resize(w, h)
                log.info("窗口尺寸 %dx%d", w, h)

            def finish() -> None:
                log.info("到达时长，正常关闭")
                win.close()
                plotter.close()
                app.quit()

            rot_timer = QTimer(win)
            rot_timer.timeout.connect(rotate)
            rot_timer.start(100)  # 每秒约 10 次相机变化，持续驱动渲染

            slow_timer = QTimer(win)
            slow_timer.timeout.connect(lambda: (zoom_cycle(), resize_cycle()))
            slow_timer.start(5000)

            mesh_timer = QTimer(win)
            mesh_timer.timeout.connect(update_mesh)
            mesh_timer.start(30000)

            end_timer = QTimer(win)
            end_timer.setSingleShot(True)
            end_timer.timeout.connect(finish)
            end_timer.start(int(args.duration * 1000))

            win.show()
            code = app.exec()
            log.info("app.exec 返回 %s", code)
            log.info(RESULT_MARKER)
            return 0
        except Exception:
            log.exception("冒烟测试异常")
            return 2


if __name__ == "__main__":
    sys.exit(main())
