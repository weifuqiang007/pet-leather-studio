# 照片浮雕 P1 交付记录

日期：2026-09-20；分支 `glm/photo-relief-p1`；发布标签 `photo-relief-p1`（未推送远端）。

## 完成范围

按实施路径文档及 Codex 答复口径交付 P1：人工蒙版 + 真实深度 + 保持输入视角 + 本地版本链。

- 照片导入：EXIF 方向归一化、原图只读副本、工作图 PNG；低分辨率/坏文件明确警告或拒绝（PH01）。
- 人工蒙版编辑器：画笔/擦除/撤销/重做/缩放，阈值亮度初稿；manifest 记录 `manual` 或 `threshold_assisted`，不伪装成 AI 分割（PH02）。
- 真实深度：Depth Anything V2 Small（transformers 实现）在项目本地 `.venv-photo/` 隔离进程运行，MPS 优先、不可用回退 CPU 并在 manifest 明示设备；`local_files_only=True`，产品路径零联网（PH11）。
- 中性三维预览：与后续母版共用 `algorithms.relief_height` 数值管线；原图/蒙版/深度/三维四视图，正侧斜视与两种光照（PH10）。
- 版本链：photo→mask→depth 逐修订 SHA-256 存储、可追溯、可激活回退；推理失败/取消/崩溃不发布新版本（PH07/PH08）。
- 模具接缝修复：master/mold 分派不再写死 `source_import`；photo/mask/depth 修订不得当作 master；未知修订种类友好报错。
- 模型安装走显式命令 `scripts/setup_photo_models.py`（bootstrap/download/verify/freeze-lock/info），下载物全部落在项目内。

保留旧 OBJ 导入、阴阳模与版本回退功能；此前 26 项测试全部保留并通过。

## 实际验证

本机执行（macOS arm64，真实 Qt 图形会话）：

```bash
scripts/dev.sh run --frozen ruff check .
scripts/dev.sh run --frozen ruff format --check .
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
scripts/dev.sh run --frozen pytest -p no:pytest-qt tests/unit tests/architecture tests/integration -m 'not real_model'
scripts/dev.sh run --frozen pytest tests/gui
scripts/dev.sh run --frozen pytest tests/integration/test_real_model_depth.py
```

结果：Ruff 检查通过；61 个文件格式通过；mypy 8 个文件通过；单测/架构/集成 87 项通过；GUI 6 项通过；真实模型冒烟 2 项通过（29.28 秒）。

CI 新增 `libgl1`/`libxkbcommon0` 安装步骤并运行 integration（排除 `real_model`）。**本轮未推送远端，Linux CI 实际结果未验证**，不得宣称 CI 通过。

## 模型与下载位置

- 推理环境 `.venv-photo/`：实测 730.2 MB（torch 2.14.0 CPU 版、transformers 4.57.6、huggingface-hub 0.36.2 等）。体积为实测值，不承诺 0.5–1 GB；实际版本冻结在 `requirements/photo-inference.lock`（含安装命令）。
- 权重 `models/hf/depth-anything-v2-small-hf/5426e4f0f36572d16453bbda7a8389317b1bef99/`：99,175,385 字节（99.18 MB），低于 1 GB（十进制，不含运行环境）预算。manifest 含逐文件 SHA-256（3 个文件校验 OK）、revision、下载 endpoint、Apache-2.0（`license_source` 注明为命令行声明，以模型卡为准、须人工核对）。
- 下载源依次尝试 huggingface.co 与 hf-mirror.com；文件列表缺权重自动换源；一致性由本地 SHA-256 清单兜底。
- 磁盘余量：安装前 319 GiB → 安装后 341.3 GB（≈318 GiB，`info` 命令报告）。

## 验收对应

| 门 | 状态 | 证据 |
| --- | --- | --- |
| PH01 照片导入 | 通过 | `tests/unit/test_photo_io.py` |
| PH02 蒙版坐标/编辑 | 通过 | `tests/unit/test_mask_coordinates.py`、`tests/gui/test_mask_editor.py` |
| PH03 深度方向/翻转 | 通过 | `tests/unit/test_relief_height.py` |
| PH04 有效域与起伏精度 | 通过 | `tests/unit/test_relief_height.py`（≤1e-4 mm） |
| PH05 参考标定 | P2 延后 | 未实现 |
| PH06 几何导出一致性 | P2 延后 | 未实现（中性预览的几何行变换已有单测） |
| PH07 链路可追溯/模具接缝 | 通过 | `tests/integration/test_photo_revisions.py` |
| PH08 失败不发布/可重跑 | 通过 | `tests/integration/test_photo_jobs.py`、`tests/gui/test_photo_workbench.py` |
| PH09 三张真实照片 | 真机完成，见下节 | `experiments/photo_relief/` |
| PH10 GUI 四视图 | 通过 | `tests/gui/test_photo_workbench.py` + 截图 |
| PH11 模型清单/离线 | 通过 | `tests/integration/test_photo_inference.py` |
| PH12 精细效果评审 | P3 延后 | 现有小图 `blocked_by_input_quality` |

## PH09：三张真实照片

脚本 `experiments/photo_relief/run_p1_three_photos.py`；运行 `workspace/photo-relief-p1/20260920-170915/`；机器数据 `experiments/photo_relief/out/20260920-170915-report_data.json`。三张均为 MPS 设备真实 DA2-Small 推理（transformers 4.57.6），语义 `relative_larger_nearer`，预览宽 80 mm / 起伏上限 2 mm。

| 样本 | 输入 | 蒙版覆盖 | 深度有效覆盖 | 推理耗时 | 全程 |
| --- | --- | --- | --- | --- | --- |
| 短毛犬 | 148×148 | 17.1% | 17.1% | 1.62 s | 5.7 s |
| 猫 | 148×148 | 21.3% | 21.3% | 3.32 s | 9.5 s |
| 长毛犬 | 205×148 | 39.0% | 39.0% | 1.06 s | 4.4 s |

逐张记录（门 PH09 要求的四项）：

- 前后关系：三张深度均为主体内连续的单目相对前后关系，近处（鼻/头/前躯）高于远处，未见整体正反颠倒。
- 错误凹凸：语义为相机视角，未做姿态归一化——趴卧/蜷卧样本身体厚度会被映射为起伏，警告已写入各 depth manifest。
- 裁切：蒙版外全部无效（有效覆盖=蒙版覆盖），蒙版为 M0.5 标注多边形并集填充（AI 辅助定位 + 人工核对，manifest notes 如实记录）。
- 细节限制：三张输入均低于 800 px（photo manifest 逐张警告）；渲染检查（等距视图）显示几何完整、起伏平滑、无空洞/尖刺/破碎，但轮廓辨识度弱、边缘有锯齿，毛流/细纹不可辨——与低分辨率输入一致，精细验收 `blocked_by_input_quality`（PH12）。

渲染离屏 6 视图×3 张（正/侧/斜 × 三点光组/头部单光源）+ 深度色图 + 高度场 npz，均在 `experiments/photo_relief/out/20260920-170915-<key>/`。视觉评审仍为 pending，最终以用户在 GUI 中勾选为准。

## 本地证据（未加入 Git，重新获取仓库不会包含）

- `runtime/evidence/photo-p1/ph10-view-{0..3}-*.png`：GUI 四视图截图。
- `experiments/photo_relief/out/20260920-170915-*`：渲染、色图、高度场、机器报告。
- `workspace/photo-relief-p1/20260920-170915/<key>/`：三个工程的修订库与原始数据。
- `runtime/backups/20260920-glm-photo-relief-p1-start.bundle`：改动前 Git bundle。

## 未实现与限制

- P2（参考高度标定 PH05、受控浮雕化、母版 OBJ/STL 导出 PH06）与 P3（毛流/细纹 PH12）未开始。
- 蒙版只定义有效域，不改变推理输入（保留场景上下文，manifest 记录 `mask_used_for_inference=False`）。
- 深度不做姿态归一化/正面化；预览与深度未通过视觉评审，不能当作已完成母版。
- CI 改动未在远端 Linux 环境实际运行验证。

## 版本及回退

旧标签 `baseline-before-mold-refocus-20260920`、`mold-workbench-v0.1.0` 未移动。新标签 `photo-relief-p1` 固定本轮代码；改动前状态另存 Git bundle（见上）。按约定本轮不推送远端。
