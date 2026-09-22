# 照片浮雕 P2 交付记录

日期：2026-09-22；分支 `glm/photo-relief-p2`；发布标签 `photo-relief-p2`（只新增；旧标签未动）。

## 完成范围

按实施路径文档及已批准计划交付 P2：**参考高度标定（PH05）、受控浮雕化、局部结构调整、母版 OBJ/STL 导出（PH06）**。

- 参考标定：参考 OBJ 测量"基准→分位裁剪高"为有效起伏，包围盒 Z 跨度单独记录仅作历史对照（永不自动套用 14.93%）；真实极值与被裁点数保留，GUI 红点视图可核查"鼻尖被裁"；区域/基准/百分位/排除比例全部字段落盘（PH05）。
- 受控浮雕化：`controlled_heights_mm` 数值管线统一处理 unit 高度→有效域感知平滑（mm 半径，界面显示 px 换算）→上限解析（explicit_depth / reference_ratio）→限幅→局部调整；预览与导出共用同一函数（PH10 一致）；限幅改变写入 report 并在界面展示，不静默截断。
- 同比例模式：有效起伏/参考宽×当前宽；越出 (0.05, 20) mm 报错提示改显式深度；无标定（或缺损）拒绝该模式，只开放 explicit_depth。
- 局部结构调整：刷选区域 + 偏移/过渡参数（过渡即高斯过渡，防尖峰）、区域增删与撤销；调整随母版修订持久化（`adjustment-*.png` + region SHA-256）。
- 母版导出：修订内平铺 `master.obj`/`master.stl`（加底水密实体，trimesh）、`master.vtp`（正面母版，基准 0 底板另计）、`preview.vtp`（≤15 万面 LOD，与模具路径同形态）、`heightfield.npz`；**发布前重读 OBJ+STL 校验**（水密/正体积/边界/逐列顶面 ≤1e-4 mm），失败即丢弃不产生修订。
- 版本链：photo→mask→depth→master 逐修订 SHA-256 可追溯、可激活回退；kind="master"、input_method="photo_reconstruction"；master.vtp 可直接进现有阴阳模生成（input_method 继承）。

P1 全部功能（导入/蒙版/真实深度/四视图/失败不发布）保留并通过回归。

## 实现阶段与修改路径

五个提交（基线 `glm/photo-relief-p1` @ `1e7563d`，改动合计 17 文件 +2559/−65）：

| 提交 | 阶段 | 主要路径 |
| --- | --- | --- |
| `7ca97ac` | ① domain + algorithms | `domain/photo_relief.py`（`ReferenceProfile`/`LocalAdjustment`、`ReliefParameters` 增 `base_thickness_mm` 及范围矩阵）；`algorithms/relief_height.py`（`ratio_depth_mm`/有效域感知平滑/`apply_local_adjustments`/`controlled_heights_mm`） |
| `afe4fe9` | ② infrastructure | `infrastructure/reference_profile.py`（`measure_reference`/`excluded_points`/`ReferenceProfileStore`，app 级 `profiles/`）；`infrastructure/photo_geometry.py`（`build_master` + 发布前重读校验）；`bootstrap/environment.py` + `.gitignore` 增 `profiles/` |
| `d229791` | ③ application + CLI | `domain/photo_ports.py`（几何/标定端口）；`application/photo_workbench.py`（`build_master` 用例：上游校验/参数与逐调整 validate/ratio 加载 profile/publish-discard）；`bootstrap/workbench.py` 组装；`__main__.py` 新子命令 `build-master`/`calibrate-reference`/`photo-profiles` |
| `d90e92f` | ④ GUI | `presentation/photo_panel.py`（母版参数表单/参考标定/排除点红点视图/master 视图分派/预览走导出同管线）；新 `presentation/height_adjust_dialog.py` |
| 本提交 | ⑤ 实验 + 文档 | `experiments/photo_relief/run_p2_masters.py`、`run_p2_relief_tiers.py`（入库；产物 out/ 不入库）；本报告；实施路径文档回写 |

## 实际验证

本机执行（macOS arm64，真实 Qt 图形会话）：

```bash
scripts/dev.sh run --frozen ruff check .        # rc=0
scripts/dev.sh run --frozen ruff format --check .   # rc=0（75 文件）
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application   # rc=0（8 文件）
scripts/dev.sh run --frozen pytest tests -m 'not real_model'   # rc=0：155 passed, 2 deselected
```

计数口径（三类分开）：**无模型 140 + GUI 15 = 155**（P1 末 112 → +43；GUI 10→15）。真实模型冒烟 2 项（real_model）P1 第三轮通过、**本轮未重跑**——P2 改动不触及推理内核，母版实验复用既有 depth 修订。

真机实验与 GUI 手测：

```bash
scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_masters.py       # rc=0（标定 + 3 explicit + 1 ratio 母版）
scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_relief_tiers.py  # rc=0（80/100/120 三档）
scripts/dev.sh run --frozen python runtime/gui_p2_smoke.py                          # rc=0 {"ok": true, 4 项断言}
```

GUI 手测断言（真实短毛犬工程）：explicit/ratio 两张母版三维视图均 actors=1 且详情含"母版/重读校验"（ratio 另含 8.35 与标定 id）；表单选真实标定后换算提示实时给出 `有效起伏 2.68 / 参考宽 19.3 × 当前宽 60.0 ⇒ 深度 8.35 mm`；排除点视图对真实 SubTool3 画出红色被裁点（actors=1）。

## 验收对应

| 门 | 状态 | 证据 |
| --- | --- | --- |
| PH01 照片导入 | 通过（P1 回归） | `tests/unit/test_photo_io.py` |
| PH02 蒙版坐标/编辑 | 通过（P1 回归） | `tests/unit/test_mask_coordinates.py`、`tests/gui/test_mask_editor.py` |
| PH03 深度方向/翻转 | 通过（P1 回归） | `tests/unit/test_relief_height.py` |
| PH04 有效域与起伏精度 | 通过 | `tests/unit/test_relief_height.py`（含上限解析/clamp 冒泡/局部调整，≤1e-4 mm） |
| PH05 参考标定 | **通过** | `tests/unit/test_reference_profile.py`（10 项）+ 真机 SubTool3 标定（下节） |
| PH06 几何导出一致性 | **通过** | `tests/integration/test_photo_geometry.py`（重读水密/正体积/边界/朝向/逐列顶面 ≤1e-4 mm/失败路径） |
| PH07 链路可追溯 | 通过 | `tests/integration/test_photo_revisions.py`（photo→mask→depth→master 链；篡改上游拒绝）、`test_photo_geometry.py`（master.vtp→阴阳模 input_method 继承） |
| PH08 失败不发布/可重跑 | 通过 | `tests/integration/test_photo_jobs.py`（build-master/calibrate-reference 返回码）、`test_photo_geometry.py`（校验失败 discard）、`tests/gui/test_photo_workbench.py` |
| PH09 三张真实照片 | 真机完成（P1 第四轮 depth 修订复用） | `experiments/photo_relief/`、本报告下节 |
| PH10 GUI 视图/预览=导出 | 通过 | `tests/gui/test_photo_workbench.py`（含 master 视图/ratio 校验/参数拼装/调整对话框/排除点，+5）+ 截图 |
| PH11 模型清单/离线 | 通过（P1 回归） | `tests/integration/test_photo_inference.py` |
| PH12 精细效果评审 | P3 延后 | 现有小图 `blocked_by_input_quality` |

## 参考标定记录（真实实物，PH05）

标定对象为 14.93% 数字的来源实物 `images/test1_result/1_SubTool3.obj`（2,999,988 点；images/ gitignored 不上远端，本机路径）。profile 存 app 级 `profiles/ref-5c1ae382ab802ef6.json`（与 GUI 下拉同一存储库，gitignored）。

| 字段 | 值 |
| --- | --- |
| profile_id | `ref-5c1ae382ab802ef6`（"ref-"+sha256(source_sha256\|region\|percentile)[:16]，确定性：同参数重跑覆盖同一文件） |
| source_sha256 | `6376ec06…7550`（重读校验通过） |
| 区域 | `full_xy_bounds_v1`：全 XY 包围 [1.270663, 20.553625, 1.475322, 20.932114] mm |
| 基准 | `min_z_plane` z = −0.771422 mm |
| 百分位 | 99.0（`DEFAULT_PERCENTILE`） |
| 排除 | 0.999837%（29,995 点 ≈ 1.0%），GUI 红点视图可逐点核查 |
| **有效起伏** | **2.684223 mm**（基准→99 分位切面） |
| 参考宽 | 19.282962 mm（区域 X 跨度） |
| 真实极值（保留不裁入上限） | true_min −0.771422 / true_max 2.106906 / 超出分位切面 0.194105 mm |
| bbox_z_span（仅历史对照） | 2.878328 mm / 比例 0.149268（≈14.93%，对应 `runtime/reference_inspection/stats.json` 的 2.878/19.283；**永不自动套用**） |
| 单位/算法 | assumed_mm / reference-profile-v1 |

同比例换算：2.684223 / 19.282962 × 60.0 = **8.352107938604037 mm**（在工程范围内）。

## 三样例表现（真机，不重跑推理）

基准 = PH09 第四轮（`workspace/photo-relief-p1/20260921-110433/`）既有 depth 修订；explicit 母版统一 60 mm 宽 / 2.0 mm 起伏 / 3.0 mm 底板 / 无平滑。

| 样本（depth 修订前 8 位） | master 修订 | 实体尺寸 mm | 体积 mm³ | 顶面最大误差 mm | 耗时 |
| --- | --- | --- | --- | --- | --- |
| 短毛犬（8a18d7ed） | `7e87ef8d…43c3eb1fa` | 60×60×5 | 12672.32 | 2.384e-07 | 1.1 s |
| 猫（f5336763） | `23bd7b20…a41a1ea1` | 60×60×5 | 13947.54 | 2.384e-07 | 1.1 s |
| 长毛犬（e9009bdb） | `4ad3439b…03d9321d` | 60×43.317×5 | 9424.09 | 2.384e-07 | 1.4 s |

三张全部：OBJ/STL 重读水密、正体积、正面起伏 2.0 mm / 加底实体 5.0 mm 分行记录、clamp 0 点（限幅未改变数据）、无 warnings。渲染离屏 6 视图×4 张（正/侧/斜 × 三点光组/头部单光源，读已发布 preview.vtp，与 GUI 同 LOD）；目视核验狗头浮雕形态正常，边缘锯齿与 148 px 输入分辨率一致（PH12 边界）。

reference_ratio 全链演示（短毛犬，同 depth 修订 + 标定 `ref-5c1ae382ab802ef6`）：master 修订 `18675809…eef5fa34`，解析深度 8.352107938604037 mm，正面起伏 8.352 / 加底实体 11.352 mm，体积 18618.92 mm³，顶面最大误差 4.768e-07 mm，1.0 s——验证标定→换算→母版→重读校验全链。

## 80/100/120 档位对照（仅实验，产品无档位控件）

实施路径文档第 4 步的"同基准 80%/100%/120% 对照是审美实验档位"以独立脚本落实（`run_p2_relief_tiers.py`）；**产品与 GUI 均无档位控件**，深度由显式 mm 或参考比例唯一确定。基准 = 短毛犬 depth `8a18d7ed`，宽 60 / 底板 3：

| 档 | 起伏 mm | master 修订 | 加底 mm | 体积 mm³ | 顶面误差 mm |
| --- | --- | --- | --- | --- | --- |
| 80% | 1.6 | `d8ad999e…889a683` | 4.6 | 12297.86 | 2.383e-07 |
| 100% | 2.0 | `b958e3d8…ca70987` | 5.0 | 12672.32 | 2.384e-07 |
| 120% | 2.4 | `3bb3aa4d…c91641f8` | 5.4 | 13046.79 | 2.384e-07 |

100% 档体积与三样例表一致（同参数独立修订，修订史 append-only）；三档 clamp 均 0 点。侧视+斜视渲染对照在 `experiments/photo_relief/out/p2-relief-tiers/`。**审美取舍（哪档好看）属视觉评审，须用户亲自查看后勾选，GLM 不代选。**

## 本地产物与证据（未加入 Git，重新获取仓库不会包含）

- 机器总账：`experiments/photo_relief/out/p2-masters/report_data.json`（标定 + 3 explicit + 1 ratio 全字段）、`experiments/photo_relief/out/p2-relief-tiers/report_data.json`。
- 渲染：`experiments/photo_relief/out/p2-masters/<tag>/`（每目录 6 图）、`experiments/photo_relief/out/p2-relief-tiers/tier-{080,100,120}-{side,iso}-lightkit.png`。
- GUI 证据截图：`runtime/evidence/photo-p2/p2-gui-{explicit-master,ratio-master,excluded-points}.png`；手测脚本 `runtime/gui_p2_smoke.py`（gitignored）。
- 母版文件：`workspace/photo-relief-p1/20260921-110433/<key>/revisions/<master-id>/{master.obj,master.stl,master.vtp,preview.vtp,heightfield.npz}`。
- 标定文件：`profiles/ref-5c1ae382ab802ef6.json`（app 级；换机器需重标定或拷贝该目录）。
- 改动前备份：`runtime/backups/20260921-glm-photo-relief-p2-start.bundle`。

## 未实现与边界（核验时不得当作已完成）

- P3（毛流/细纹，PH12）未开始；现有小图 `blocked_by_input_quality`。`ReliefParameters.detail_strength` 保持 0.0 不消费。
- P4（模具采样偏差评估）未做：master.vtp→阴阳模生成的集成链路已通（input_method 继承、STL 水密），但固定低采样上限的偏差量化与足够分辨率论证属 P4。
- 有效正面区域选择为 v1 口径（`full_xy_bounds_v1` + `min_z_plane` + 相机正面假设），交互式区域/基准选择未实现；换口径须重标定，全部字段落盘可审计。
- 深度语义延续 P1：相机视角相对前后关系，无姿态归一化；趴卧样本身体厚度仍映射为起伏（各 depth manifest 警告保留）。
- 所有母版 `visual_review=pending`、`manufacturing_validated=false`：技术门（水密/体积/误差）通过 ≠ 视觉/加工验收，最终以用户在 GUI 勾选为准。
- 参考同比例假设参考部位与目标部位对应（SubTool3 人像起伏 → 宠物浮雕仅为尺度参照）；不对应时界面提示改显式深度。
- CI（Linux）结果以远端实际运行为准，本报告落笔时未在远端验证。

## 版本及回退

- 分支 `glm/photo-relief-p2`，提交 ①`7ca97ac` ②`afe4fe9` ③`d229791` ④`d90e92f` ⑤本提交（实验脚本 + 报告 + 文档回写）；标签 **`photo-relief-p2`**（新增于本提交，未移动任何旧标签）。
- 旧标签 `baseline-before-mold-refocus-20260920`、`mold-workbench-v0.1.0`、`photo-relief-p1-original/-r1/-r2/-r3` 均未动。
- 回退：`git reset --hard photo-relief-p1-r3` 回 P1 末状态；改动前 bundle 见上节（同盘备份，防误操作不防磁盘故障）。
- 本轮交付经用户确认后推送远端（SSH `git@github.com:weifuqiang007/pet-leather-studio.git`）：分支 `glm/photo-relief-p2` + 新标签，不动 main、不改历史。

## 用户复测指引（GUI）

```bash
conda deactivate   # 避免 base 环境干扰 Qt/VTK
scripts/dev.sh run --frozen pet-leather-studio --project workspace/photo-relief-p1/20260921-110433/short_hair_dog photo
```

`--project` 必须在子命令 `photo` 之前。看什么：历史列表选 kind=master 的修订 → "三维中性预览"出母版实体，详情含正面起伏/加底厚度/重读校验/起伏上限来源；"起伏上限来源"切"参考比例"并选 `1_SubTool3.obj · 起伏 2.68` 标定 → 换算提示实时显示 8.35 mm；"查看参考排除点"画红色被裁点。满意后在界面完成视觉评审勾选（`visual_review` 不由 GLM 代填）。

## 复验记录（R1：蒙版边界背景过渡带，2026-09-22）

独立验收报告 [photo-relief-P2-acceptance-review.md](photo-relief-P2-acceptance-review.md) 结论为"工程链路通过、视觉效果不通过"，必修项：非矩形蒙版边界处主体高度单格跌落至 0（垂直墙）。GLM 数值复核确认该缺陷属实（旧母版域外严格 0，跨界单格跳变中位 0.8–4.2 mm、最大 1.9–6.0 mm），当日修复并复验。

### 修复内容

- `algorithms/relief_height.py` 新增 `edge_falloff(heights_mm, valid, band_mm, dx_mm, dy_mm)`：带宽内域外像素取**最近有效像素**高度（各向异性 EDT，采样 `(dy_mm, dx_mm)`），乘衰减 `1−smoothstep(d/带宽)`（3t²−2t³：边界导数 0，坡面最大斜率 1.5×h/带宽）；带宽外仍严格 0；**有效域内部逐位不变**（统计语义不动，满足验收报告第 5 点）。
- 管线顺序（验收报告第 3 点）：cap_to_mm → **edge_falloff** → 局部调整 → clamp_cap——刷在过渡带上的偏移作用在衰减后的高度上并受最终限幅。
- 参数：`ReliefParameters.falloff_band_mm` 默认 **2.5 mm**、范围 (0,50)、**0=关**（逐位等价旧行为）；CLI `--falloff-mm`；GUI 表单"边缘过渡宽度 mm（0=关）"，母版详情新增"边缘过渡"统计行；manifest 新增 `falloff{enabled, band_mm, raised_points, max_raised_mm, algorithm}`。
- 纵向网格间距 `dy_mm = dx×ny/max(ny−1,1)` 与 photo_geometry 的 height 换算同式；矩形全有效域为 no-op（旧测试零改动通过）。

### 实测（同 depth 修订重跑，修订史 append-only；跳变=恰一端有效的相邻单元 |Δh|）

| 样本 | 跨界跳变旧 p50/p95/max mm | 新 p50/p95/max mm | 域内固有断层 max mm（前→后） |
| --- | --- | --- | --- |
| 短毛犬 | 1.010 / 1.325 / 1.427 | **0.076 / 0.560 / 1.126** | 1.212 → 1.212 |
| 猫 | 0.808 / 1.614 / 1.894 | **0.063 / 0.390 / 1.621** | 1.786 → 1.786 |
| 长毛犬 | 1.085 / 1.975 / 1.998 | **0.042 / 0.148 / 0.744** | 1.082 → 1.082 |
| 短毛犬 ratio（8.35 mm） | 4.217 / 5.533 / 5.961 | **0.315 / 2.337 / 4.700** | 5.062 → 5.062 |

跨界中位跳变降 13–26 倍；四样本有效域内部逐位一致（`内部一致=True` 逐项断言）。**残余跨界最大跳变溯源为输入深度图固有断层**（修复前后域内最大跳变完全不变）——属 PH12 输入质量边界（148 px 深度图），非蒙版墙；可用 `smoothing_radius_mm` 缓解，不在 R1 范围。

新母版修订（渲染/实体在 `workspace/…/revisions/<id>/` 与 `experiments/photo_relief/out/`，同前节路径）：

| 母版 | master 修订 | 域外抬升点 | 最大抬升 mm | 体积 mm³ |
| --- | --- | --- | --- | --- |
| 短毛犬 explicit | `d614f21d…` | 2045 | 1.326 | 12810.6 |
| 猫 explicit | `d9a7bf42…` | 2325 | 1.759 | 14072.8 |
| 长毛犬 explicit | `337a74cb…` | 4444 | 1.922 | 9638.2 |
| 短毛犬 ratio | `611ffd12…` | 2045 | 5.536 | 19196.5 |
| 档位 80/100/120% | `a54e5554…` / `f4ef2c74…` / `d0af9eea…` | 2045 | 1.060 / 1.326 / 1.591 | 12408.5 / 12810.6 / 13212.8 |

### 验证

- 测试 +6（unit 5 + integration 1）：衰减公式钉扎（距边界 1 单元 = cap×(1−smoothstep(1/4))）、远离主体单调落地、全域单格跳变 ≤1.5×cap/带宽×单元、主体内部逐位不变、管线顺序（过渡带先于局部调整）、重跑逐位一致、L 形非矩形全链（band 开/关的域内逐位一致 + 域外近缘 >0）。**161 passed, 2 deselected**（无模型 146 + GUI 15；P2 交付 155 → +6，旧测试零删除）；ruff check / format / mypy 通过；真实模型 2 项未重跑（R1 不触及推理内核）。
- GUI 真机 smoke 复跑 ok（`runtime/gui_p2_smoke.py`，证据截图已更新至 `runtime/evidence/photo-p2/`）：explicit/ratio 母版三维视图 + 详情含"边缘过渡"统计行。
- 渲染目视（`out/p2-masters/short_hair_dog/short_hair_dog-side-lightkit.png`）：侧视轮廓两侧斜坡落地、无竖直台阶、顶面无孤立尖刺；斜视图主体边缘暗环为斜坡受光阴影，非垂直墙（与上表数值一致）。

### 版本

- R1 提交见 `git log` 本条（fix(p2-r1)）；新标签 **`photo-relief-p2-r1`**（只新增；`photo-relief-p2` 及更早标签未动，已推送远端）。
- 母版 `visual_review=pending` 不变：过渡带形态（带宽 2.5 mm 是否合意）属视觉评审，须用户在 GUI 亲自查看后勾选。
