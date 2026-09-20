# 模具工作台 v0.1 交付记录

日期：2026-09-20；分支 `codex/mold-refocus-v0.1`；发布标签 `mold-workbench-v0.1.0`。

## 完成范围

新增领域参数/端口、应用服务、网格导入及投影适配器、实体生成算法、SQLite 修订库与工程锁、CLI、PySide6/PyVista 工作台。保留旧实验及原始输入。每次导入/生成独立保存参数和文件 hash，支持预览历史与激活旧版本；后台失败不发布成功版本。

GUI 明示照片重建未实现、候选未获实物验证，展示实际采样间隔、覆盖率与不足提示。修复 PyVista 清空场景后灯光丢失的问题；阴模单独显示默认查看底部接触面。

## 实际验证

本机执行：

```bash
scripts/dev.sh run --frozen ruff check .
scripts/dev.sh run --frozen ruff format --check .
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
scripts/dev.sh run --frozen pytest tests/unit tests/architecture tests/integration tests/gui
```

结果：Ruff 检查通过；40 个文件格式通过；mypy 5 个文件通过；26 项测试全部通过（5.61 秒）。GUI 测试在实际 Qt 图形会话运行，覆盖后台生成、历史切换及灯光回归。合成坡面测试覆盖配套间隙、封闭性、体积；版本测试覆盖失败、文件篡改、写锁、回退与分支。

真实参考 `images/test1_result/1_SubTool3.obj` 已导入 `workspace/refocus_reference`，原始参考未修改。母版 999,996 个三角形，中性材质可查看真实人物细节。以宽 60 mm、起伏 2 mm、间隙 1 mm、底板 3 mm、长边 128、最小特征 0.2 mm 生成两份 STL。实际采样约 0.476 / 0.477 mm，覆盖率 76.5%，明确标为 sampling_sufficient=false，不能保留目标细纹。

本地证据（未加入 Git，重新获取仓库不会包含）：

- `runtime/reference_import.json`、`runtime/reference_import_v2.json`、`runtime/reference_molds.json`：命令输出。
- `runtime/reference_inspection/workbench_master.png`：中性材质母版界面。
- `runtime/reference_inspection/workbench_male.png`、`workbench_female.png`：低采样候选界面。
- `workspace/refocus_reference/revisions/`：母版与候选产物。新预览修正通过新修订保存，旧修订保留。

## 验收对应

V01/V02/V03/V04/V06/V07 已有真实导入或自动测试证据；V08 检查及 GUI 冒烟通过。V05 的失败/锁与保持当前版本已测，主动取消按钮的进程中断边界尚未进行专门自动化验收，不宣称完整通过。相似度用户验收、照片重建、打印细纹和皮革实际转印均未通过或未进行。

## 版本及限制

改动前标签 `baseline-before-mold-refocus-20260920`；未提交的原文档另存 `runtime/backups/20260920-141309/working-tree.zip`，附 manifest 与 Git bundle。新标签 `mold-workbench-v0.1.0` 固定本轮代码。建议另建 worktree 回看旧版；不删除当前工程或数据。

本次无新增第三方依赖、AI 权重或 FreeCAD 安装；uv.lock 仅同步本项目版本。沿用项目本地环境。

下一步是照片到精细几何的独立质量实验，以及高分辨率采样/公差处理。本轮不能替代这两项，也未实现等法向间隙、倒扣检测、定位销、压力仿真、机械臂或扫描质检。
