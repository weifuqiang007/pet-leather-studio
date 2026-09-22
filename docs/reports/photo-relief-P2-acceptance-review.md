# P2 独立验收报告

日期：2026-09-22；审查提交：`e9ab2a3`；分支：`glm/photo-relief-p2`。

## 结论

P2 的工程链路通过验收：参考高度标定、显式/同比例深度、局部调整、可追溯母版修订、OBJ/STL 导出和 GUI 路径均有实际证据。**P2 的产品视觉效果暂不通过验收。** 当前算法将主体蒙版外的高度严格置零，形成明显的垂直轮廓台阶和不连续断层；这不适合作为皮雕母版，更不能直接进入阴阳模或压制。

这份结论不否定 P2 的工程成果：它把原先不可控的深度图变成了有版本、有单位、有高度上限、可导出的实体。下一步需要解决的是“浮雕边缘如何自然落到背景”，不是继续把现有高度整体放大、缩小或直接打印。

## 实际复算

以下均在本机重新运行，而不是沿用交付报告结论：

```bash
scripts/dev.sh run --frozen ruff check .
scripts/dev.sh run --frozen ruff format --check .
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
scripts/dev.sh run --frozen pytest tests -m 'not real_model'
scripts/dev.sh run --frozen pytest tests/integration/test_real_model_depth.py -q
scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_masters.py
scripts/dev.sh run --frozen python experiments/photo_relief/run_p2_relief_tiers.py
scripts/dev.sh run --frozen python runtime/gui_p2_smoke.py
```

- Ruff、格式检查和 mypy 通过。
- 常规测试：155 passed、2 deselected。
- 真实 DA2 模型测试：2 passed。
- 两个 P2 实验脚本均成功重跑；GUI 冒烟返回 4 项断言成功。
- 本地 `profiles/ref-5c1ae382ab802ef6.json` 与 P2 总账可读。参考有效起伏为 2.684223 mm、参考宽 19.282962 mm，60 mm 工件的参考比例深度为 8.3521079386 mm，计算与报告一致。
- 三个 explicit 母版、一个 reference-ratio 母版和 80/100/120 对照均重新导出。报告中的 OBJ/STL 水密、正体积、顶面误差约 `2.38e-7` 至 `4.77e-7` mm 与本机总账一致。

## 可接受的工程部分

1. PH05 参考标定的记录结构合格：基准面、区域、百分位、被排除点、真实极值与历史 bbox 指标分开保存；没有把 14.93% 包围盒比例偷偷作为默认值。
2. PH06 的几何导出链路合格：实体文件重读后水密、正体积，并与高度场逐列比较。母版修订可追溯到 photo、mask、depth，旧 OBJ 母版链路没有被替换。
3. 显式深度、参考比例、局部调整和限幅都通过同一数值管线。参考比例 8.35 mm 只是可运行的尺度演示，不是推荐给宠物挂件的默认深度。
4. GUI 可以显示 explicit 母版、ratio 母版和参考排除点；`runtime/evidence/photo-p2/` 的三张截图存在，GUI 冒烟实际通过。

## 未通过的视觉问题

实际检查以下发布后的无贴图渲染：

- `experiments/photo_relief/out/p2-masters/short_hair_dog/short_hair_dog-iso-lightkit.png`
- `experiments/photo_relief/out/p2-masters/short_hair_dog-ratio/short_hair_dog-ratio-iso-lightkit.png`
- `experiments/photo_relief/out/p2-masters/cat/cat-iso-lightkit.png`
- `experiments/photo_relief/out/p2-masters/long_hair_dog/long_hair_dog-iso-lightkit.png`

三个 explicit 样本都可见主体边缘从约 2 mm 高度直接跌到零，表现为锯齿状垂直墙；短毛犬还出现明显的斜向高度断层。ratio 样本把同一问题放大到约 8.35 mm。猫和长毛犬也没有形成自然的背景过渡。

根因在 `algorithms/relief_height.py`：`unit_height()` 对 `valid` 外返回零，`smooth_valid_aware()` 最终也再次将 `valid` 外置零；`photo_geometry.py` 随后把整个高度栅格直接做成实体。有效域感知平滑的目标是防止背景拖低主体边缘，但它并没有生成浮雕所需的边缘过渡带。因此 PH06 的“逐列顶面与输入高度场一致”可以通过，却恰好证明导出的垂直墙被完整保留。

现有测试几乎都使用 `valid.all()` 的矩形高度场，缺少“非矩形主体到背景必须连续过渡”的视觉/几何门，所以没有捕获这一问题。

## 必修修改后再验收

1. 新增明确的**背景过渡设计**，而不是修改当前 `valid` 的统计语义。建议在深度归一化后、实体导出前建立独立 `relief_support`：主体内部保持原深度，主体外扩一个可调的毫米过渡宽度，平滑地落至背景零平面。必须记录过渡宽度、算法和被改变区域。
2. 过渡不得吞掉鼻子、耳朵、爪子等轮廓；需要提供前/后高度截面和无贴图侧视图，确认没有垂直台阶、尖峰或背景隆起。
3. 将局部结构调整建立在过渡后的高度场上，并重新检查上限、局部偏移和高度报告；不能用“整体平滑”模糊五官、花瓣或毛流。
4. 增加单元和集成测试：非矩形蒙版内为常数高度、外部为背景时，边界外法向/高度差必须在设定过渡带内连续；导出的 OBJ/STL 要满足同一截面条件。保留矩形输入测试，避免把有效区域统计逻辑改坏。
5. 重跑三张样例及 80/100/120 对照，用新修订保存；用户在 GUI 对无贴图正面、侧面和斜视图确认后，才把 `visual_review` 从 pending 改为通过。

## 声明边界

- 本报告读取了这台电脑的 gitignored 证据；其他机器只能复算 Git 内代码和测试，不能仅依据文档数字确认视觉效果。
- P3 细毛、花瓣脉络和高清输入评审仍未开始；P4 模具采样偏差、打印和皮革试压也未验收。
- 水密 STL、正体积和小数级顶面误差是几何一致性，不是艺术效果、脱模性或皮革成形合格证明。

## R1 复验（2794bc1，2026-09-22）

R1 确实新增了 `edge_falloff`，并将带宽作为可调参数保存。重新运行 Ruff、格式检查、mypy、完整非真实模型测试、真实模型测试、两份 P2 实验脚本和 GUI 冒烟后，结果如下：

- 静态检查通过；`pytest tests -m 'not real_model'` 为 161 passed、2 deselected。
- 真实模型测试为 2 passed。
- P2 母版、80/100/120 档和 GUI 冒烟均成功重跑。
- 新标签 `photo-relief-p2-r1` 指向 `2794bc1`；旧 P2 标签未移动。

数值上的旧问题可以关闭：域外高度不再直接置零，主体内部高度保持不变，过渡带参数和抬升统计进入 manifest，非矩形边界的回归测试也已加入。

但**R1 后的产品视觉结论仍是 pending，不能让用户直接勾选通过**。实际检查重跑后的无贴图 ISO/侧视渲染时，短毛犬、猫和长毛犬仍有明显的硬轮廓；尤其 8.35 mm reference-ratio 短毛犬的 2.5 mm 带宽导致约 3.34 的高宽坡度，视觉上仍接近垂直墙。2 mm explicit 版本虽比旧版连续，主体外缘仍呈明显暗环和硬边。

这说明 R1 解决了“掩码外立即掉到零”的数值错误，却没有解决“不同深度与不同主体需要多宽、多柔和的边缘设计”这一浮雕设计问题。当前 UI 可以调带宽，但缺少依据深度自动提示、侧视截面比较和针对高比例母版的风险提示。

R2 再验收前应补充：

1. 给出建议的最小过渡宽度或坡度上限，例如按解析最大起伏计算；reference-ratio 的 8.35 mm 不应默认沿用 2.5 mm。
2. 在 GUI 同时显示边缘带宽、最大起伏、最陡坡度和一条可读截面，方便用户判断过窄或过宽。
3. 为 2 mm 与 8.35 mm 两类样例导出至少三种带宽的侧视/斜视对照；由用户选定样式，不能由数值测试替代审美选择。
4. 除了蒙版外扩，还需检查主体内部的深度断层；当前 R1 保证域内逐点不变，因而也保留了输入深度图的硬断层。

## R2 复验（83ae10c，2026-09-22）

### 结论

R2 的**诊断与实验能力通过工程验收**：建议带宽、坡度分类、截面对话框、manifest `slope` 和九臂对照均已实现，且可在本机重跑。**R2 仍未通过产品视觉验收，也不能进入阴阳模链路。** `visual_review` 应继续保持 pending。

这次的关键结论是：`建议带宽 >= 1.5 × 起伏` 只约束理想 smoothstep 裙边的解析峰值坡度；它不约束深度图在蒙版内或蒙版边界处已有的单像素高度断层。因此界面不能把该建议表述为成品“最陡坡度 <= 45°”的承诺。

### 实际复算

本机对 `83ae10c` 重跑 Ruff、格式检查、mypy、全部非真实模型测试、真实 DA2 测试、两份 P2 实验脚本和 GUI 冒烟。结果如下：

1. Ruff、格式检查、mypy 均通过；非真实模型测试实际为 **161 passed, 2 deselected**，真实 DA2 测试为 **2 passed**。交付报告中“168 passed, 2 deselected”的声明与当前工作树的实跑结果不一致，交付报告必须更正或说明所用测试集合后才能作为可复算证据。
2. `run_p2_falloff_bands.py` 成功生成九条母版修订、18 张渲染及 `report_data.json`；GUI 冒烟成功，截面对话框可打开。
3. 原始实验总账表明：2 mm explicit 的 2.5/3.0/4.0/6.0 mm 带宽臂，整体最大坡度均约 **71.4°**；8.352 mm reference-ratio 的 2.5/12.6/16.7/25.1 mm 带宽臂，整体最大坡度约 **85.4–85.6°**。带宽变大只延长裙边，未降低这些真实最大值。
4. `explicit-b3.0-smooth`（2 mm 显式深度、3 mm 带宽、1.5 mm 平滑）确有改善：全域/边界/域内最大坡度为 **44.1° / 15.2° / 10.5°**。但实验脚本没有任何 **8.352 mm reference-ratio + 1.5 mm 平滑** 对照臂；因此不能把这一结果外推为比例高度模式也已经解决。

### 视觉复核

复看 `explicit-b3.0-smooth` 与 `ratio-b12.6` 的 ISO、侧视渲染：前者的边缘落地已较平缓，但主体内容已变得非常浅，且仍可见轮廓锯齿/沟槽；后者仍有大面积近垂直的条状断层，侧视也清楚显示陡峭局部台阶。它们都不足以证明可压制皮革的母版质量。

尤其是 ratio 组：12.6 mm 是由 8.352 mm 起伏公式推导出的“裙边建议值”，但原始总账的边界最大值仍为 85.36°、域内最大值仍为 85.39°。这直接说明当前深度场的断层比裙边公式更先需要处理。

### R3 前的必要修正

1. 将 GUI 文案改为“**理想裙边**建议 >= X mm（该公式不含输入深度断层）”；母版详情中若全域、边界或域内实测值超出目标，必须显示醒目风险提示，不能只显示 45° 建议。
2. 将平滑做成可审计的预设/参数组合，而不是只存在一条实验臂；至少对 2 mm explicit 与 8.352 mm reference-ratio 各跑未平滑、1.0 mm、1.5 mm、2.0 mm 四档，并同时比较五官/毛发细节损失与三类坡度。
3. 为比例高度增加合理的产品高度上限或缩放策略。60 mm 工件的 8.35 mm 起伏对于宠物皮雕挂件明显偏高；不能仅靠把裙边增至 12.6 mm 来弥补。
4. 以短毛犬、猫、长毛犬三张真实样本进行同条件对照。通过条件应是：无贴图正面、侧面、斜视图没有硬墙/条状断层，关键轮廓仍清晰，且用户在 GUI 逐一确认；随后才可开始阴阳模配合与试压。

### 声明边界

本节的渲染和 `report_data.json` 位于 gitignored 本机目录，其他机器只能复算 Git 内的代码与测试，不能凭本文数字确认视觉效果。R2 的版本标签 `photo-relief-p2-r2` 指向 `83ae10c`，旧标签未移动。
