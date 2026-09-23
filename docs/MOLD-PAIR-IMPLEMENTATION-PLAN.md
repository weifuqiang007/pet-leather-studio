# 皮革压制阴阳模生成规划书

**状态**：待实现。  
**前置输入**：已冻结并通过视觉复核的照片浮雕母版修订。  
**目标**：从一份 `master` 母版生成可 3D 打印的阳模、阴模 OBJ/STL 文件，并保存可复算的配合间隙、皮革参数、版本关系和几何验收结果。

---

## 1. 产品边界

本阶段服务于湿润植鞣革的压制成形：皮革夹在阳模与阴模之间，阳模把浮雕顶起，阴模从正面压入并约束外形。

本阶段交付的是**几何上配对、可打印、可试压的候选模具**，不声明已经验证最佳压力、树脂强度、皮革回弹、脱模寿命或批量生产安全性。每次实物试压必须记录皮革厚度、润湿方式、闭模位置、保压时间和结果，后续以这些记录校准参数。

不在第一版实现：

- 自动预测最佳压机压力；
- 复杂倒扣、多方向脱模或全三维法向布尔偏置；
- 自动生成可靠排气槽、螺钉孔和复杂锁模外壳；
- 未经实物验证就把候选模具标记为量产可用。

---

## 2. 现有基础与改造原则

项目已具备以下基础：

- 照片母版链路会保存 `heightfield.npz`、`master.vtp`、`master.obj`、`master.stl` 和不可变修订 manifest。
- `algorithms/mold_solids.py` 的 `solid_between()` 可从两张高度场构建水密实体。
- `mold_pair()` 已能生成固定 Z 向间隙的候选模具。
- `infrastructure/mesh_geometry.py` 已能导出和重读验证 STL。
- 修订仓库支持 append-only 历史、激活旧版本和篡改检测。

现有 `MeshGeometry.generate()` 的缺口是：它会从 `master.vtp` 重新射线采样，可能降低照片母版的细节；间隙是固定 Z 向 `gap_mm`，没有表达皮革厚度；只导出 STL；没有定位、配合和间隙场报告。

**改造原则**：照片母版优先读取原修订中的 `heightfield.npz`；外部 OBJ/STL/PLY 仍可走现有射线采样兼容路径。高度场是阴阳模核心几何来源，定位孔等辅助特征才允许使用单独网格操作。

---

## 3. 几何定义

### 3.1 坐标和零面

- X 向右、Y 向上、Z 向上，单位均为 mm。
- 母版高度场记为 `h(x, y)`，最低浮雕面为 `z = 0`。
- 阳模底板厚度记为 `backing_mm`。
- 阳模接触面为：

```text
z_male(x, y) = backing_mm + h(x, y)
```

### 3.2 皮革厚度与法向间隙

皮革在斜坡上应按表面法线方向留厚度，不能用全局固定 Z 向间隙代替。

```text
g_x = ∂h/∂x
g_y = ∂h/∂y
n_z = 1 / √(1 + g_x² + g_y²)

t_effective = max(min_clearance_mm, leather_thickness_mm - compression_allowance_mm)
z_gap(x, y) = t_effective / n_z
z_female_inner(x, y) = z_male(x, y) + z_gap(x, y)
```

其中：

- `leather_thickness_mm` 是实际测量的湿润前皮革厚度；
- `compression_allowance_mm` 是预留给湿润皮革压实的余量，必须小于皮革厚度；
- `min_clearance_mm` 防止平面区域形成零间隙；
- `z_gap` 是轴向距离，换算后对应近似恒定的法向皮革厚度。

阴模实体的接触面是 `z_female_inner`，从下方观察形成与阳模对应的凹腔；阴模上方加足够厚的承压背板。阳模与阴模应在同一装配坐标系输出，便于直接导入 Blender、切片软件或装配检查。

### 3.3 模具边框

母版高度场必须带有平坦边框。生成模具前计算主体到版边的最小距离：

- 小于 `edge_margin_mm`：阻止生成，并提示先扩展背景或缩小主体；
- 足够：边框保留为平坦止口，用于闭模和后续加定位结构；
- 主体贴边的旧修订：只能生成“无平边试验模”，manifest 必须记录 warning，不能标记为试压通过。

---

## 4. 参数合同

新增 `LeatherMoldParameters`，替代当前只适用于候选的 `MoldParameters`。所有字段进入 manifest，任何修改都必须产生新模具修订。

| 参数 | 类型与建议范围 | 含义 | 第一版默认值 |
| --- | --- | --- | --- |
| `leather_thickness_mm` | 0.5–6.0 | 皮革实测厚度 | 2.0 |
| `compression_allowance_mm` | 0–1.0，且小于皮厚 | 闭模压实余量 | 0.15 |
| `min_clearance_mm` | 0.1–2.0 | 最小有效间隙 | 0.3 |
| `backing_mm` | 2.0–20.0 | 阴阳模承压底板厚度 | 5.0 |
| `edge_margin_mm` | 2.0–15.0 | 浮雕外的平坦止口宽度 | 4.0 |
| `sampling_feature_mm` | 0.05–2.0 | 需要保留的最小几何特征 | 0.2 |
| `sampling_mode` | `native` / `resample` | 使用母版原高度场或重新采样 | `native` |
| `alignment_mode` | `none` / `external_jig` / `pins` | 合模定位方式 | `external_jig` |
| `vent_mode` | `none` / `manual` | 排气方案 | `none` |

第一版采用 `external_jig`：输出主模具实体和定位说明，定位柱/孔由单独治具或后续版本实现。这样核心压制面不依赖不稳定的网格布尔操作。

---

## 5. 文件与版本产物

每个成功模具修订目录必须包含：

```text
revisions/<mold_revision_id>/
├── male.obj
├── male.stl
├── female.obj
├── female.stl
├── male.vtp
├── female.vtp
├── mold_pair.npz
├── assembly_preview.vtp
├── manifest.json
└── README.txt
```

`mold_pair.npz` 至少保存：

- `male_contact_mm`；
- `female_inner_mm`；
- `axial_gap_mm`；
- `normal_clearance_mm`；
- `dx_mm`、`dy_mm`、宽高；
- 有效主体蒙版与平坦止口蒙版。

manifest 必须保存：母版修订 ID、母版文件哈希、参数、算法版本、采样来源、最小/最大法向间隙、最小边框余量、水密检查、体积检查、相交检查、警告和 `manufacturing_validated=false`。

---

## 6. 实现分期

### M1：原生高度场阴阳模核心

目标：从照片母版的 `heightfield.npz` 直接生成配对 OBJ/STL。

1. 新增 `domain/leather_molds.py`：参数对象、校验、数据结构和端口合同。
2. 新增 `algorithms/leather_mold_pair.py`：梯度、法向间隙场、止口检查、阳模/阴模高度场和几何验收计算。
3. 改造 `PhotoGeometry` 或新增 `LeatherMoldGeometry`：当父修订为照片母版时读取原生高度场，不重新射线采样。
4. 用 `solid_between()` 分别构建阳模与阴模实体，导出 OBJ、STL、VTP、NPZ。
5. 新增 CLI：

```bash
python -m pet_leather_studio --project <project> generate-leather-molds \
  --master <master_revision_id> \
  --leather-thickness-mm 2.0 \
  --compression-allowance-mm 0.15 \
  --backing-mm 5.0 \
  --edge-margin-mm 4.0
```

6. GUI 增加“生成皮革阴阳模”面板：显示参数、预计闭模间隙、警告、三维装配预览和导出目录。

### M2：几何验收与装配预览

目标：让用户在打印前发现不配合、细节损失或边框不足。

1. 三维预览同时显示阳模、阴模内表面和半透明皮革间隙层。
2. 显示最小/最大法向间隙、最陡坡度、最小边框和采样间距。
3. 对母版网格采样和原生高度场分别记录误差；超过 `sampling_feature_mm / 4` 时阻止“精细模具”导出。
4. 新增 `assembly_report.json` 和可读的 `README.txt`，供打印服务商使用。

### M3：定位与试压校准

目标：从“可打印配对模具”进入“可重复试压”。

1. 增加四角外部定位治具；确认稳定后再实现两定位柱两孔。
2. 定位结构必须避开止口与浮雕区，孔/柱的间隙写入参数和 manifest。
3. 增加试压记录：皮革批次、实测厚度、湿润方式、闭模量、保压、干燥、脱模、照片和人工补刻时间。
4. 依据实物结果更新材料预设，不修改既有模具修订。

---

## 7. 验收标准

### M1 代码与几何验收

- 阳模和阴模的 OBJ/STL 均可由 trimesh 重读，水密、法向一致、体积为正。
- 输出坐标与母版一致，单位为 mm；OBJ/STL 边界与高度场误差不超过 `1e-4 mm`。
- `normal_clearance_mm` 全域最小值不小于 `t_effective - 0.02 mm`。
- 阳模与阴模不存在相交；任何采样点的 Z 向间隙均大于零。
- 原生照片高度场路径不重新降采样；如果必须重采样，报告明确最大误差和 `sampling_sufficient=false`。
- 每个输出文件及参数可追溯到唯一母版修订；回退到旧模具不会修改任何历史文件。
- 单元测试覆盖：平面、单坡、圆顶、局部尖峰、边框不足、异常参数和文件篡改。
- 集成测试覆盖：照片母版 → 阴阳模 OBJ/STL → 重新导入 → 配合间隙核验。

### M2 用户验收

- GUI 可同时查看母版、阳模、阴模和间隙层；正面、侧面、斜视图可读。
- 用户可以明确看到皮革厚度、压缩余量、最小法向间隙、警告和模具版本。
- 输出目录内存在四个主文件：`male.obj`、`male.stl`、`female.obj`、`female.stl`。

### M3 实物验收

- 小尺寸测试块和一个完整样本分别完成试压。
- 皮革可顺利放入、闭模、脱模；没有穿孔、明显撕裂或关键轮廓完全塌陷。
- 实物照片和压制参数被关联到对应模具修订。
- 仅完成 M3 后，特定参数组合才可标记为 `manufacturing_validated=true`。

---

## 8. 推荐开发顺序

先实现 M1 的原生高度场、法向间隙、OBJ/STL/NPZ 和自动几何验收；不要先做定位销、排气槽或压机控制。M1 通过后打印一个无浮雕小测试块和一个低起伏样本，使用实测皮厚校准压缩余量；随后再做 M2 装配预览和 M3 定位/试压记录。

当前 P3 母版仍需保留 `visual_review` 和实物试压边界。模具生成必须继承这些状态，不能因为 OBJ/STL 水密就把产品标记为制造合格。
