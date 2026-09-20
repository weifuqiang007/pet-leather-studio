# P1 独立验收：需要修改后复验

日期：2026-09-20；被审代码 93f87df，文档 HEAD df818fa。结论：真实本地推理基础成立，但 P1 整体暂不通过；不得进入“已完成精细母版”状态。本轮仅审查、运行验证与记录，未修改业务代码。

## 已复算与实际可访问的证据

当前评审在用户本机运行，能够读取未入 Git 的本地证据，不能沿用“GPT 看不到”的假设。

- `scripts/dev.sh run --frozen pytest -p no:pytest-qt tests/unit tests/architecture tests/integration -m 'not real_model'`：87 passed、2 deselected（6.16 秒）。该命令不含 GUI，因此“旧 26 项包含在内”不准确，旧 GUI 一项不在其中。
- `scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application`：8 个文件通过。
- `scripts/dev.sh run --frozen ruff check .`：失败，两个问题，见下文。
- `scripts/dev.sh run --frozen ruff format --check .`：失败，一个实验脚本需格式化。
- `scripts/dev.sh run --frozen pytest tests/gui tests/integration/test_real_model_depth.py::test_real_depth_inference_runs -q`：6 passed、1 failed（14.97 秒）；真实深度模型冒烟通过，失败为旧 `test_workbench_generate_and_restore`，生成后 history 为 1 而非 2。随后单独运行 `tests/gui/test_workbench.py -q` 通过（4.74 秒），同测试临时工程手动 CLI 生成也通过。应查测试间环境/状态干扰，不据此直接断言旧算法已坏，也不能宣称整套 GUI 稳定通过。
- 未运行会原地修改正式权重的 `test_worker_rejects_corrupt_model`。该测试应改为临时副本，避免测试异常中断损坏正在使用的权重。
- ModelRegistry 对本地 `5426e4f0f36572d16453bbda7a8389317b1bef99` 模型文件校验通过。
- report_data.json 所列三个工程、每个 photo/mask/depth 共九个修订文件 hash 全部通过。
- 实际查看猫正面中性渲染与短毛犬蒙版；存在可信文件，但样例蒙版不能证明完整可见主体重建通过。
- 不做远端 CI 声明，不更改 visual_review=pending。PH05/06/12 后置范围合理。

## 必修项（按影响排序）

### R1 / 高：取消只杀 CLI，未终止推理子进程

位置：`src/pet_leather_studio/presentation/photo_panel.py:430`、`infrastructure/photo_inference.py` 的 DepthWorker.run。

GUI 用 QProcess.kill 结束 CLI，CLI 又使用 subprocess.run 启动模型 worker，没有进程组或子进程生命周期清理。取消父进程不保证 worker 退出；可能继续占用内存/设备并写临时文件。现有 PH08 测试主要抛异常和清 staging，没有真实进程树中断测试，不能覆盖此问题。

要求：实现受控进程组或显式子进程回收，跨平台分别处理；取消后确认 CLI/worker 均退出、锁释放、active 不变、重试成功。添加启动长任务再取消的真实子进程集成测试，不只用异常桩。

### R2 / 高：CPU 回退分支会传入非法设备字符串

位置：`scripts/photo_inference_worker.py:57–63`。

MPS 模型迁移失败后，device 被设为 `cpu（MPS 不可用回退）`，随后传给 inputs.to(device)，不是有效 Torch 设备。前向计算发生的 MPS 错误也不在现有回退范围。

要求：计算设备保持 `cpu`/`mps`，回退说明用独立字段；覆盖模型迁移和推理阶段可回退错误，不能吞掉输入或模型损坏错误。增加明确设备选择参数，使 CPU 基线能在支持 MPS 的机器上复跑；用故障注入验证回退，而非测试仅允许那条错误字符串。

### R3 / 高：PH09 主体蒙版沿用旧局部标注，视觉结论失去依据

位置：`experiments/photo_relief/run_p1_three_photos.py` 的 mask_from_annotations/run_one；本地 mask-preview 与渲染。

脚本以旧 M0.5 区域多边形并集作有效域。短毛犬蒙版仅为头部附近椭圆，排除了原图大量可见上身；猫渲染呈不完整局部轮廓，不能支持报告中的“蜷卧剪影可辨”（原图本身为头部与上身）。这是样例准备问题，不能全归因于 148px 或模型能力。

要求：为三张照片重新制作覆盖目标可见主体的蒙版，保存原图叠加图供核对。若有意只做头部，明确记录裁切/ROI 并标注不验全身；长毛犬必须保留全身测试。重新执行三样例、发布新修订，旧证据保留；报告区分蒙版错误、深度错误与低分辨率细节限制。不能凭“平滑、无空洞”通过形体质量。

### R4 / 中：主体内 NaN 被静默剔除并发布成功

位置：`src/pet_leather_studio/infrastructure/photo_inference.py` 的 assemble_depth_revision。

代码 `valid = (mask > threshold) & isfinite(arr)` 将主体中的错误预测改作背景，而不是按 PH04 拒绝。已实际复现：3×3 全主体蒙版、中心 NaN，函数成功发布候选文件，覆盖率变成 8/9。极小有效面积也未在发布时按统一阈值检查，可能保存一个无法预览的 depth。

要求：先定义主体域，再检查主体域内非有限值与面积，失败不发布；如果未来允许缺测，另定义显式缺测策略、比例和警告，不能偷偷缩蒙版。增加真实组装函数测试，而不只测试 unit_height。

### R5 / 中：模型版本选择不能稳定复现指定版本

位置：`scripts/photo_inference_worker.py` 的 cmd_download/parser、`infrastructure/photo_inference.py` 的 ModelRegistry.locate。

download 声明了 --revision，但 model_info 没有使用该参数；安装时不能可靠请求指定版本。locate 把提交 hash 按字典序排序并取最后一个，hash 字典序不是发布时间，新增模型后选中版本可能不符合预期。

要求：查询及下载均使用明确 revision 并记录解析后的 commit；注册当前选中版本或显式传 revision，已有任务根据清单重现，不按 hash 排序猜“最新”。测试两个非时间排序的版本以及指定旧 revision 下载的请求参数。

### R6 / 中：声明的质量检查不通过，GUI 联合回归需排查

Ruff 实测：`tests/integration/test_real_model_depth.py:7` 的 sys 未使用；`experiments/photo_relief/run_p1_three_photos.py:5` 超长。后者是 Git 跟踪文件，不能以“experiments 不在 Git”解释。格式检查也要求修改该脚本。

要求：修正 lint/format，排查整套 GUI 联合运行失败；再次完整运行而非只重跑失败项。真实权重损坏测试改为临时副本；测试报告精确区分 87 项无模型测试、GUI 与真实推理。

## 补充建议

- 保存完整原始浮点深度及预处理元数据：当前组装会把蒙版外预测置零，TemporaryDirectory 退出后原始输出丢失；重新做蒙版时难以复用/诊断。至少保存 raw depth 或明确提供可重跑配置与处理记录。
- ModelRegistry.verify 对空 files 清单会通过，应校验必需文件、模型身份、路径范围及大小；自建 hash 能确认下载后未变化，不能单独证明第三方镜像与官方完全一致。
- “本节与代码优先”只能描述实际状态，不能用交付声明覆盖验收合同；缺失项目应标失败/延后，而不是自动修改要求。

## 复验入口

先修 R1–R6，更新 PH04/08/09/11 证据；运行 lint、format、mypy、87 项及新增回归、完整 GUI、隔离权重的真实模型冒烟；重新核对三图主体蒙版和至少正面/侧面/两种光照。满足后可以接受“P1 工程基线”，仍不等于通过 P2 高度设计、P3 细毛或打印/试压。
