# M0 渲染选型报告 —— Qt + VTK 真机冒烟（PRD §3.2）

日期：2026-09-18
结论：**通过**。选定 Qt Widgets（PySide6）+ PyVista/pyvistaqt（VTK）桌面组合。

## 锁定版本矩阵（M1 期间不升级）

| 组件 | 版本 | 备注 |
| --- | --- | --- |
| macOS | 14.2.1（Darwin 23.2.0, arm64） | Apple silicon, 8 核, 16GB |
| Python | 3.11.16 | 项目本地 .venv（uv 管理） |
| PySide6 | 6.11.2 | Qt Widgets 桌面 UI |
| VTK | 9.7.0 | 渲染后端 |
| PyVista | 0.49.0 | 网格构建/离屏渲染 |
| pyvistaqt | 0.13.1 | QtInteractor 桥接 |

（与 `runtime/system_profile.json` 一致；uv.lock 已提交可复现。）

## 测试方法

`scripts/render_smoke.py`：QMainWindow + QtInteractor，QTimer 程序驱动——
每 100ms 相机方位角 +2.5°/俯仰 ±0.8°（持续渲染负载）、每 5s 缩放循环 +
窗口尺寸切换（1280×800 / 900×600 / 1100×900）、每 30s 更新网格（球↔锥，
覆盖网格重建路径）；faulthandler 落盘；正常退出打 `SMOKE_CLEAN_EXIT` 标记。

`scripts/run_render_smoke.sh`：1×300s 长跑 + 10×15s 快启停；记录每次退出码到
`runtime/smoke/*.exit`；前后比对 `~/Library/Logs/DiagnosticReports` 新增崩溃报告。

## 实际运行命令

```bash
scripts/run_render_smoke.sh
```

## 测试结果

| 项 | 结果 |
| --- | --- |
| 300s 长跑（连续旋转/缩放/改尺寸） | 退出码 0，`SMOKE_CLEAN_EXIT` |
| 长跑动作计数（日志） | 网格更新 11 次、缩放循环 60 次、窗口尺寸切换 60 次 |
| 10×15s 快启停（quick1–10） | 退出码全部 0，全部含 `SMOKE_CLEAN_EXIT` |
| CLEAN_EXIT 标记 | 11/11 |
| 新增 macOS 崩溃报告（.ips/.panic） | 0 |

## 手工演示步骤

1. `scripts/dev.sh run python scripts/render_smoke.py --duration 30 --tag demo`
   —— 弹出窗口：自动旋转、周期缩放/改尺寸、每 30s 换网格，30s 后自动关闭，
   终端退出码 0。
2. `cat runtime/logs/smoke-demo.log | tail -2` —— 可见 `SMOKE_CLEAN_EXIT`。

## 已知限制

- 程序驱动（QTimer）替代人工鼠标交互——PRD §3.2 认可的等效方式；后续里程碑
  出现真实编辑交互后再补人工操作记录。
- 快启停每次含 Python 解释器 + VTK 初始化，单次 ~8s 开销，属已知正常水平。
- 未做长时间（>5min）与多窗口并发压力——M1 接入真实工作流后视需要补。
