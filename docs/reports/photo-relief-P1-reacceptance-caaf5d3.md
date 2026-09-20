# P1 第二轮独立验收（caaf5d3）

日期：2026-09-20。结论：基础工程明显改善，自动检查通过；仍需修复取消回调与模型版本选择边界，修正样例蒙版及版本管理记录，暂不签署“R1–R6 全部关闭”。未修改业务代码。

## 实际复算

- Ruff check：通过；format check：65 文件通过；mypy：8 文件通过。
- 无模型 unit/architecture/integration：94 passed、2 deselected，3.55 秒。
- `scripts/dev.sh run --frozen pytest tests/gui tests/integration/test_real_model_depth.py -q`：9 passed，18.83 秒（GUI 7、真实模型 2）。上轮 GUI 联测失败本轮未复现。
- 20260920-181637 三样例的 photo/mask/depth 九个修订 hash 全部校验通过。新证据真实存在，旧结果保留。
- 主体 NaN 拒绝、原始深度保存、CPU 设备字符串修复、下载 revision 透传、清单退化校验均已有代码及测试支持。

## 尚未关闭的问题

### 1. [P1] 取消完成后，延迟回调访问已销毁的 QProcess

位置：`src/pet_leather_studio/presentation/photo_panel.py:470`。

cancel_job 创建 5 秒单次回调并捕获 process；任务正常响应 TERM 后 job_finished 调用 process.deleteLater。5 秒后 lambda 再调用 process.state()，触发已删除 C++ 对象异常。

本轮在真实 PhotoWorkbenchWindow 中启动 sleep 子进程，调用 cancel_job，并让事件循环继续 5.6 秒，实际捕获：`libshiboken: Internal C++ object (PySide6.QtCore.QProcess) already deleted.` 现有 GUI 测试全部通过但未覆盖这个等待窗口。

修复：使用受控 QTimer，在任务结束时停止并释放；或回调先验证任务身份和对象有效性。补充取消成功后等待超过 5 秒、关闭窗口取消、取消后立刻启动新任务的回归。另建议 TERM 后确认 worker 进程组确实退出，必要时整组 KILL；当前仅向组发送 TERM 后退出父进程，对忽略 TERM 的 worker 无等待/升级保障。

### 2. [P2] 已下载旧版本不能可靠被重新选中

位置：`scripts/photo_inference_worker.py` cmd_download 中 revision_root 已存在分支；`infrastructure/photo_inference.py` ModelRegistry.locate。

新版首次下载会写 selected.json，但目标目录已有 manifest 时直接 return 0，不更新 selected，也不重新校验。因此先装 A、再装 B、再显式 download --revision A，界面仍可能使用 B。另一个问题是 selected 指向缺失/错误版本时静默回退 downloaded_at 最新，违反明确选择失败应报错的原则。

修复：已存在分支也校验并原子更新选中指针；有显式 selected 但无法解析时明确报错，仅真正没有选中配置时使用兼容策略。增加“已有 A/B 再选 A”和“失效 selected 不自动换模型”的测试。

### 3. [P2] 三样例扩大了范围，但“完整主体蒙版”仍不成立

实际查看新 mask-overlay：短毛犬图像右侧耳朵明显在红色蒙版外；长毛犬头顶毛发、右侧身体和爪部仍有可见遗漏，另有背景被纳入。叠加图为不透明红色，不利于核对内部对齐。不能单凭覆盖率增加就验收。

修复：提供半透明叠加与边界线，逐张修正明显缺失和背景误纳；若有意舍弃细毛边缘，记录处理口径，但耳朵和身体不是微纹例外。猫中性正面仍主要呈平滑轮廓，不能作为五官/细纹成功证据；visual_review 继续 pending。本轮不把低分辨率细毛不足当新增 P1 范围，只要求基础主体准备正确。

### 4. [P2] 移动发布标签违反已约定的回退规则

文档自述并经 git 核查，photo-relief-p1 从首轮 93f87df 移到 caaf5d3。原合同要求新增唯一标签、不移动旧标签；首轮提交仍存在，未丢失代码，但相同标签现在指向不同成果，削弱追溯。

修复建议：先记录当前所有引用，明确首轮与修复轮唯一标签（例如 photo-relief-p1-original 与 photo-relief-p1-r1）；是否恢复原标签需记录迁移决定，不能再次偷偷移动。本轮评审未改动标签。后续一律新增版本标签。

## 文档同步

阅读入口仍混合首轮 170915 证据与新 181637 证据，仍有“旧26项均包含在94非GUI项”“experiments均不入Git”等错误表述。需将旧轮明确标历史，新轮链接作为当前入口。R6 原义包含 lint/GUI，不能仅改称“清单退化”即视为原问题关闭。

## 复验结论

R2 原非法设备问题、R4、R6 静态检查及本轮 GUI 联测可视为已修；R1/R3/R5 部分修复，剩余如上。P1 本地真实推理技术基线成立，但最终验收需关闭以上缺陷。参考高度、母版导出和精细毛发属于后续阶段，不以本轮测试通过替代其验收。
