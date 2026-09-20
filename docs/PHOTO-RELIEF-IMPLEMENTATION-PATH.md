# 猫狗及花卉照片到浮雕母版：实施路径

日期：2026-09-20。本文细化 IMPLEMENTATION-REFOCUS-v0.1.md 阶段 B；为实施计划，不表示照片重建已实现。

## 现有素材与输入边界

| 文件 | 实际尺寸 | 可验证 | 不适合验收 |
|---|---|---|---|
| images/长毛犬.jpeg | 205×148 | 趴卧全身大形、头身关系、白毛与白背景分割 | 单根毛发、细小五官几何 |
| images/短毛犬.jpeg | 148×148 | 头部与上身、耳朵/口鼻、前后关系 | 被裁掉身体、细纹 |
| images/猫.jpeg | 148×148 | 猫头与上身、耳朵/口鼻、花纹与形体区分 | 被裁掉身体、细纹；可见文字水印可能干扰 |

三张足够开始输入、分割和粗形体实验，不足以验收精细重建。此轮没有花卉输入，不能宣称已验证荷花。建议精细实验获取原始高分辨率照片，主体长边尽量达到约 1000 像素或以上；这是采集建议而非硬性合格线，清晰度、遮挡和光照同样重要。放大图片不会增加可验证的原始细节。

不要求用户先抠背景。保留原图，另外生成 foreground_mask；抠图预览只作派生产物。白毛白底处支持修正蒙版。无主体区域不参与深度归一化；不把阴影当作身体。缺失身体默认保留构图裁切，不自动幻想补全。若为审美需要生成补全，必须单独标记生成区域。

## 顺序、产物与质量门

1. **输入检查与版本登记**：读取原始尺寸/hash，提示低分辨率、水印及裁切（自动检测不能保证，允许人工标记）。保存源文件只读副本和输入记录。验收：不改原图，不把超分辨率当细节恢复。
2. **主体分割**：生成独立蒙版，叠加检查耳朵、爪子、尾部等；支持添加/擦除/撤销。验收：保留可见主体，不含大块背景；白毛边缘允许人工修正。蒙版修订有版本。
3. **基础形体估计实验**：评估通用单图深度方案，输出深度、坐标约定和中性网格。主体可为头部、半身或全身，不绑定人脸拓扑。验收：鼻子、躯干、四肢等可见结构的前后关系合理；黑色毛斑不因颜色被刻成坑。没有可信形体时记录失败，不以规则鼓包替代成功结果。
4. **参考高度标定与浮雕化**：区分有效正面、背景/基底和异常点；记录整体高宽比、局部起伏与单位。人物 OBJ 仅为高度风格参照，不强行套用到动物全身。提供等比例模式和受控压缩模式、最大起伏约束。以同一基准做 80%/100%/120% 对照，这只是审美实验档位。验收：侧面不过度突出，正面结构仍清楚；基底厚度不混入浮雕起伏。
5. **局部结构调整**：在可信基础形体上，刷选鼻子、口鼻、耳朵、躯干或花瓣，控制局部偏移、过渡和边缘。总高度约束持续生效；参数与区域可撤销。验收：调整局部不会把整个主体一起拔高，不产生尖峰或高度越界。
6. **多尺度细节实验**：独立处理大形、发束/花瓣结构、微纹。细节应来自图像结构或明确的生成推测，不能直接将亮度当高度。对现有缩略图暂停细毛验收；先获得足够清晰的照片。验收：换光照的无贴图视图仍有合理细节；不是贴图、阴影坑或随机噪声。
7. **母版导出与版本**：保存 OBJ/STL、深度/蒙版/调整记录、来源及算法模型版本。预览 LOD 与真实几何分开。验收：源图→参数→母版可追溯；导出真实网格，打印实体封闭性按后续模具需求检查。
8. **接现有阴阳模模块**：选定已认可母版后生成候选。当前固定低采样上限可能丢细节，须补充足够分辨率与偏差评估，不能只靠母版看起来精细。验收：比较母版与模具接触面误差；实际打印/皮革试压为独立质量门。

## 执行优先级

先短毛犬（头部与上身结构）、再猫（花纹不等于起伏）、再长毛犬（全身与白毛边界）。当前三图只用于前三步和粗形体比较。第一轮不下载多个大型模型：先做本地兼容性与许可筛选，选一个通用深度基线进行真实推理；输出不合格再有针对性比较第二条路线。猫狗与荷花分别评审，不能用一张成功样例代表所有类别。

## 工程规则

沿用 domain/application/infrastructure/presentation 分层和当前数据修订机制；推理在后台任务执行，可取消。每种算法输出统一深度约定、有效蒙版和来源信息；不假造模型置信度。模型权重放项目内 models/<provider>/<model>/<revision>/，推理依赖放项目本地独立环境，缓存放 .cache；模型来源、版本、许可和 hash 写入清单。先验证本机可运行性，不假定 CUDA 可用，不修改全局环境。

每阶段保留失败结果与验收记录；代码提交和数据修订分别管理，不覆盖 v0.1.0。未经过用户评审的相似度、未试压的加工效果不能自动标为通过。

## GLM 开发合同：范围与交付顺序

以下是待实现要求，不是现有功能声明。先阅读本文、IMPLEMENTATION-REFOCUS-v0.1.md、REFERENCE-TARGET-CORRECTION.md、reports/mold-workbench-v0.1.md，再读取实际代码。旧 PRD 的粗区域鼓包路线不恢复。

- P1：输入版本、蒙版、真实通用深度基线及中性几何预览；先用三个现有样本验证大形。不得以只有界面或模拟推理完成 P1。
- P2：参考高度标定、受控浮雕化、局部调整与母版导出；可先用已知几何做数值开发，照片效果单独验收。
- P3：获得更清晰照片后开展毛流/细纹实验；现有缩略图不支持精细效果验收，不因此阻塞 P1/P2 的工程交付。
- P4：母版接模具及采样偏差检查；物理成形仍需另行试验。

每阶段单独提交并写报告；视觉效果不通过时不得宣称整条链路已完成。不一次铺开扫描、机械臂、FreeCAD、有限元、云服务等无关功能。

## 代码路径与职责

所有路径相对仓库根目录；下表标“新增”的文件当前不存在。可在保持职责边界的前提下细分文件，变更路径必须更新本文。

| 路径 | 状态 | 职责及禁止事项 |
|---|---|---|
| `src/pet_leather_studio/domain/photo_relief.py` | 新增 | 参数 dataclass、输入/推理/参考标定结果描述、阶段枚举；只用标准库，不导入 Qt/Torch/NumPy/SQLite |
| `src/pet_leather_studio/domain/photo_ports.py` | 新增 | 分割、深度、几何、模型清单端口；以路径及类型化元数据跨进程传递，不传 GPU 对象 |
| `src/pet_leather_studio/application/photo_workbench.py` | 新增 | 导入、分割、保存蒙版、推理、生成母版用例；依赖注入，协调校验/修订，不写模型或 UI 算法 |
| `src/pet_leather_studio/algorithms/relief_height.py` | 新增 | 有效区域归一化、深度方向转换、浮雕压缩和局部高度约束；纯数值函数，禁止文件/网络/UI 副作用 |
| `src/pet_leather_studio/algorithms/relief_detail.py` | P3 新增 | 多尺度细节操作；未通过实验前不默认启用，不从亮度直接造高度 |
| `src/pet_leather_studio/infrastructure/photo_io.py` | 新增 | Pillow 解码、EXIF 方向归一化、派生图和坐标变换、输入验证 |
| `src/pet_leather_studio/infrastructure/photo_inference.py` | 新增 | 调用隔离推理进程，验证模型清单、输出格式、设备、错误与取消；不在模块导入时下载或加载权重 |
| `src/pet_leather_studio/infrastructure/photo_geometry.py` | 新增 | 将高度数据转换为 VTP/OBJ/STL 和 LOD；复用已有实体算法，记录单位及几何检查 |
| `src/pet_leather_studio/infrastructure/reference_profile.py` | 新增 | 参考 OBJ 正面及基准选择、测量与标定文件；不把包围盒 Z 跨度直接等同有效浮雕高度 |
| `src/pet_leather_studio/presentation/photo_panel.py` | 新增 | 照片/蒙版/深度/中性模型切换、阶段状态及参数表单；不直接导入推理库 |
| `src/pet_leather_studio/presentation/mask_editor.py` | 新增 | 叠加、缩放、画笔添加/擦除、撤销/重做；坐标映射独立测试 |
| `src/pet_leather_studio/bootstrap/workbench.py` | 扩展 | 组装新旧服务，不放算法 |
| `src/pet_leather_studio/__main__.py` | 扩展 | CLI 子命令，复用应用服务，不能另写一条不同业务流程 |
| `src/pet_leather_studio/infrastructure/revisions.py` | 受控扩展 | 复用修订及锁；兼容旧数据、失败恢复和完整文件校验 |
| `src/pet_leather_studio/application/mold_workbench.py` | 必须修改接缝 | 支持照片母版来源，明确拒绝把 photo/mask/depth 修订当作 master；去掉模具来源写死 source_import 的假设 |
| `src/pet_leather_studio/presentation/workbench.py` | 受控扩展 | 新种类修订的显式分派；当前“非 master 就当 mold”逻辑须改，未知种类友好报错 |
| `scripts/photo_inference_worker.py` | 新增 | 隔离环境进程入口；使用参数列表启动，不拼 shell；调用模型适配器并写中间结果 |
| `scripts/setup_photo_models.py` | 新增 | 显式安装/下载与校验命令；支持已有本地权重，不把下载塞进程序启动 |
| `experiments/photo_relief/` | 新增 | 真实模型比较脚本及可重跑配置；与正式产品代码分开 |
| `docs/reports/photo-relief-P1.md` 等 | 新增 | 每阶段检查、样本表现、失败、依赖、耗时/内存及视觉待评审记录 |

### 建议的服务接口

实现前落实为带类型注解的接口，返回修订描述；所有 revision_id 均由程序生成并校验：

```python
import_photo(source: Path) -> RevisionSummary
segment_photo(photo_id: str, model_id: str) -> RevisionSummary
save_mask(photo_id: str, mask_path: Path, parent_id: str) -> RevisionSummary
estimate_depth(photo_id: str, mask_id: str, model_id: str) -> RevisionSummary
build_master(depth_id: str, parameters: ReliefParameters) -> RevisionSummary
```

`RevisionSummary` 与 `ReliefParameters` 定义在 domain。模型 worker 输出候选文件，校验成功后应用层才发布。蒙版和深度必须引用同一照片及变换；尺寸相同但来源不同也应拒绝混用。修改蒙版后旧深度保留，界面标为旧依赖，不能静默套用。

## 数据协议与来源追溯

沿用 `workspace/<project>/project.sqlite` 与 `revisions/<uuid>/`。新增 photo、mask、depth 修订；最终母版仍使用 `kind=master`，增加 `input_method=photo_reconstruction`。旧 OBJ 导入保留 `source_import`。模具必须继承实际 master 来源与 ID。

每个修订内文件先用扁平布局，因为现有 RevisionStore 只对顶层文件建 hash 清单；不得悄悄放嵌套文件而不校验。若改成递归清单，必须同时升级路径安全和旧清单兼容测试。

| 修订 | 至少包含 |
|---|---|
| photo | 原文件副本、方向归一化派生图、原始/工作尺寸及坐标变换 |
| mask | `mask.png`（0–255 的主体覆盖率，使用阈值需记录）、photo_id、人工修改记录 |
| depth | `depth.npz`（二维 float32 数据、布尔 valid 数组；可选 confidence）、photo_id、mask_id、原生深度类型、方向转换及推理元数据 |
| master | `master.vtp`、`preview.vtp`、`master.obj`、`master.stl`、`heightfield.npz`、参数和上游引用；形状或封闭性不满足时不得标为成功可用母版 |

统一约定：工作图左上原点、x 向右、y 向下；几何 X 向右、Y 向上、Z 越大越凸。显式完成 Y 翻转及深度方向转换，禁止靠肉眼临时取反。模型的深度、逆深度、相对深度必须先记录原生语义再适配；浮雕毫米是设计尺度，不冒充测量得到的动物真实尺寸。

无效区域用 valid/mask 表达；有效区域不得有 NaN/Inf，空蒙版、恒定深度或有效面积不足时明确报错。存储无效位置可填零，但不得参与归一化和高度统计。模型没有 confidence 时不伪造一个置信图。

manifest 增加 `schema_version`（元数据版本）、上游 ID/hash、模型/代码版本、参数、设备、耗时、质量警告、`visual_review=pending`、`manufacturing_validated=false`。采用加字段兼容旧 schema 时，读取旧记录要有明确默认；破坏兼容时提供备份及迁移测试，旧代码不得静默写入不认识的数据格式。

### 高度与可调参数规则

- `width_mm` 与最大起伏沿用当前数值范围作工程输入边界，不解释为物理安全范围。
- `height_mode` 至少区分 reference_ratio 与 explicit_depth。reference_ratio 必须有有效 profile_id；没有标定时拒绝该模式，不暗用 14.93% 包围盒比例。
- 同比例参考模式：有效参考起伏/明确的参考宽度 × 当前对应宽度；参考部位与目标部位不对应时需提示并由用户选择显式深度。
- 整体深度、局部偏移、细节强度、平滑程度分开存储。局部偏移单位 mm；平滑半径说明是 mm 还是像素，显示尺度转换。
- 任何合成或局部编辑之后，最终浮雕起伏须在所设上限内；若压缩/限幅改变用户操作，应显示改变范围，不无提示地截断。
- 浮雕基准为 0，底板另计。正面母版与加底后的实体的起伏/厚度分别记录；接模具时不能把实体背面当作正面基准。
- 模型分辨率、原图尺寸、网格采样和 LOD 是四个不同参数，不能用插值或面数冒充输入细节。

## 本地依赖与任务约束

推理环境建议 `.venv-photo/`，下载 Python 放 `.tools/`，模型按前文 `models/` 路径，Hugging Face/Torch/uv/pip 缓存分别固定到项目 `.cache/` 子目录。补齐 `.gitignore`，不提交权重、用户照片或运行产物；依赖用独立锁文件，例如 `requirements/photo-inference.lock`，记录实际安装命令与版本。不能修改现有桌面环境解决模型依赖冲突。

先检查本机架构及 CPU/MPS 支持，真实运行单图再宣称兼容；不默认安装 CUDA 包。下载记录代码与权重分别的许可、来源、版本/提交及 SHA-256；许可不清的模型不能作为默认产品模型。下载失败或离线要能选择本地文件或明确失败，禁止偷偷换算法。不得上传用户照片到远程 API。

耗时任务独立进程，取消应终止其子进程、释放写锁，不推进 active revision。崩溃后残留 staging 要能识别、隔离及显式清理，不能误删其他正在执行的任务目录。当前工程写锁可以保持串行；不为提高并行度取消锁。发布前检查上游 hash 与当前任务来源。

遵守 PEP8 及当前 Ruff 配置（100 列）；domain/application 完整类型注解，禁止大范围 noqa/type: ignore。算法参数禁止散落魔数；新后端通过端口接入，不在 UI 中堆叠模型特例。测试桩只允许在 tests，产品不能返回模拟推理成功。

## 验证条件与测试文件

“工程通过”与“视觉通过”分开报告。数值阈值是软件验收阈值，不等于皮革加工公差。

| 编号 | 验收条件 | 测试/证据路径 |
|---|---|---|
| PH01 | 三张原图 hash 不变；EXIF 方向及工作尺寸变换正确；坏文件明确失败 | `tests/unit/test_photo_io.py` |
| PH02 | 空/错尺寸/错来源蒙版拒绝；画笔缩放映射误差不超过 1 工作像素；撤销后像素完全恢复 | `tests/unit/test_mask_coordinates.py`、`tests/gui/test_mask_editor.py` |
| PH03 | 用已知斜坡/阶梯验证深度类型适配、Y 翻转和 Z 方向；黑白测试纹理不能直接决定高度 | `tests/unit/test_relief_height.py`；真实照片另看 PH09 |
| PH04 | 主体外无效数据不影响有效高度；NaN/Inf/恒定深度/空有效域按约定拒绝；最大起伏误差 ≤ 1e-4 mm | `tests/unit/test_relief_height.py` |
| PH05 | 参考包围盒与有效浮雕高度分开记录；缺 profile 禁止参考模式；尺寸缩放及局部约束可重跑 | `tests/unit/test_reference_profile.py` |
| PH06 | OBJ/STL 重读后单位、朝向、边界一致；实体封闭、正体积、有效数值；实际导出起伏误差 ≤ 1e-4 mm | `tests/integration/test_photo_geometry.py` |
| PH07 | 原图→蒙版→深度→master→mold 可追溯；模具不再写死 source_import；旧 OBJ 与历史仍能使用 | `tests/integration/test_photo_revisions.py` |
| PH08 | 错误/取消/强制结束不新增成功修订、不改变 active；重启可再次生成；篡改输入拒绝使用 | `tests/integration/test_photo_jobs.py`、`tests/gui/test_photo_workbench.py` |
| PH09 | 三张真实图片均运行真实模型；逐张记录前后关系、错误凹凸、裁切与细节限制；不以合成测试代替 | `experiments/photo_relief/`、`docs/reports/photo-relief-P1.md` |
| PH10 | GUI 可切原图/蒙版/深度/无贴图三维，正侧斜视与至少两种光照；预览和实际导出一致；未知种类不崩溃 | `tests/gui/test_photo_workbench.py` + 实际屏幕截图 |
| PH11 | 本地模型清单/hash 验证；缺模型/损坏模型/离线错误清晰；未请求安装时不联网下载 | `tests/integration/test_photo_inference.py` |
| PH12 | 精细效果需高清输入的无贴图对照、局部截面及用户评审；现有小图必须标 blocked_by_input_quality，不填通过 | `docs/reports/photo-relief-P3.md` |

通用单元测试使用小型可解释数据；模型测试分成协议测试与独立的真实模型测试，使用明确 marker，例如 real_model，并在 pyproject.toml 注册。缺权重时可 skip，但报告必须写清“真实推理未验证”，不能用其余测试通过宣布 P1 完成。

至少执行并记录：

```bash
scripts/dev.sh run --frozen ruff check .
scripts/dev.sh run --frozen ruff format --check .
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
scripts/dev.sh run --frozen pytest tests/unit tests/architecture tests/integration -m 'not real_model'
# 以下需本地图形会话/实际已安装模型环境
scripts/dev.sh run --frozen pytest tests/gui
scripts/dev.sh run --frozen pytest tests/integration -m real_model
```

真实模型测试由桌面测试进程调用隔离环境 worker，不把推理依赖塞进桌面环境。已有 26 项测试保持通过；新增架构测试阻止领域/应用层反向依赖 infrastructure/presentation。检查失败要修复或明确记录阻塞，不删除旧测试掩盖失败。

## 版本、交付和给 GLM 的执行指令

开始前记录 Git 状态，保留用户未提交修改；从当前已提交状态建立新的开发分支，例如 `glm/photo-relief-p1`，若已存在则先检查，不覆盖或强制重置。保留 `baseline-before-mold-refocus-20260920` 与 `mold-workbench-v0.1.0` 两个旧标签；阶段完成后普通提交，新增唯一发布标签，不移动旧标签。不自动推送或覆盖远程历史。

每次报告列出：实现阶段、修改路径、命令/返回码、各 PH 状态、实际模型与下载位置、三个样例表现、截图/产物绝对路径、未实现项、回退版本。技术测试通过但视觉待评审时，保持 visual_review=pending；用户否定后记录 rejected，不替用户勾选。

可直接给 GLM：

> 按 docs/PHOTO-RELIEF-IMPLEMENTATION-PATH.md 开发，先检查当前代码与已有版本，完成 P1 的本地真实推理闭环，逐步推进 P2；不要一次扩展所有后续功能。严格遵守代码分层、输入来源、坐标/高度协议、本地依赖和 PH 验收条件。现有三张小图只验收分割与粗形体，不能宣称细毛重建。保留 OBJ 导入、阴阳模和版本回退；修复旧 master/mold 分派及 source_import 写死的集成接缝。提供真实模型运行证据与未通过项，禁止用鼓包、贴图或模拟推理冒充完成。
