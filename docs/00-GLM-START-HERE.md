# GLM 实施阅读入口

更新：2026-09-20；仓库 `/Users/weifuqiang/Desktop/pet-leather-studio`。

## 必读顺序

1. [IMPLEMENTATION-REFOCUS-v0.1.md](IMPLEMENTATION-REFOCUS-v0.1.md)：当前实施范围、参数、不可调约束、版本回退与验收。
2. [REFERENCE-TARGET-CORRECTION.md](REFERENCE-TARGET-CORRECTION.md)：用户认可的精细几何目标和参考文件含义。
3. [reports/mold-workbench-v0.1.md](reports/mold-workbench-v0.1.md)：当前已完成能力、实际验证与缺口。
4. [adr/0002-master-mold-refocus.md](adr/0002-master-mold-refocus.md)：新架构决策。
5. [PRD.md](PRD.md)：继续沿用不冲突的工程规范、本地依赖规则和分层约束；旧建模路线和里程碑已被本轮收敛方案替代。

旧 PRD-review-response、PRD-review-issues、ADR 0001 和 M0.5 报告用于追溯，不覆盖最新范围。用户最新明确要求优先，其次当前收敛路径与 ADR 0002。

## 下一轮工作

照片重建开发必须先读 [PHOTO-RELIEF-IMPLEMENTATION-PATH.md](PHOTO-RELIEF-IMPLEMENTATION-PATH.md)，其中含具体代码路径、接口/数据协议、P1–P4 顺序和 PH01–PH12 验证条件；当前阶段以该细化计划为准。

先运行现有测试、启动工作台并查看参考 OBJ。不要重写已经实现的版本/导入/候选模具功能。下一项核心工作是独立验证照片到精细母版的质量：真实几何中性显示与参考对比，通过用户评审后再接入正式流程。`test1.png` 是软件截图，不能假定它等同原始照片。

不将区域鼓包、贴图、占位模型或合成测试冒充精细照片重建。当前模具低分辨率、Z 向间隙、无定位销，不能称为可生产精细模具；需继续完善采样、公差、脱模与实物试压。

## 必须保持

- PySide6 + PyVista 桌面，领域/应用层不依赖 GUI、VTK 或 SQLite。
- 下载模型、依赖、缓存仅到仓库本地约定目录；记录来源、版本、许可及校验值。
- 已有 Blender 按需使用，FreeCAD/FEM/扫描硬件暂不强制安装。
- 不覆盖母版、历史产物和用户文件。每轮代码提交、数据修订分开保存。
- 外部命令通过受控适配器；GUI 长任务用后台进程，失败不发布成功版本。
- 每轮在 reports 写真实检查结果，不以代码测试代替相似度或实物验收。

## 可复制的任务指令

> 在 pet-leather-studio 中，先按 docs/00-GLM-START-HERE.md 的顺序阅读当前文档及代码。以 IMPLEMENTATION-REFOCUS-v0.1.md 为当前范围，保留现有 Git 标签和数据历史。先验证现有导入与阴阳模工作台，再进行照片到精细浮雕母版的独立质量实验。不要恢复旧区域凸起路线，也不要宣称当前候选模具可直接量产。所有下载物留在项目内；逐项提供真实验收证据。
