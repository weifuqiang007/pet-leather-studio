# P1 第三轮独立验收（4ed7c05）

日期：2026-09-21。结论：代码质量和主流程回归通过，取消与标签问题可关闭；模型选择损坏边界、样例蒙版及其可视核对仍需修正，暂不签署完整 P1 效果验收。此次只记录评审，未修改业务代码。

## 实测结果

- Ruff check / format 通过（66 文件）；mypy 8 文件通过。
- 非模型 unit/architecture/integration：97 passed、2 deselected，5.04 秒。
- `scripts/dev.sh run --frozen pytest tests/gui tests/integration/test_real_model_depth.py -q`：12 passed，21.08 秒，即 GUI 10 + 真实模型 2。
- 合计 109 项通过；取消超过 5 秒窗口及忽略 TERM 的 worker 回收回归通过。
- 20260921-100609 三样例共九个修订 hash 校验通过，原始证据可访问。
- 标签核实：photo-relief-p1-original→93f87df、photo-relief-p1-r1→caaf5d3、photo-relief-p1-r2→4ed7c05；baseline 和 mold-workbench-v0.1.0 保留。拆分决定已记录，可以关闭标签追溯问题。

## 已关闭

F1：受控 QTimer 在结束时停止，回调检查任务身份；新增 GUI 延迟回归及进程组 TERM/KILL 测试通过。
F2 的主要路径：已有模型版本重新下载可重新校验并更新 selected；指向不存在版本报错。仍有下列损坏文件边界。
F4：独立标签及迁移说明已落实。
静态检查、GUI 联测、真实模型与 NaN 拒绝等原问题没有发现回归。

## 尚需修正

### A / P2：损坏 selected.json 仍被视作“没有选择”

位置：`src/pet_leather_studio/infrastructure/photo_inference.py` 的 `_selected`（约第 49 行）。

JSON 解析错误/缺 revision 等返回 None，locate 继续选择最新下载版本。与“显式选择失效必须报错”的要求仍不符。

已用临时模型目录复现：写入 `{broken` 的 selected.json，locate 成功返回一个模型目录，没有报错。应区分文件不存在与存在但损坏；后者报 ResourceMissingError，空值/错误类型/缺字段也校验。添加损坏 JSON、缺 revision、空 revision 回归；不要扩大为所有情况自动回退。

### B / P2：所谓半透明叠加实际没有保留主体处原图 RGB

位置：`experiments/photo_relief/run_p1_three_photos.py:249–254`。

`base.paste(red, ..., mask_up)` 使用 255 主体蒙版直接替换 RGBA 像素，得到红色 RGB 与 alpha=80，而不是把红色按 31% 混合到原图。查看三个 overlay，内部仍为整片红色，无法核对五官与边界内部对齐。

应先构建 alpha=mask×80/255 的覆盖层，再 alpha_composite 到原图，最后绘制边界；保存 RGB 成品避免查看器透明底差异。加像素测试：主体内部 RGB 应等于约 0.69×原图+0.31×红色，而非恒定红色。重新导出三张叠加图供核对。

### C / P2：阈值轮廓的 IoU 是自洽检查，不能证明真实主体正确

第三轮轮廓比旧版改善，但短毛犬颈胸附近出现较大缺口、猫右侧形成矩形突出、长毛犬腹部出现大块挖空，需要回原图判断白毛/水印/背景而非直接接受阈值分割。输入中白毛和浅背景本就难分，最大连通域和闭运算不能替代核对。

IoU≥0.985 只说明多边形近似与其源阈值掩码一致，不是与人工正确标注的一致率。报告的“客观测定”不能作为主体准确率承诺。

要求：用修好的半透明叠加逐张修正可见大块误纳/遗漏，保留人工修正记录。阈值辅助结果的 mask_method 宜为 threshold_assisted，并保存阈值/颜色距离、形态学配置；当前脚本传 MANUAL、仅 notes 描述处理，来源字段不够准确。P1 不要求细毛逐根保留，但耳朵、白毛躯干和水印误纳必须分清。视觉评审继续 pending。

## 复验范围与边界

下一轮只需针对 A 的异常选择、B 的颜色混合、C 的三样例修正增加直接证据，同时保持现有回归通过。不追加人脸/毛发高精度或物理成形要求。当前可以继续 P2 的独立算法实验，但不得把 P1 样例正确性标为通过，也不得把深度预览称为完成精细浮雕母版。
