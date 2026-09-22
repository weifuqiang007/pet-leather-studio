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
