# 照片浮雕 P1 交付记录

日期：2026-09-20（首轮）/ 2026-09-20（复验）/ 2026-09-21（第二轮复验）；分支 `glm/photo-relief-p1`；发布标签见"版本及回退"（未推送远端）。

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

> 注：本轮蒙版为 M0.5 局部标注（评审 R3 指出覆盖不全），已被下方"PH09 复跑"取代，后者又被"PH09 第三轮（客观蒙版）"取代；本轮数据与证据原样保留。**当前阅读入口：第三轮（`20260921-100609`）。**

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

- `runtime/evidence/photo-p1/ph10-view-{0..3}-*.png`：GUI 四视图截图（复验轮重截，`viewer.screenshot()` 方式）。
- `runtime/evidence/photo-p1/ph09-rerun-20260920-181637-<key>-{mask-overlay,iso}.png`：复验轮蒙版叠加核对图与斜视渲染。
- `experiments/photo_relief/out/20260920-170915-*`、`out/20260920-181637-*`：两轮渲染、色图、高度场、机器报告。
- `workspace/photo-relief-p1/20260920-170915/<key>/`、`20260920-181637/<key>/`：两轮工程的修订库与原始数据。
- `runtime/backups/20260920-glm-photo-relief-p1-start.bundle`：改动前 Git bundle。

## 复验记录（2026-09-20，回应第三方验收评审）

背景：用户 GUI 实测"深度图/三维预览/蒙版均无画面输出"，第三方评审（`docs/reports/photo-relief-P1-acceptance-review.md`，结论"需要修改后复验"）提出 R1–R6。逐项处置：

| 项 | 评审发现 | 处置 | 验证 |
| --- | --- | --- | --- |
| R1 取消挂死 | SIGKILL 回收不了孙进程 | worker 以 `start_new_session=True` 独立进程组启动；CLI 收 SIGTERM 先 `killpg` 整组再退出；GUI 先 TERM、5 秒未退再兜底 KILL | 新增真实进程树测试 `test_sigterm_terminates_worker_process_tree` |
| R2 设备回退崩溃 | MPS `.to()` 失败后把标签字符串传给 torch | 计算设备与展示标签分离；MPS 失败回退 CPU 重跑并在 manifest 标注 `cpu（MPS 不可用回退）`；`--device mps` 不可用时拒绝静默回退（exit 3） | worker 代码路径 + manifest `device`/`device_requested` 字段 |
| R3 蒙版只覆盖局部 | 三张蒙版沿用 M0.5 局部标注 | 重制完整可见主体蒙版并复跑三样例（见下节） | 叠加图人工核对 + 新 PH09 运行 |
| R4 NaN 静默排除 | 主体内 NaN 被静默改为背景、有效域缩水 | 主体域内 NaN/Inf 一律拒绝发布（PH04），新增 1% 工程下限；原始浮点 `depth_raw.npy` 随修订保存供诊断 | `test_assemble_rejects_nan_inside_subject`、`test_assemble_rejects_tiny_coverage`、`test_assemble_preserves_raw_float_output` |
| R5 版本选择/下载线程 | 按 hash 字典序选版、`--revision` 未透传 hub | download 写 `selected.json` 显式记录选中版本；无选择文件时按 `downloaded_at` 取最新；`model_info`/`snapshot_download` 全程透传 revision | `test_registry_prefers_selected_then_download_time`、`test_download_threads_revision_to_hub` |
| R6 门禁清单退化（原义为 lint/format、GUI 联测与清单校验等多道门退化，清单仅其一） | 空文件列表/无权重/嵌套路径清单可用 | 清单为空、缺 `.safetensors`、含非顶层路径均拒绝使用；lint/format/mypy 与 GUI 套件作为门禁实际重跑（见下"复验测试计数"） | `test_registry_verify_rejects_degenerate_manifests` + 门禁命令输出 |

GUI 三视图空白的定位与修复：

1. 证据截图方式错误：PH10 截图原用 `QWidget.grab()`，抓不到 VTK 的 OpenGL 内容（得到空白 PNG），此前的"空白"证据不代表 GUI 画布空白。已改用 `viewer.screenshot()` 重截，四视图均含渲染内容（非背景像素占比 29.4%）。
2. 视图切换空白陷阱：选中 photo 修订后切蒙版/深度/三维视图时，严格链路缺数据 → 画布空白且无解释。预览链改为自动补齐同照片最新修订，详情注明"（注：所选修订缺该环节，已用同照片最新修订预览；编辑/推理以所选链路为准。）"；编辑/推理按钮仍走严格链路。新增 `test_view_switching_auto_uses_latest_chain`。

另：请在纯净终端（先 `conda deactivate`）复测 GUI；若 conda base 环境干扰 Qt/VTK 插件加载导致仍空白，属环境问题而非本轮代码，需单独排查。

复验测试计数（本机 macOS arm64）：ruff check / format 通过；mypy 8 文件通过；`tests/unit tests/architecture tests/integration -m 'not real_model'` **94 项通过**（上轮 87 + 新增 7）；`tests/gui` **7 项通过**（连续两轮）；真实模型 2 项通过；按评审原命令的 GUI+integration 组合 8 项通过。

计数口径更正：上轮"87 项"不含 GUI 6 项，表述不精确；本轮起区分——无模型测试 94 / GUI 7 / 真实推理 2。

评审提到的 GUI 联测波动（`test_workbench_generate_and_restore` history 1≠2）在修复后**本机未复现**（该组合连续两轮 7 项通过、按评审原命令 8 项通过）；不否认对方环境观察到，仅如实记录未复现。

## PH09 复跑（R3：完整主体蒙版）

蒙版重制：`experiments/photo_relief/run_p1_three_photos.py` 内联 `FULL_SUBJECT_POLYGONS`（AI 辅助定位轮廓 + `mask-overlay.png` 红色半透明叠加图人工核对；坐标定义于原图像素系、按工作图尺寸等比缩放）。M0.5 旧标注文件原样保留但不再引用；旧运行 `20260920-170915/` 与旧 out/ 目录未改动。

新运行 `workspace/photo-relief-p1/20260920-181637/`，机器数据 `experiments/photo_relief/out/20260920-181637-report_data.json`（MPS 真实推理，语义与预览参数同上轮）：

| 样本（蒙版口径） | 蒙版覆盖（旧→新） | 深度有效覆盖 | 推理耗时 | 全程 |
| --- | --- | --- | --- | --- |
| 短毛犬（头 + 可见上身） | 17.1% → 56.3% | 56.3% | 2.20 s | 11.5 s |
| 猫（双耳 + 面部 + 身体） | 21.3% → 50.3% | 50.3% | 2.55 s | 11.1 s |
| 长毛犬（全身，含尾巴） | 39.0% → 49.5% | 49.5% | 0.98 s | 8.4 s |

逐张错误归因（区分蒙版错误 / 深度错误 / 低分辨率限制）：

- 短毛犬：蒙版完整（头/耳/口鼻/上身，叠加图核对）；深度前后关系正确（鼻/头高于远侧）；起伏柔和属 148 px 低分辨率限制，非蒙版或深度错误。
- 猫：蒙版完整（双耳+面部+身体）；底边阶梯源于主体在原图底边被裁切（画面内容至此为止，非蒙版错误）；浮雕偏浅属浅色毛发 + 低分辨率限制；左下角水印部分落在蒙版边缘内，可能带来轻微伪起伏（photo manifest 早已警告水印）。
- 长毛犬：全身保留（头、躯干、四肢、尾巴整体轮廓，叠加图核对）；毛流纹理不可辨属模型粒度 + 低分辨率限制；未见整体正反颠倒。

叠加图与斜视渲染证据：`runtime/evidence/photo-p1/ph09-rerun-20260920-181637-<key>-{mask-overlay,iso}.png`。视觉评审仍为 pending，最终以用户在 GUI 中勾选为准。

## 第二轮复验（2026-09-21，回应复验报告 caaf5d3）

背景：第三方复验（`docs/reports/photo-relief-P1-reacceptance-caaf5d3.md`，结论"基础工程明显改善，暂不签署 R1–R6 全部关闭"）提出 F1–F4。逐项处置：

| 项 | 评审发现 | 处置 | 验证 |
| --- | --- | --- | --- |
| F1 [P1] 取消后悬空回调 | 5 s QTimer 兜底 lambda 捕获的 QProcess 在任务正常结束后已被 deleteLater，触发 `libshiboken: Internal C++ object ... already deleted` | 兜底改为受控 QTimer（父对象为窗口、单射）；`job_finished` 先停表清空再读输出；回调加 `self.process is not process` 身份检查与 NotRunning 防护；worker 进程组 TERM 后 2 s 未退整组 SIGKILL | `test_cancel_job_stops_kill_timer_and_survives_window`（跨过 5.6 s 兜底窗口）、`test_close_window_during_job_cancels_then_closes`、`test_start_job_during_pending_cancel_is_ignored`、`test_sigterm_escalates_to_sigkill_for_ignoring_worker`（KILL 升级实测 ~2.2 s） |
| F2 [P2] 选中指针不更新/静默回退 | `cmd_download` 已存在分支不重校验、不更新 `selected.json`；locate 遇失效 selected 静默回退最新版 | 已存在分支改为先重校验、通过后以 tmp+`os.replace` 原子更新 `selected.json`（校验失败不切指针）；selected 指向缺失修订时抛 `ResourceMissingError`，无 selected 才按 `downloaded_at` 取最新 | `test_registry_selected_pointing_to_missing_revision_errors`、`test_download_reselect_updates_pointer_and_keeps_it_on_verify_failure` |
| F3 [P2] 蒙版不完整/叠加图不可核对 | 犬两张主体部位（右耳、头顶毛、右侧身体、爪部）在蒙版外、背景误纳；叠加图整片高不透明度红 | 三张蒙版全部改为像素级客观测定（见下节），叠加图改半透明红 + 黄色边界线；重新执行三样例。猫虽未被评审点名，第三轮复核确认第一轮目测轮廓切掉耳尖/额头/右侧毛发（约 11% 主体），一并重制 | 逐行/逐列外沿核对（残差均在浅色绒毛过渡带或 ≤6 px 不连通绒毛簇）+ 叠加图视觉模型逐面板复核 |
| F4 [P2] 发布标签被移动 | `photo-relief-p1` 从 93f87df 移到 caaf5d3，违反"新增唯一标签、不移动旧标签"约定 | 拆分为唯一标签 `photo-relief-p1-original`（93f87df）/ `photo-relief-p1-r1`（caaf5d3）/ `photo-relief-p1-r2`（本轮提交），删除被移动的 `photo-relief-p1`；旧标签未动（见"版本及回退"） | `git tag -l --format=...` 逐标签对照提交 |

第二轮复验测试计数（本机 macOS arm64）：ruff check 通过、ruff format 通过（66 文件）、mypy 8 文件通过；`pytest tests -m 'not real_model'` **107 项通过**（无模型 97 + GUI 10，较上轮 +6：F1×4、F2×2）；真实模型冒烟 2 项上轮通过、本轮未重跑（本轮改动不触及推理内核）。

## PH09 第三轮（客观蒙版；当前阅读入口）

新运行 `workspace/photo-relief-p1/20260921-100609/`，机器数据 `experiments/photo_relief/out/20260921-100609-report_data.json`（MPS 真实推理，语义与预览参数同上轮）：

| 样本（蒙版口径） | 蒙版覆盖（上轮→本轮） | 深度有效覆盖 | 推理耗时 | 全程 |
| --- | --- | --- | --- | --- |
| 短毛犬（头 + 可见上身） | 56.3% → 37.4% | 37.4% | 3.29 s | 16.1 s |
| 猫（双耳 + 面部 + 身体，含底边胸口） | 50.3% → 63.0% | 63.0% | 2.14 s | 11.9 s |
| 长毛犬（全身） | 49.5% → 48.9% | 48.9% | 2.25 s | 11.7 s |

方法与核对：

- 客观测定管线（取代两轮均有偏差的目测坐标）：四角 12×12 中位背景色 → 欧氏距离阈值 40 前景 → 最大连通域（丢弃水印碎块）→ `binary_fill_holes`（耳间/胸前浅色毛）→ `binary_closing` 2 px 平滑凹口后与原前景取并（不削细毛尖）→ Moore 轮廓追迹 + Douglas-Peucker 简化；多边形栅格化回填与主体掩码 IoU ≥ 0.985 自检。多边形内联于脚本 `FULL_SUBJECT_POLYGONS`（坐标定义于原图像素系）。
- 与上轮差异：短毛犬去掉误纳的背景条/穹顶后覆盖回落至真实主体 37.4%；猫补回耳尖（y=0）/额头/右侧毛发并含底边胸口毛（gettyimages 半透明水印叠在毛上而非背景，按主体保留）升至 63.0%；长毛犬 48.9% 与上轮持平。
- 边界核对：逐行/逐列对比蒙版外沿与阈值前景外沿（容差 3 px）——残差或位于浅色绒毛 thr35↔thr50 过渡带内（蒙版外沿介于两阈值外沿之间），或为 ≤6 px 的不连通绒毛簇（thr40 连通域分析弃置）；无整块主体缺失、无背景大块误纳。
- 叠加图（半透明红 + 黄边界）经视觉模型逐面板复核：短毛犬耳部完整、无背景穹顶/背景条；猫双耳含耳尖、面部、右侧身体、底部胸口均在界内；长毛犬头顶/背线/臀部/前爪在界内、腿间空隙为凹口。视觉评审仍为 pending，最终以用户在 GUI 中勾选为准。
- 证据：`runtime/evidence/photo-p1/ph09-r3-20260921-100609-<key>-{mask-overlay,iso}.png`。

## 用户复测指引（GUI）

```bash
conda deactivate   # 避免 base 环境干扰 Qt/VTK
scripts/dev.sh run --frozen pet-leather-studio --project workspace/photo-relief-p1/20260921-100609/short_hair_dog photo
```

注意 `--project` 必须在子命令 `photo` 之前。窗口内切换 原图/蒙版/深度图/三维中性预览 四视图；选中 photo 修订切其他视图会自动用同照片最新修订预览并在详情注明。前两轮工程（`20260920-170915/`、`20260920-181637/`）原样保留可对比。

## 未实现与限制

- P2（参考高度标定 PH05、受控浮雕化、母版 OBJ/STL 导出 PH06）与 P3（毛流/细纹 PH12）未开始。
- 蒙版只定义有效域，不改变推理输入（保留场景上下文，manifest 记录 `mask_used_for_inference=False`）。
- 深度不做姿态归一化/正面化；预览与深度未通过视觉评审，不能当作已完成母版。
- CI 改动未在远端 Linux 环境实际运行验证。

## 版本及回退

旧标签 `baseline-before-mold-refocus-20260920`、`mold-workbench-v0.1.0` 未移动。第二轮复验指出首轮复验曾把 `photo-relief-p1` 从交付提交移动到复验提交，违反"新增唯一标签、不移动旧标签"约定；本轮更正为拆分唯一标签：`photo-relief-p1-original`（93f87df，首轮交付）、`photo-relief-p1-r1`（caaf5d3，首轮复验修复）、`photo-relief-p1-r2`（本轮提交，第二轮复验修复），并删除被移动过的 `photo-relief-p1`。所有标签均未推送远端，移动仅影响过本地；改动前状态另存 Git bundle（见上）。按约定本轮不推送远端。
