# 皮革压制阴阳模 M1 独立验收复核

**复核对象**：提交 `55d32f6`，标签 `leather-mold-m1`  
**复核日期**：2026-09-23  
**结论**：**候选模具文件与修订链通过；M1 的“连续几何最小间隙”验收暂不通过。**

现有三对候选 OBJ/STL 可以保留、查看和用于后续修复后的复验；但不能把当前
`clearance_independent.min_mm` 当作连续模具表面已安全配合的证明，也不能据此把
M1 标为“§7 全部满足”或进入实物试压。

## 已通过的项目

- Git 状态、提交和远端标签一致：`55d32f6`、`leather-mold-m1`；工作树无未提交修改。
- `scripts/dev.sh run --frozen python -m pytest tests -m 'not real_model'`：
  **207 passed, 2 deselected**。
- `ruff check .`、`ruff format --check .`、
  `mypy src/pet_leather_studio/domain src/pet_leather_studio/application --strict`：均通过。
- 真实深度模型回归：
  `scripts/dev.sh run --frozen python -m pytest tests/integration/test_real_model_depth.py -q`：
  **2 passed**。
- 三份本地候选修订均存在 `male.obj/.stl/.vtp`、`female.obj/.stl/.vtp`、
  `mold_pair.npz`、`README.txt` 和装配预览；manifest 的 `kind=mold_pair`、
  `parent_id`、四级上游 ID、`manufacturing_validated=false` 与
  `visual_review=pending` 一致。
- 三份候选都执行了模具侧扩边，源母版核心逐位保留，平坦止口分别为
  4.019、4.012、4.282 mm；导出的 OBJ/STL 可重读且为水密正体积。这些结论和
  [leather-mold-M1.md](leather-mold-M1.md) 的记录相符。

## 阻断项：内置“独立距离”不是三角面距离

**等级：P0（必须修复后才能宣布 M1 几何验收通过）。**

`algorithms/leather_mold_pair.py` 中的 `_surface_samples()` 只取每个面片的顶点、
三条边中点和面心；`bidirectional_min_distance()` 随后把两组这些采样点放入
`scipy.spatial.cKDTree` 做**点到点**最近距离。它没有查询“一个点到另一张三角网格
的最近三角面”，也没有连续曲面的误差上界。

这与规划书 §3.2、§7 所写的“以高度场三角面为依据过采样或可审计 guard”及
“三角网格独立最近距离”不一致。有限点集上的最小距离是连续表面最小距离的上界：
两个面片的真实最近点若都落在采样点之间，当前代码可能报出较大的距离并错误放行。
同一缺口也使 `guard=0` 的放行没有连续几何依据；球形包络本身是正确方向，问题在于
顶点离散构造和验收器没有形成可证明的保守闭环。

### 对现有三份候选的补充复核

为判断这是否已影响当前文件，复核时没有使用项目内的 KD-tree 结果，而是将每个
导出 VTP 顶面每个三角形作 4 等分重心采样（每方向 961,230–1,317,600 个点），再由
PyVista/VTK 查询到**另一张三角面**的最近点。结果与交付报告数值相同：

| 样本 | 双向加密三角面抽样最小距离 mm | 当前验收门 mm | 复核结果 |
| --- | ---: | ---: | --- |
| 短毛犬 `af6902eb` | 1.820675 | 1.747959 | 当前文件通过加密抽样 |
| 猫 `d99cb085` | 1.819664 | 1.747959 | 当前文件通过加密抽样 |
| 长毛犬 `aa4fa55c` | 1.832146 | 1.776471 | 当前文件通过加密抽样 |

这降低了三份现有候选出现夹紧的风险，但它是一次性复核，不是仓库内可重复执行的
连续几何验收，不能替代代码修复和回归测试。

### 必须修改的实现

1. 将 `bidirectional_min_distance()` 改为独立的**点到三角面**测距：可使用
   PyVista/VTK cell locator 或 `trimesh.proximity.closest_point`。两个方向都必须测，
   且不得调用 `spherical_envelope()` 或读取其公式场来回填距离。
2. 对每个高度场三角形做确定性可配置细分（至少把现有顶点/边中点/面心替换为完整的
   重心细分格）；在 manifest 记录 `distance_method`、每面细分数、总采样数、
   双向值和误差/停止准则。
3. 对球形包络的源高度场也采用同样的三角面细分来构造包络，或计算并记录一个由
   单元对角线和最大坡度导出的保守 `discretization_guard_mm`。若独立测距失败，自动
   提高细分/guard 后再生成，超出上限则拒绝发布。
4. 新增回归测试：构造“真实最近点位于两个三角面内部、现有 5 类点样本均未命中”的
   反例；旧点到点实现必须错误放行，新实现必须拒绝或加 guard 后通过。现有平面、凸脊、
   单格尖峰测试继续保留，但不再把旧 KD-tree 当作独立验证器。
5. 修复后重新生成三份 `mold_pair` 修订（不能覆盖既有修订），执行完整测试和真实三
   样本复验，并把新 `distance_method` 与双向数值写入交付报告。

## 非阻断观察

1. 当前装配图把闭合的阳模和阴模以接近的实体颜色叠在一起。侧视可见缝隙，但等轴图中
   阳模接触面大多被阴模遮住，不能据此人工检查凹腔细节。M1 的文件输出不受影响；M2
   应提供分离距离、剖切或透明阴模，并分别显示 male/female 接触面和间隙层。
2. 三份源母版均仍是 `visual_review=pending`，且每份有“源分辨率不足”警告。这是正确
   继承，意味着修复 P0 后也只能进入候选/试样流程；母版视觉确认和低起伏试压仍是独立
   前置条件。

## 复验通过条件

M1 可以改为“通过”的必要条件如下：

- 新测距器在代码中对三角面工作，并且 manifest 可复算地说明其方法和采样密度；
- 新增内部最近点反例测试通过，完整非 real-model 测试、ruff、format、strict mypy
  通过；
- 三份真实候选用修复后的管线重新生成，双向三角面测距都不小于
  `t_effective - distance_tolerance_mm`；
- 模具、母版继续保持 `manufacturing_validated=false`，直到用户完成视觉复核与实际试压。

---

## R1 复验（提交 `576937d`，标签 `leather-mold-m1-r1`）

**结论：P0 的测距方法修复通过，但 M1 几何验收仍不通过。**

### 已关闭的部分

- `bidirectional_min_distance()` 已不再使用点到点 KD-tree 作为结果，而是以每面 15 个
  重心细分点，分别计算到对面三角网格的精确点到三角面距离。质心 KD-tree 只用于缩小
  候选面，并有半径证书和球查询兜底；这符合“独立于包络公式”的要求。
- `manifest.json` 与 `mold_pair.npz` 已记录测距方法、细分阶、采样数、双向距离、
  `sampling_bound_mm`、`conservative_min_mm` 及证书统计。
- 内部最近点反例真实存在且测试正确：旧五点点集测距为 0.731 mm（会越过 0.5 mm 门），
  新测距为 0.120 mm，证明本次替换解决了原 P0 的方法缺陷。
- 三份新修订 `5692c8dd`、`b7b3e789`、`5d2e4afc` 已 append-only 生成；
  标签、远端和完整回归可复算。实测：`208 passed, 2 deselected`；ruff、format、
  strict mypy 均通过。

### 未关闭的阻断项：证书化下界没有作为放行门

R1 正确把 `conservative_min_mm = min_mm - sampling_bound_mm` 定义为连续表面的保守下界，
但发布代码仍只判断 `min_mm >= t_effective - distance_tolerance_mm`。这使三份新候选在
原始采样最小值上被放行，而在其声称更严格的证书化下界上全部失败：

| 样本 | `min_mm` | `sampling_bound_mm` | `conservative_min_mm` | 验收门 | 下界是否过门 |
| --- | ---: | ---: | ---: | ---: | --- |
| 短毛犬 `5692c8dd` | 1.825494 | 0.104999 | 1.720495 | 1.747959 | 否 |
| 猫 `b7b3e789` | 1.822858 | 0.107322 | 1.715536 | 1.747959 | 否 |
| 长毛犬 `5d2e4afc` | 1.835879 | 0.081464 | 1.754416 | 1.776332 | 否 |

因此交付报告中“扣除采样界后的证书化下界也过门”与其自身数值矛盾。`certified=true`
只说明每一个**已采样点**到对面三角网格的最近距离计算精确；它不消除采样点之间的
连续表面误差。正是 `sampling_bound_mm` 需要被扣除的原因。

### 必须修正后再复验

1. 在 `LeatherMoldGeometry.generate_leather_molds()` 的 guard 循环和最终拒绝条件中，
   将放行门改为 `clearance_check["conservative_min_mm"] >= t_effective - tolerance`；
   错误信息同时打印原始最小值、采样界和保守下界。
2. 新增集成回归：构造一个 `min_mm` 过门、`conservative_min_mm` 不过门的案例，断言
   guard 继续尝试；若三档后仍失败，stage 必须为空且没有发布修订。
3. 重新生成三份模具修订。优先让 guard 在下界过门时才停止；如果设计上不希望增加
   额外间隙，则提高包络和验收细分阶、重新计算采样界，并把其取舍作为明确参数记录。
4. 更正 [leather-mold-M1.md](leather-mold-M1.md) 的 R1 表格和结论，不能在上述门改变
   前将 M1 写为几何验收通过。

---

## R2 复验（提交 `b887d26`，标签 `leather-mold-m1-r2`）

**结论：M1 软件几何验收通过。**

R2 已将 guard 循环和最终拒绝统一改为：

```text
conservative_min_mm >= t_effective - distance_tolerance_mm
```

因此只有扣除连续表面采样界后的保守下界过门，才能发布 `mold_pair` 修订。新增两条
集成回归分别钉住“原始距离过门但下界失败时必须升 guard”和“三档 guard 后下界仍失败时
必须拒绝且 staging 为空”。

三份 R2 候选的实际 manifest 与 `mold_pair.npz` 已独立复算：

| 样本 | 修订 | guard mm | 原始最小 mm | 采样界 mm | 保守下界 mm | 验收门 mm | 结果 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 短毛犬 | `97f9b67f` | 0.102041 | 1.929910 | 0.104999 | 1.824910 | 1.747959 | 通过（+0.076951） |
| 猫 | `47178876` | 0.102041 | 1.925108 | 0.107322 | 1.817786 | 1.747959 | 通过（+0.069827） |
| 长毛犬 | `ef0a0971` | 0.073668 | 1.910512 | 0.081464 | 1.829048 | 1.776332 | 通过（+0.052717） |

三个修订均包含完整 OBJ/STL/VTP/NPZ/README 文件，核心高度场逐位保持，导出实体水密。
完整复验为 `210 passed, 2 deselected`；ruff、format、strict mypy 以及真实深度模型测试
（`2 passed`）均通过。

本结论只覆盖软件生成的连续三角面间隙、文件完整性和版本可复算性。三个修订继续保持
`visual_review=pending` 和 `manufacturing_validated=false`：用户仍需在 GUI 审看母版与模具，
并完成低起伏测试块和实际皮革试压，才能作出制造可用性结论。
