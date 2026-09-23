# M1 交付：皮革压制阴阳模生成

日期：2026-09-23。基线 `8caf845`（分支 `glm/leather-mold-m1`），完成后打唯一新标签 `leather-mold-m1`。

## 目的

按 `docs/MOLD-PAIR-IMPLEMENTATION-PLAN.md` §6 M1 范围：从照片浮雕母版的 `heightfield.npz` 原生高度场直接生成几何配对、可 3D 打印的阳模/阴模 OBJ/STL，在同一照片工程 RevisionStore 内追加 `kind="mold_pair"` 修订，配齐独立几何验收与可复算的间隙场。不重采样母版、不做定位柱/排气槽（M3）、不做装配分析界面（M2）。

## 实现

- `src/pet_leather_studio/domain/leather_molds.py`（新增）：`LeatherMoldParameters` 冻结数据类（皮厚 2.0 / 压实 0.15 / 最小间隙 0.3 / 底板 5.0 / 止口 4.0 / 最大版面 120.0 / 特征 0.2 / native）与校验矩阵；`effective_thickness_mm`（t_eff = max(min_clearance, 皮厚−压实)，默认 1.85）；`LeatherMoldGeometryPort` 协议；算法版本 `leather-mold-pair-v1` 与 external_jig 声明常量。
- `src/pet_leather_studio/algorithms/leather_mold_pair.py`（新增，纯数值）：单侧最大差分坡度（断崖不折半）；平铺扩边 `expand_heightfield`（核心逐位不变 ×1.0、smoothstep 单调落地、追加纯平止口、超 `max_plate_mm` 拒绝）；球形偏置上包络 `spherical_envelope`（核半径 = t_eff，逐偏移取 max，核参数入 manifest）；`grid_surface_trimesh` + `bidirectional_min_distance`（两面独立三角化，V + 逐面 3 边中点 + 面心采样，cKDTree 双向取最小）；`distance_tolerance_mm = max(0.05, 0.25 × max(dx, dy))`。
- `src/pet_leather_studio/infrastructure/leather_mold_geometry.py`（新增）：`LeatherMoldGeometry.generate_leather_molds` 全链——读母版 npz → 有效止口评估（全有效域记 0，贴边记 0，否则 EDT mm）→ 扩边 → 阳模接触面 = h + backing → 包络 → guard 三档 `(0, 1, 2) × 容差` 逐档独立复测 → 法向间隙场与坡度 → `solid_between` 双实体 → OBJ/STL 导出并 trimesh 重读验水密/边界误差 ≤ 1e-4 mm → VTP/NPZ/README → warnings。guard 加密后仍不达标则拒绝发布。
- `src/pet_leather_studio/application/leather_mold_workbench.py`（新增）：仅接受 `kind=master` 且 `input_method=photo_reconstruction`（legacy source_import 拒绝）；发布前后复验 photo/mask/depth/master 四上游 hash；继承母版 `visual_review`（pending → 警告）与母版警告；发布 `kind="mold_pair"`（parent_id=master、四级上游 id、visual_review=pending、manufacturing_validated=false）；异常整目录 discard，不发布。
- `src/pet_leather_studio/bootstrap/workbench.py`、`src/pet_leather_studio/__main__.py`（扩展）：`create_leather_mold_workbench` 组装；CLI 子命令 `generate-leather-molds --master … --leather-thickness-mm …` 等（JSON 输出，异常返回码 1）。
- `src/pet_leather_studio/presentation/photo_panel.py`（扩展）：模具参数表单与“生成皮革阴阳模”按钮（QProcess 起 CLI，GUI 不写库）；`mold_pair` 修订三维装配视图（male.vtp 象牙 + female.vtp 半透明钢蓝）；详情面板展示独立实测最小距离、扩边、坡度、体积、警告与 pending 继承 ⚠ 行。
- `experiments/photo_relief/run_m1_leather_molds.py`（新增）：复用 R3 三张真实母版（同工程库、追加修订不覆盖），记录机器总账与离屏装配渲染。

验收口径：公式场与实测场分开——包络生成公式不得自证，配合间隙以双面独立三角化测距为准；45° 凸脊同时留有朴素 Z 偏置欠清（≈ t·cos45°）的回归测试，防退回平面近似。单格尖峰（近垂直壁）不可被单值上包络侧向表达：单元测试如实记录 plain 不足，guard 档 2× 容差兜底达标；生产路径 guard 三档自动加密。

## 实际验证

```text
scripts/dev.sh run --frozen python -m pytest tests -m 'not real_model'
    207 passed, 2 deselected（含 tests/gui 17 项真机运行）
scripts/dev.sh run --frozen ruff check .            通过
scripts/dev.sh run --frozen ruff format --check .   通过
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
    通过（strict，无 type:ignore）
```

新增 34 项（旧测试零删除）：单元 `tests/unit/test_leather_mold_pair.py` 13 项（参数矩阵、t_eff 下限、容差公式、断崖不折半、法向 1/√2、平面精确偏置、凸脊 pinch 回归、圆顶、尖峰需 guard、平行面采样数 V+4F、扩边 noop/逐位+止口/超版面拒绝）；集成 `tests/integration/test_leather_mold_geometry.py` 7 项 + `tests/integration/test_leather_mold_revisions.py` 8 项（四上游防篡改、legacy 拒绝、staging 回收、pending 继承、CLI 返回码）；GUI `tests/gui/test_photo_workbench.py` 追加 3 项（参数拼装与拒绝、装配视图分派、pending ⚠ 行）。

真机实验（返回码 0，默认参数全链）：

```bash
scripts/dev.sh run --frozen python experiments/photo_relief/run_m1_leather_molds.py
```

## 几何验收记录（三张 R3 真实母版，t_eff 1.850 mm）

| 样例 | 母版 | mold_pair | 耗时 | 扩边 | 过渡/止口 | guard | 独立最小距离（验收门） | 核心逐位 | 最陡坡度 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 短毛犬 | `9c37b28a` | `af6902eb` | 11.8 s | 60.0→73.9 mm（pad 17 px，182×182） | 2.92 / 4.02 mm | 0.000 | 1.8207 mm ≥ 1.7480 | 是 | 44.8° |
| 猫 | `bef3f6cc` | `d99cb085` | 9.7 s | 60.0→73.1 mm（pad 16 px，180×180） | 2.52 / 4.01 mm | 0.000 | 1.8197 mm ≥ 1.7480 | 是 | 44.2° |
| 长毛犬 | `bdb68708` | `aa4fa55c` | 17.3 s | 60.0×43.3→70.6×53.9 mm（pad 18 px，184×241） | 1.01 / 4.28 mm | 0.000 | 1.8321 mm ≥ 1.7763 | 是 | 43.9° |

- 三者源母版均无有效平边（贴边或余量 1.47 mm < 过渡带），全部走模具侧平铺扩边；扩边核心与源高度场逐位一致。
- 验收门 = t_eff − distance_tolerance_mm（犬/猫 dx=0.408 → 容差 0.102；长毛犬 dx=0.295 → 0.074）。独立测距双向各 29.5 万/28.9 万/39.6 万采样点，guard 均在 0 档即达标（未动用加密）。
- Z 向最小间隙均 1.8500 mm；OBJ/STL 重读水密、法向一致、体积为正（阳模 29468/30236/20945 mm³，阴模 35645/33485/24395 mm³），边界与高度场误差 ≈ 4.8e-07 mm。
- 包络核：半径 = t_eff 1.85 mm（犬/猫 69 偏移、半径 4.53 px；长毛犬 121 偏移、6.29 px）。
- 每修订 4 条警告：external_jig 定位说明（M3 前不暴露为参数）、manufacturing_validated=false、源分辨率不足（native 不降采样但物理间距 0.408/0.295 mm > 特征/4 = 0.05 mm）、母版 visual_review=pending 继承。
- 坡度 43.9°–44.8° 均低于 45° 提示线，无陡坡警告。

## 产物绝对路径

- 模具修订（含 male/female OBJ·STL·VTP、mold_pair.npz、assembly_preview.vtp、README.txt、manifest.json）：
  - `/Users/weifuqiang/Desktop/pet-leather-studio/workspace/photo-relief-p1/20260921-110433/short_hair_dog/revisions/af6902ebf5e1483c8888193395b398f5/`
  - `/Users/weifuqiang/Desktop/pet-leather-studio/workspace/photo-relief-p1/20260921-110433/cat/revisions/d99cb08513b44cb3be21d5c096cc6cc2/`
  - `/Users/weifuqiang/Desktop/pet-leather-studio/workspace/photo-relief-p1/20260921-110433/long_hair_dog/revisions/aa4fa55c3fc343898394cdb159a37899/`
- 机器总账：`/Users/weifuqiang/Desktop/pet-leather-studio/experiments/photo_relief/out/m1-leather-molds/report_data.json`（gitignored 本机证据）。
- 装配渲染（正/侧/斜视 ×3 样例）：`/Users/weifuqiang/Desktop/pet-leather-studio/experiments/photo_relief/out/m1-leather-molds/<key>/<key>-assembly-{front,side,iso}.png`。短毛犬侧视图人工核对：双板齐全、阳模起伏与阴模型腔互为镜像、间隙呈细缝、无相交。

## 未实现与边界

- M2 未做：GUI 间隙层可视化、assembly_report.json、`resample` 采样路径（当前仅 `native`，`sampling_mode` 值已校验但只支持 native）。
- M3 未做：定位柱/孔与排气槽（external_jig 仅 README 说明）；试压记录与材料预设。
- `manufacturing_validated` 恒为 false；模具 `visual_review=pending`，母版 pending 继承为警告——几何验收不替代视觉复核，实物试压前须用户在 GUI 确认母版与模具。
- 球形包络会圆化半径小于 t_eff 的凹谷（规划书 §1 已声明的保守近似）；单格尖峰依赖 guard 兜底。
- 源照片 148 px 量级：模具物理细节受母版采样间距（0.408/0.295 mm）限制，native 不降采样也不凭空增细节。

## 回退版本

分支起点 `8caf845`；开工备份 `runtime/backups/20260923-glm-leather-mold-m1-start.bundle`。修订史 append-only：回退 = 在 GUI 激活旧修订（或 `git revert` 本次提交后重建环境），三份 mold_pair 修订与其母版、照片链历史文件均不被修改或删除。

---

# M1-R1 修复：独立测距换为双向点到三角面（2026-09-23）

独立验收（`leather-mold-M1-acceptance-review.md`）判定 M1 **P0 未过**：内置 `bidirectional_min_distance()` 只做采样点之间的 KD-tree 点到点距离，不能代表连续三角面最小距离。上文 §几何验收记录中旧"独立最小距离"列即该口径（数值上与用户 PyVista/VTK 点到三角面复核 1.820675 / 1.819664 / 1.832146 mm 接近，但方法论无效，不得作为通过依据）。R1 按报告五项要求修复，修复后重新生成三份候选。

## 修改内容（对应验收报告"必须修改的实现"）

1. **双向点到三角面距离**：`bidirectional_min_distance()` 重写。两面各自按三角面**重心细分格**采样（`SUBDIVISION_ORDER=4`，每面 (m+1)(m+2)/2 = 15 点，不去重），对每个采样点计算到**对面整张三角网格**的精确最近距离（Ericson《Real-Time Collision Detection》5.1.5 向量化：3 顶点区 + 3 边区 + 面区，退化三角回退顶点距离）。不调用 `spherical_envelope()`、不读公式场回填。
2. **可复算的方法与密度记录**：manifest/`mold_pair.npz` 记录 `distance_method`、`subdivision_order`、`points_per_face`、双向采样总数、`a_to_b_mm`/`b_to_a_mm`、`sampling_bound_mm`（= 最大棱长 /(√3×order)，子三角外接半径覆盖界）、`conservative_min_mm = min − bound`（真实间隙的**证书化下界**）与 `certificate` 统计（候选面数 96 / 精确槽 8 / 最大外接半径 / 精化点数）。证书口径：第 96 近质心距离 − 最大外接半径 ≥ 当前上界 ⇒ 上界=真值=下界，结果**按构造精确**；不满足的采样点用上界+外接半径做球查询，对面内全部三角矢量化重算。
3. **包络源同一细分 + guard**：`spherical_envelope()` 球心同样取三角面重心细分格（order 4、25 点/格；实测 88/88/148 个不同偏移），与验收器共用同一 `SUBDIVISION_ORDER`（集成测试断言一致）。独立测距不达标时 guard 三档 (0, 1, 2)×容差 逐档**独立复测**，仍不达标拒绝发布。
4. **内部最近点反例回归**：`test_point_to_triangle_interior_nearest_counterexample`——B 的低顶点悬在 A 大三角面内部上方 0.12 mm 处；旧 5 点采样（保留为 `_legacy_point_samples`，仅回归对照）点到点报 0.731 mm，按 0.5 mm 门限会**错误放行**；新验收器报 0.120 mm（最近点对在 A 面内部，`b_to_a_mm`），必须拒绝或加 guard。这正是 P0 缺口的可执行证明。
5. **三份真实候选已重新生成**（见下表；修订史 append-only，旧修订原样保留）。

附带性能修复：初版逐点 Python 精化循环导致 30×63 测试网格单次 generate 24.2 s；改为分块 k-NN 查询 + 矢量化球查询精化后 **1.13 s**（21×），全套件恢复到 64.7 s。真实模具生成 30.7–45.2 s/对。

## R1 验证

```text
scripts/dev.sh run --frozen python -m pytest tests -m 'not real_model'
    208 passed, 2 deselected（新增反例回归 1 项；含 tests/gui 17 项真机运行）
scripts/dev.sh run --frozen ruff check .            通过
scripts/dev.sh run --frozen ruff format --check .   通过
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
    通过（strict，无 type:ignore）
scripts/dev.sh run --frozen python experiments/photo_relief/run_m1_leather_molds.py
    返回码 0，追加三份 mold_pair 修订
```

## R1 几何验收记录（三张真实母版重生成，t_eff 1.850 mm，guard 均 0 档）

| 样例 | 母版 | 新 mold_pair | 耗时 | 双向 a→b / b→a mm | 保守下界（门） | 采样（×2 向） | 证书精化点 | 核心逐位 | 最陡坡度 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 短毛犬 | `9c37b28a` | `5692c8dd` | 30.7 s | 1.825494 / 1.825500 | 1.720495（<1.7480 ✗） | 982 830 ×15/面 | 165 / 166 | 是 | 44.8° |
| 猫 | `bef3f6cc` | `b7b3e789` | 29.6 s | 1.822858 / 1.822892 | 1.715536（<1.7480 ✗） | 961 230 ×15/面 | 121 / 133 | 是 | 44.2° |
| 长毛犬 | `bdb68708` | `5d2e4afc` | 45.2 s | 1.835879 / 1.835936 | 1.754416（<1.7763 ✗） | 1 317 600 ×15/面 | 59 411 / 175 568 | 是 | 43.9° |

- **双向点到三角面最小距离（原始 min_mm）全部过门；但保守下界全部低于验收门**——R1 初版交付文本误写为"下界也过门"，与其自身数值矛盾（初版把 1.7205 ≥ 1.7480 之类的比较写反），已按独立验收复核更正。放行逻辑当时仍判 `min_mm`，属 P1 级阻断，R2 修复（见下节）。`certified=true` 只说明每个已采样点的距离计算精确，不消除采样点之间的连续表面误差——那正是要扣 `sampling_bound_mm` 的原因。
- 与用户独立 PyVista/VTK 复核同向吻合且更保守（1.8255 vs 1.8207 / 1.8229 vs 1.8197 / 1.8359 vs 1.8321，差 ≤ 0.004 mm ≪ 容差 0.102/0.074 mm）。
- 采样密度：每面 15 点（细分 order 4），是旧 5 点口径的 3 倍；采样界 0.105 / 0.107 / 0.081 mm 全部入 manifest。
- 长毛犬（dx 0.295 mm 细网格）证书精化点最多（b→a 13.3%），全部由矢量化球查询兜底，`certified=true`。
- Z 向最小间隙均 1.8500 mm；OBJ/STL 重读水密、边界误差 ≈ 4.8e-07 mm；包络核 order 4 / 25 点每格 / 球心 81.9 万–109.8 万；体积：阳模 29468/30236/20945、阴模 35637/33477/24391 mm³（包络加密后阴模腔略深，体积与 M1 初版相差 <0.03%）。

## R1 产物路径（新修订；旧 `af6902eb`/`d99cb085`/`aa4fa55c` 原样保留可回退）

- `workspace/photo-relief-p1/20260921-110433/short_hair_dog/revisions/5692c8dd…/`
- `workspace/photo-relief-p1/20260921-110433/cat/revisions/b7b3e789…/`
- `workspace/photo-relief-p1/20260921-110433/long_hair_dog/revisions/5d2e4afc…/`
- 机器总账（含完整 method/双向值/证书统计）：`experiments/photo_relief/out/m1-leather-molds/report_data.json`；装配渲染同目录 `<key>/<key>-assembly-{front,side,iso}.png`。

## R1 后边界（不变）

`manufacturing_validated=false`、模具与母版 `visual_review=pending`；几何复验数据如上，**是否记为 M1 几何验收通过由用户按验收报告复验条件判定**；实物试压（M3）前须用户在 GUI 完成视觉复核。球形包络圆化半径 < t_eff 凹谷、单格尖峰依赖 guard 兜底、源照片分辨率边界（0.408/0.295 mm 采样间距）均维持 M1 声明。

R1 完成后打唯一新标签 `leather-mold-m1-r1`（不移动任何旧标签）。

---

# M1-R2 修复：放行门改为证书化保守下界（2026-09-23）

R1 复验结论：点到三角面测距修复通过，但发布逻辑仍判未扣采样界的 `min_mm`——三份 R1 候选的 `conservative_min_mm` 全部低于验收门（见上节更正后的表），且 R1 交付文本"下界也过门"与其数值矛盾（比较方向写反）。`certified=true` 只覆盖已采样点的距离精度，不消除采样点之间的连续表面误差，必须扣 `sampling_bound_mm` 后才构成可证明的放行依据。

## 修改内容

1. **放行门（`infrastructure/leather_mold_geometry.py`）**：guard 循环与最终拒绝都改为 `conservative_min_mm >= t_effective - tolerance`；拒绝信息同时打印原始最小值、采样界与保守下界。`mold_pair.npz` 新增 `independent_conservative_min_mm`；README 与 GUI 详情明示"保守下界 … 为放行门"。
2. **取舍（按验收报告第 3 条）**：guard 在保守下界过门时才停止（实测三份真实候选均在 1×容差档通过），细分阶维持 4 不变——未选择"提高细分阶压采样界"路线，guard 值与采样界均已入 manifest 可审计。
3. **回归测试（`tests/integration/test_leather_mold_geometry.py`）**：
   - `test_conservative_bound_gate_escalates_guard`：ramp 案例复算 guard=0 状态——原始 `min_mm` 1.7129 ≥ 门 1.60（旧口径会放行）而保守下界 1.4491 < 1.60；断言发布结果 guard 升到 1×容差、保守下界 1.7089 过门、间隙真实抬高。
   - `test_conservative_bound_rejects_when_all_guards_fail`：单格 5 mm 尖峰三档 guard 后保守下界仍 0.72/0.99/1.28 < 1.60 → 抛错拒绝且 stage 目录为空。

## R2 验证

```text
scripts/dev.sh run --frozen python -m pytest tests -m 'not real_model'
    210 passed, 2 deselected（新增 2 项保守门回归；含 tests/gui 17 项真机运行）
scripts/dev.sh run --frozen ruff check .            通过
scripts/dev.sh run --frozen ruff format --check .   通过
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
    通过（strict，无 type:ignore）
scripts/dev.sh run --frozen python experiments/photo_relief/run_m1_leather_molds.py
    返回码 0，追加三份 mold_pair 修订
```

## R2 几何验收记录（保守下界过门；guard 均 1×容差档，R = t_eff + 容差）

| 样例 | 母版 | 新 mold_pair | 耗时 | 双向 a→b / b→a mm | 原始 min | 采样界 | **保守下界** | 验收门 | 余量 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 短毛犬 | `9c37b28a` | `97f9b67f` | 45.3 s | 1.929910 / 1.929937 | 1.929910 | 0.104999 | **1.824910** | 1.747959 | +0.0770 |
| 猫 | `bef3f6cc` | `47178876` | 39.2 s | 1.925108 / 1.925108 | 1.925108 | 0.107322 | **1.817786** | 1.747959 | +0.0698 |
| 长毛犬 | `bdb68708` | `ef0a0971` | 110.3 s | 1.910512 / 1.910534 | 1.910512 | 0.081464 | **1.829048** | 1.776332 | +0.0527 |

- **放行依据 = 保守下界**：连续三角面真实间隙 ≥ min − 采样界 ≥ 验收门，三份余量 +0.053～+0.077 mm，这是 R1 缺失的可证明闭环。
- guard 1×容差使包络半径增至 1.952 / 1.952 / 1.924 mm（Z 向最小间隙 = 同值）；阴模腔略深，体积较 R1 变化 <0.1%。
- 双向各 98.3 / 96.1 / 131.8 万采样点（order 4，15 点/面）；证书精化点 392/1210、306/1811、186 243/235 777（细网格长毛犬比例最高），全部 `certified=true`。
- 核心逐位不变 True；OBJ/STL 重读水密、边界误差 ≈ 4.8e-07 mm；坡度 44.8°/44.2°/43.9° 无陡坡警告；每修订 4 条警告不变。

## R2 产物路径（新修订；R1 三份 `5692c8dd`/`b7b3e789`/`5d2e4afc` 与 M1 三份原样保留可回退）

- `workspace/photo-relief-p1/20260921-110433/short_hair_dog/revisions/97f9b67f…/`
- `workspace/photo-relief-p1/20260921-110433/cat/revisions/47178876…/`
- `workspace/photo-relief-p1/20260921-110433/long_hair_dog/revisions/ef0a0971…/`
- 机器总账与装配渲染：`experiments/photo_relief/out/m1-leather-molds/report_data.json` 及同目录 `<key>/`。

## R2 后边界（不变）

`manufacturing_validated=false`、模具与母版 `visual_review=pending`；**是否记为 M1 几何验收通过由用户按验收报告复验条件判定**；实物试压（M3）前须用户在 GUI 完成视觉复核。

R2 完成后打唯一新标签 `leather-mold-m1-r2`（不移动任何旧标签）。
