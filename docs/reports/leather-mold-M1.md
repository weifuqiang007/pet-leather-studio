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
