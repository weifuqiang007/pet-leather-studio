# 宠物皮革浮雕工作台：产品需求与工程实施规范

- 文档版本：1.0
- 日期：2026-09-18
- 项目代号：Pet Leather Studio
- 适用对象：产品负责人、GLM 编程代理、Python/Qt 开发者、建模与模具服务商
- 文档性质：PRD + 架构约束 + 实施顺序 + 验收合同
- 当前交付物是规范，不表示程序、材料仿真或实物工艺已经完成验证。

## 0. 给实施代理的执行约定

1. 先读完整文档，再按第 15 章的里程碑实施，不要一次生成大量未验证的空壳代码。
2. 优先交付可离线运行的基础闭环：照片导入、人工标注、参数化浮雕、三维查看、测试块和打印文件导出。
3. AI 自动分割、AI 深度估计是增强能力。必须提供人工路径；不得把占位数据或规则生成冒充 AI 推理。
4. 用户已有 Blender，但安装路径和版本尚未核实。允许探测和手动配置，不重新安装、不修改已有 Blender 环境。
5. 用户尚未安装 FreeCAD。本期禁止将 FreeCAD 作为启动依赖；只定义接口与能力状态，不自动下载 FreeCAD。
6. 所有为本项目下载的模型、Python 包、工具、缓存必须放入本项目本地目录。不得默认散落到系统 Python、全局 site-packages 或用户全局模型缓存。
7. 不访问云端推理，不上传宠物照片；联网下载模型必须由资源管理器中的显式操作触发，普通启动和打开项目不得联网下载。
8. 不生成或执行真实机器人控制指令。本期刀路是设备无关的预览数据。
9. 未校准的仿真必须标为“未校准”；没有求解器不能伪造应力云图。三维动画不是力学仿真。
10. 每个里程碑交付代码、测试结果、演示步骤和已知限制；不得仅凭按钮存在就宣布完成。
11. 不把本规范中的测试尺寸当作实际皮料的成熟工艺参数，不臆造压机吨位、材料强度或扫描精度。
12. 任何变更写入 docs/adr/；接口保留应小而明确，不提前搭建插件市场、微服务或消息中间件。

## 1. 项目背景与目标

### 1.1 背景

用户希望在没有熟练皮雕师傅的情况下，将宠物照片制作成皮革浮雕挂件。当前拟采用：照片生成浅浮雕及纹理，3D 打印配套模具，湿润植鞣革压制成形；局部细纹先由人工补刻，上色可外包，填充、背皮粘贴与装配由人工完成。

主要未知因素是：模型相似度、打印纹理可制造性、模具承载、皮革贴合与回弹、细纹转印效果。软件用于设计、检查、追溯和比较，不能替代材料试验。

### 1.2 产品目标

- 把照片、标注、浮雕、模具、试压样品、质检结果建立可追溯关系。
- 所有关键建模阶段均可三维查看、可修改、可回退。
- 无模型权重、无 FreeCAD、无扫描仪时仍能完成基础设计和打印文件导出。
- 为后续 Blender 编辑、材料仿真、扫描质检和补加工刀路保留清晰边界。
- 让软件给出可核查的数据与建议，而不是无法复核的“AI 评分”。

### 1.3 非目标

本期不建设商城、支付、团队权限、云端服务、自动接单；不训练基础模型；不要求完整三维动物头重建；不承诺任意照片一键获得生产级模具；不直连相机/扫描仪厂商 SDK、压机或机械臂；不预测未经标定的最佳压力；不承担模具结构安全认证。

### 1.4 用户与核心任务

- 项目负责人：导入照片、调整形体、比较版本、导出打样包。
- 打印/模具服务商：获得真实尺寸、模具几何、来源版本和待确认项。
- 精修/上色人员：获得标记清楚的任务单和参考图。
- 后续开发者：替换模型、求解器或设备适配器，不改变核心业务。

## 2. 范围分级与完成定义

| 层级 | 内容 | 本轮要求 |
|---|---|---|
| R1 核心版 | 本地项目、素材标注、参数化浅浮雕、三维交互、毛流/测试块、基础模具候选、文件导出、任务/资源管理 | 必须实现 |
| R1 集成 | 现有 Blender 探测及文件往返、材料参数录入、几何规则检查、试压记录 | 必须实现；Blender 缺失时可降级 |
| R1 增强 | 本地 AI 分割/深度适配 | 完成接口、资源流程和能力验证；只有真实本地模型通过测试才称可用 |
| R2 质检版 | 扫描文件导入、刚性配准、偏差计算、照片人工缺陷标注、精修报告 | R1 通过后实施 |
| R2 刀路预览 | 选定缺陷区域对应曲线、贴合实际表面、工具包络预览 | R2 质检完成后实施，不发设备指令 |
| R3 物理/设备版 | FreeCAD、有限元求解器、经校准的皮革成形、自动视觉判缺、设备指令后处理 | 本轮仅保留必要协议，不能算已交付能力 |

R1 的“基础模具”限定为沿 Z 方向可成形、无倒扣的浅浮雕候选。复杂曲面法向偏置、全自动排气设计、真实压力计算不在 R1。

## 3. 技术选型与运行形态

### 3.1 采用桌面应用

采用 Python + PySide6（Qt for Python）+ Qt Widgets。用户所说 PyQt 视为 Python Qt 桌面方案，具体绑定统一使用 PySide6，不混装 PyQt5/PyQt6。

不做浏览器前后端和本地 HTTP 服务。这里的“前端”是 Qt 展示层，“后端”是同机应用服务、算法模块与独立工作进程。

| 层次 | 选型 | 边界 |
|---|---|---|
| Python | 首选 3.11.x，按本机依赖兼容性锁定 | 不使用未测试的最新版本 |
| 窗口与控件 | PySide6 / Qt Widgets | GUI 仅处理展示、用户输入、状态同步 |
| 三维查看 | PyVista + pyvistaqt + VTK | QtInteractor 嵌入主窗口；渲染仅在 GUI 线程 |
| 图像处理 | Pillow、NumPy；必要时 opencv-python-headless | 避免 OpenCV 自带 GUI 与 Qt 冲突 |
| 几何数值 | NumPy、SciPy、trimesh；实际需要再增依赖 | 不把 VTK 对象作为核心领域对象 |
| 本地数据 | SQLite 元数据 + 文件产物 + 版本化 JSON | 大图片/网格不塞进数据库 |
| 配置 | TOML；JSON Schema/Pydantic 用于外部数据校验 | 版本固定，不依赖宽松的隐式转换 |
| 测试 | pytest、pytest-qt、Ruff、mypy | 几何测试可脱离 GUI 执行 |
| 包管理 | 项目内 uv 或明确配置的已有 uv | uv.lock 锁定实际验证组合 |
| Blender | 已安装程序，子进程与文件协议 | 不把 Blender Python 包装入主环境 |
| FreeCAD/FEM | 接口预留 | 不安装，不阻塞核心功能 |

### 3.2 必须先做兼容性验证

在开发完整 UI 前验证本机 CPU 架构、系统版本、内存、可用空间、Python wheel 可用性和 VTK 渲染。硬件信息写入 runtime/system_profile.json。

冒烟测试：启动 PySide6，嵌入 QtInteractor，显示并旋转一个网格，正常关闭。不能以 mock 渲染通过替代真实本机验证。失败时记录根因、选兼容依赖版本；不要悄悄换成截图查看器。

AI 默认具备 CPU 回退路径；Apple Silicon 的 MPS 仅在模型实际支持并通过测试后启用，不能默认要求 NVIDIA/CUDA。

## 4. 架构：高内聚、低耦合

### 4.1 依赖方向

```text
presentation (Qt Views/ViewModels)
            ↓
application (use cases / jobs / DTOs)
            ↓
domain (entities / invariants / Protocol ports)

algorithms → domain
infrastructure → domain (实现仓储、文件、外部工具等端口)
bootstrap → 组装上述实现并注入 application
```

- domain 不导入 Qt、VTK、SQLite、Blender 或模型框架。
- application 只依赖领域和注入的端口，不直接拼 subprocess 命令或执行 SQL。
- algorithms 不导入 UI；以明确的数值数组/数据类作为输入输出。
- infrastructure 不操纵窗口；返回结果、事件和错误。
- presentation 不执行文件导出算法、模型推理、SQL、网格布尔或质检计算。
- 只有 bootstrap/composition root 知道所有具体实现。
- 通过 import-linter 或 AST 依赖测试检查规则，禁止循环导入。
- 禁止全局“当前项目”单例、全局可变网格、任意模块可发布任意事件的万能消息总线。

### 4.2 工程目录

```text
pet-leather-studio/
  pyproject.toml
  uv.lock
  README.md
  .gitignore
  .env.example
  docs/
    PRD.md
    architecture.md
    acceptance.md
    adr/
    reports/
  configs/
    defaults.toml
    material_examples/             # 明确标为示例，非实测
    schemas/
    model_catalog.json             # 可用模型与版本/许可清单，不含权重
  scripts/
    bootstrap.py
    launch.py
    doctor.py
    download_resource.py
    build_offline_bundle.py
  src/pet_leather_studio/
    __main__.py
    bootstrap/
      environment.py
      container.py
    domain/
      projects.py
      artifacts.py
      geometry.py
      annotations.py
      materials.py
      inspection.py
      toolpaths.py
      errors.py
      ports/
    application/
      projects/
      imaging/
      modeling/
      molds/
      inspection/
      production/
      jobs/
      resources/
    algorithms/
      image_preprocessing/
      relief/
      texture/
      mold_geometry/
      geometry_checks/
      registration/
      deviation/
      toolpath_preview/
    infrastructure/
      persistence/
      filesystem/
      workers/
      model_providers/
      blender/
      freecad/                    # 仅 capability/协议适配占位，不伪实现
      simulation/                 # 同上
      exporters/
    presentation/
      main_window.py
      navigation.py
      projects/
      image_editor/
      model_editor/
      mold_editor/
      inspection/
      production/
      settings/
      shared_widgets/
      resources/
  tests/
    unit/
    integration/
    gui/
    architecture/
    fixtures/                     # 小型合成数据，可提交
  .venv/                          # 主环境，不提交
  .tools/                         # 本地 uv/Python 等，不提交
  .cache/                         # 本项目下载缓存，不提交
  models/                         # 版本固定的权重、清单，不提交大文件
  vendor/                         # 下载包、许可证、可离线安装依赖
  runtime/                        # 日志、临时文件、任务输出，不提交
  workspace/                      # 用户项目，不提交
```

每个特性内部围绕自己的用例组织，公共控件仅在真实复用后抽取。禁止新建逐渐承包一切的 utils.py、manager.py、common.py。

## 5. 本地资源、依赖与模型下载规范

### 5.1 根目录与路径

源码根目录定义为 APP_ROOT（由脚本位置解析，不依赖启动时 cwd）。默认 DATA_ROOT=APP_ROOT。允许用户在设置中更换本地 DATA_ROOT，但迁移须校验剩余空间、内容校验和并保持旧目录直到迁移成功。

不可在源码中写死 /Users/weifuqiang 或某个桌面路径。用户选择的已有 Blender 可执行文件允许位于 APP_ROOT 外，但本项目新增下载物必须位于上述本地根目录内。

Windows/macOS/Linux 使用 pathlib。中文、空格、括号、# 等路径须在测试中覆盖。

### 5.2 下载目录约定

| 资源 | 目录 |
|---|---|
| 主程序依赖安装位置 | APP_ROOT/.venv/ |
| 可选 AI 隔离环境 | DATA_ROOT/runtime/envs/<provider-id>/ |
| Python 包归档 | DATA_ROOT/vendor/python/<os>-<arch>-py311/ |
| uv 缓存 | DATA_ROOT/.cache/uv/ |
| pip 缓存（如确需） | DATA_ROOT/.cache/pip/ |
| 本项目 Python 运行时 | DATA_ROOT/.tools/python/ |
| 工具下载及安装 | DATA_ROOT/.tools/ 或 vendor/tools/ |
| 模型权重 | DATA_ROOT/models/<provider>/<model>/<revision>/ |
| Hugging Face 缓存 | DATA_ROOT/.cache/huggingface/ |
| PyTorch 缓存 | DATA_ROOT/.cache/torch/ |
| 临时与中间结果 | DATA_ROOT/runtime/tmp/<job-id>/ |
| 用户工程 | DATA_ROOT/workspace/<project-id>/ |

bootstrap/launch 必须在导入第三方 ML 库前设置环境。至少覆盖 UV_CACHE_DIR、UV_PROJECT_ENVIRONMENT、UV_PYTHON_INSTALL_DIR、PIP_CACHE_DIR、HF_HOME、HF_HUB_CACHE、HF_XET_CACHE、HF_ASSETS_CACHE、TORCH_HOME、XDG_CACHE_HOME、TMPDIR/TEMP/TMP；如启用相应库，覆盖 U2NET_HOME、ONNX 等专属路径。路径均由根目录解析。

Qt 绑定设置 QT_API=pyside6。模型普通运行设置 HF_HUB_OFFLINE=1；离线加载优先显式 local_files_only=True。环境变量不是所有库都遵守，必须测试是否产生预期目录以外的模型/依赖缓存。操作系统自身创建的 Qt/图形缓存不计入“本项目下载物”，需要记录而非承诺控制所有系统写入。

不要更改 HOME、CODEX_HOME 等系统目录变量来达到重定向目的。

### 5.3 下载流程

1. 普通启动不下载模型；资源管理器列出“未安装/下载中/完整可用/校验失败/不兼容”。
2. 下载前显示来源、精确 revision、大小或大小未知、许可、用途、本地目的地和磁盘空间要求。
3. 使用官方可信来源；模型许可与用途不清楚时不可列为默认自动安装模型。
4. 下载到 .partial；支持取消、重试；支持断点续传时验证服务端版本未变。
5. 下载后记录 SHA-256、大小、revision、许可文件、来源 URL、安装时间和运行后端。
6. 只有校验通过才原子提升为 ready；失败文件不能被模型加载器选中。
7. 禁止默认 trust_remote_code=True；不加载来源不明的可执行 pickle。确需自定义代码时先审核并固定版本，作为本地适配器管理。
8. 不把 HF token 等密钥写入项目包和日志；默认不要求账号。
9. 初次 bootstrap 下载依赖到本地环境并生成 lock；后续 frozen 安装不得静默升级。
10. 提供面向本机平台的离线包生成与安装流程。离线包记录 Python ABI/OS/架构，不能宣称一个 wheel 包跨所有平台通用。

### 5.4 AI 模型选型门槛

当前不指定未经本机验证的 image-to-3D 大模型。provider 必须先通过：许可确认、本机可运行、内存占用可接受、版本固定、输入输出契约明确、样图真实推理成功。

第一版可按顺序增加背景分割和相对深度建议。深度结果只作为可编辑设计初稿，必须人工确定浮雕毫米尺度；不能把相对深度当作真实尺寸测量。没有模型时，手工轮廓和参数曲面路径仍完整可用。

## 6. 数据标准与版本追溯

### 6.1 坐标与单位

- 工件坐标：右手系，X 向右，Y 向上，Z 向观察者/浮雕凸起方向。
- 几何统一 mm，力 N，应力 MPa，时间 s；角度接口明确 deg 或 rad，不用裸 angle。
- 图像坐标原点左上、Y 向下；保存裁剪、旋转、缩放的完整变换链。
- 图像平面映射示例：x=(u-u0)*sx，y=(v0-v)*sy；sx/sy 单位 mm/px，默认保持比例。
- 坐标变换统一 4×4 齐次矩阵，使用列向量；名称如 T_scan_to_part，文档写明方向。
- OBJ/STL 单位不可靠，导入必须确认单位并检查包围盒；导出附 manifest 标记 mm。
- 预览用降采样网格与生产网格分离，不能把 LOD 误导出为精细成品。

### 6.2 核心实体

| 实体 | 必备字段 |
|---|---|
| Project | id、name、schema_version、created_at、updated_at、active_revision_id |
| Artifact | id、kind、relative_path、sha256、size_bytes、unit、coordinate_frame、created_at |
| Revision | id、parent_ids、input_artifact_ids、parameters、algorithm_version、model_revision、seed、outputs |
| AnnotationSet | source_image_id、transform_chain、landmarks、regions、manual/AI 来源 |
| FurCurve | id、region_id、points、surface_revision_id、width_mm、depth_mm、order、seed |
| MaterialProfile | id、batch、state、properties、units、data_source、test_conditions、calibration_status |
| Sample | id、mold_revision_id、material_profile_id、press_run_id、drying_state |
| Inspection | sample_id、target_revision_id、scan_id、alignment、tolerances、coverage、metrics、defects |
| Defect | region、type、evidence_ids、severity、confidence_or_unknown、review_status、action |
| Job | id、kind、state、input_revision_id、progress、result_ids、error、timings |

所有时间存 ISO 8601 UTC，界面按本地时区显示。未知值为 null 并附原因，不能用 0 表示未知。

### 6.3 工程文件布局

```text
workspace/<uuid>/
  project.json                    # 可恢复的基本元数据快照
  project.sqlite                  # 元数据主存储
  originals/                      # 原始图片只读副本
  annotations/
  revisions/<revision-id>/
    parameters.json
    target_surface.obj
    relief_solid.stl
    fur_curves.json
    preview.png
    manifest.json
  molds/<revision-id>/
  samples/<sample-id>/
    photos/
    scans/
    press_run.json
    inspection/
  exports/<export-id>/
```

SQLite 是索引与事务主存储；project.json 是快照，不形成两个可独立修改的真源。文件先写临时位置、校验后提升，再提交数据库；启动时扫描孤立文件和未完成任务，可恢复或清理。启用外键；不跨线程共享同一连接；每个项目同一时间仅一个写实例。

版本为不可变产物：修改参数产生新 revision，不能覆盖已用于打印/质检的版本。上游变更后下游标为 stale，保留历史，不自动替换。

迁移前备份；迁移失败可恢复；较新 schema 不强行读取写回。导出工程包必须使用相对路径，禁止路径穿越，默认不包含模型权重、缓存或密钥。

## 7. 交互策略

### 7.1 主界面

左侧导航：项目 → 照片与标注 → 浮雕设计 → 毛纹与模具 → 检查与试压 → 质检与精修 → 资源与设置。

建模页面：左侧原图/标注，中间三维视口，右侧参数；底部显示任务状态与提示。页面切换不丢失未提交草稿。

### 7.2 操作规则

- 明确区分“预览草稿”“保存新版本”“导出文件”。
- 图像导入后必须可裁剪/旋转/描轮廓，不强制先安装 AI。
- 五官可拖动修改；高度滑块明确 mm；参数同时显示作用区域。
- 调节期间使用低分辨率预览并节流；释放后提交最新计算。过时任务结果不得覆盖最新参数。
- 三维查看提供正/侧/顶视、旋转缩放、重置、线框、无贴图、光照方向、剖切及简单距离测量。
- 提供 undo/redo；参数编辑与标注操作可撤销。保存版本不删除之前的版本。
- 下游无有效输入时按钮不可用，并显示准确缺少项。
- Blender/FreeCAD/模型不可用只影响相关功能，不能阻断整个软件启动。
- 所有耗时任务可见 queued/running/progress/cancel；无法估算百分比时显示阶段，不伪造进度。
- 错误提示写清原因、受影响文件与下一步；保留技术日志供复制，不直接把堆栈当成唯一提示。
- “几何检查通过”不得显示为“可安全压制”；“模拟扫描”始终有明显标记。
- 质检结果分为可接受/需复核/不合格/数据不足。低覆盖不能给通过。
- 删除工程需明确确认或移至项目内回收区；取消任务不损坏原文件。

### 7.3 可访问性与可用性

中文 UI，单位始终可见；键盘支持保存、撤销、恢复视图；色图附数字和图例，不能仅靠红绿判断；暗色/亮色可先实现一种，但文字对比清晰。不同 DPI 和窗口缩放下参数控件可滚动、不截断。

## 8. 功能模块规格与独立验收

本章编号同时用于测试、提交和交付报告追踪。

### F01 项目与资源管理（R1）

输入：项目名、本地目录、照片。输出：可重开的工程与资源索引。

规则：复制原图并计算 hash，重复素材可引用同一产物但保留来源；项目操作不加载 AI 权重。

验收：
- AC-F01-01：创建、保存、关闭、重开，字段与版本关系一致。
- AC-F01-02：中文空格路径可用；外部原图删除后项目仍完整。
- AC-F01-03：保存途中模拟失败，旧版本可读且未损坏。
- AC-F01-04：导出工程包并换目录导入，引用不含旧绝对路径。

### F02 图像与标注（R1）

输入 JPEG/PNG，正确处理 EXIF 方向、透明度与超大图。支持手动轮廓、五官点、区域、毛流引导线；AI 输出是可覆盖建议。

验收：
- AC-F02-01：裁剪旋转后标注通过变换链正确对应原图；往返误差 ≤0.5 原图像素（合成测试）。
- AC-F02-02：移动点、撤销、重做、重开后结果一致。
- AC-F02-03：断网且无权重时，手动流程全部可用。
- AC-F02-04：损坏图片给出明确错误，超限图片先提示并生成工作副本，不覆盖原图。

### F03 基础浅浮雕生成（R1）

输入：轮廓、五官区域、成品宽度、深度参数。输出：连续高度场、目标表面网格、带底封闭打印实体。

基线算法：由人工/AI 标注构造区域平滑基函数或可编辑高度场；鼻子、脸颊、额头、眼眶分别控制；边界向背景平滑过渡；深度估计是可选混合输入，不从 RGB 亮度直接复制 Z。支持重叠区域规则并保存完整参数。

验收：
- AC-F03-01：一张照片仅经人工标注即可生成基础浮雕，不依赖网络。
- AC-F03-02：改变鼻部高度只影响预定义影响区及平滑带，不无故移动眼睛。
- AC-F03-03：测试输出宽度与设定值误差 ≤0.01 mm；数值检查无 NaN/Inf。
- AC-F03-04：导出的基础实体封闭、法向一致、体积为正；发现自交时不能静默通过。
- AC-F03-05：有正面、侧面、无贴图预览；同参数和 seed 产生可复现几何（跨平台按公差比较）。

### F04 三维查看与 Blender 往返（R1）

现有 Blender 通过配置路径或有限候选路径检测；调用 --version 校验。用参数数组启动进程，不用 shell 拼接。首次集成先做离线往返小样，不注入未审核的外部脚本。

接口文件包含 project_id、input_revision、单位、坐标变换与源 hash。编辑另存 .blend 并经本项目脚本导出网格；用户在应用中“导入编辑结果”创建版本。文件监视只通知，不自动覆盖。

验收：
- AC-F04-01：基础预览不依赖 Blender；找到现有程序后能打开指定副本。
- AC-F04-02：包含已知尺寸标记的测试件往返尺寸误差 ≤0.01 mm，方向不翻转。
- AC-F04-03：Blender 编辑产生新版本，旧版仍可打开。
- AC-F04-04：未编辑往返可保留关联；拓扑或坐标显著变化时毛纹绑定标 stale，不能按旧顶点序号错误绑定。
- AC-F04-05：Blender 路径错误、启动失败、导出缺失分别可诊断，不自动安装软件。

### F05 毛流、毛纹与测试块（R1）

先保存毛流曲线，再将曲线转换为实际几何。曲线具有 region_id、curve_id、顺序和尺寸；不把毛发烘焙成唯一不可编辑 STL。禁入区域如眼球/鼻头由用户设置。

基线：用户在局部画引导线，程序按 seed 生成受约束的毛束；允许删改局部，不承诺全自动语义毛发。

测试块提供宽度、间距、深浅组合和编号。默认示例可以为线宽 0.2/0.3/0.5/0.8 mm、深浅 0.1/0.2/0.3 mm，但标注“试验设计值，非皮革工艺推荐”。区分线中心距与净间距。

验收：
- AC-F05-01：修改密度/方向后仍在区域内，不越过禁入边界。
- AC-F05-02：纹理导出为真实凹凸，重新导入 STL 的剖面可以测得对应深度。
- AC-F05-03：同 seed/参数重建曲线一致；编号与参数 CSV/JSON 一一对应。
- AC-F05-04：过细、交叉密集或可能破坏最小皮层参数的纹理给出可定位警告，不自动删改。

### F06 模具候选与打印导出（R1）

限定 2.5D 无倒扣浅浮雕。分别保存目标外表面、上模、下模。R1 可以采用明确标注的 Z 向间隙近似，不得称为精确法向等厚模具；用坡度阈值警告并阻止不支持的陡面导出为已通过候选。阈值是几何算法适用范围，不是材料成形极限。

上模表面按目标纹理反形生成；下模负责支撑大形体。用户输入间隙、底座、定位和限位参数；这些值不能由未校准 AI 自动决定。导出候选附待评审清单。

验收：
- AC-F06-01：平面/缓坡解析测试中，指定轴向间隙正确，误差 ≤0.02 mm。
- AC-F06-02：在剖面中验证皮面凹纹对应上模凸纹，方向不会反转。
- AC-F06-03：上下模各自闭合，定位结构装配无意外穿透；自交/倒扣/不支持坡面有报告。
- AC-F06-04：导出 STL+OBJ+manifest+参数表；manifest 含单位、版本、hash、近似方法、未验证事项。
- AC-F06-05：用独立重新导入检查包围盒与实体有效性；不能仅断言文件存在。

### F07 材料与设计检查（R1）；物理仿真接口（R3）

R1 必须：材料数据表、参数来源、几何薄弱位置检查、间隙/尖角/尺寸规则；可显示 F/A 的名义平均压力换算，但标注不是实际接触压力。

R1 不要求 FEM。SimulationProvider 返回 available=false/reason 时，UI 显示“未接入求解器”。缺弹性模量、边界条件等时禁用求解，不补造参数。

R3 输入：网格、材料本构、支撑/载荷/接触、求解设置。输出：位移、应力/应变、收敛信息、假设、材料适用范围、校准状态。真实模具承载需要适当强度判据，不能统一用单一应力值给所有树脂安全结论。

验收：
- AC-F07-01：实测/厂家/假设数据明显区分，未知与零不同。
- AC-F07-02：修改单位能正确转换，非法负厚度/负模量被拒绝。
- AC-F07-03：缺求解器不阻断建模；不产生伪应力图。
- AC-F07-04：规则检查标明使用的阈值和来源，不等同“压制安全认证”。
- R3 额外门槛：解析算例、网格收敛、实物校准及误差报告通过后才标“已校准”；动画仅标可视化。

### F08 试压与生产记录（R1）

记录：模具版本、材料批次与皮厚、润湿方法、载荷或液压表读数及换算关系、闭合间隙、保压、干燥条件、脱模时间、照片、人工补纹耗时、上色/装配成本。

验收：
- AC-F08-01：每个样品可追溯到特定模具和材料版本。
- AC-F08-02：液压表读数不被直接当作皮面接触压力；缺转换资料显示未知。
- AC-F08-03：可比较至少三组样品及其参数差异。
- AC-F08-04：任务单导出 Markdown/HTML 和图片；照片与报告一致，缺失成本不按零汇总为完整成本。

### F09 扫描导入与三维质检（R2）

输入 PLY/STL/OBJ 扫描文件，明确单位、采集状态、设备说明；本期不需要相机/扫描仪 SDK。

先手选对应基准点或导入已知变换，再做可选刚性 ICP。质检配准禁止自动尺度拟合与非刚性变形；确需单位修正作为独立操作并记录。仅凭全局最佳拟合可能掩盖关键区偏差，默认优先稳定基准并按区域报告。

计算扫描点到目标表面的距离，并额外检查目标到扫描的覆盖情况，避免缺扫区域消失在统计中。统一闭合且法向可靠的表面才使用 signed distance；其他情况输出 unsigned 并注明限制。报告中“偏高/偏低”需有明确方向定义与算法依据。

验收：
- AC-F09-01：合成基准模型施加已知刚性变换后可对齐；无噪声测试 RMS ≤0.05 mm。
- AC-F09-02：构造局部 0.5 mm 偏移且采样足够的测试区，测得偏差误差 ≤0.05 mm；不将该数值宣称为真实扫描仪精度。
- AC-F09-03：缺失区域显示“未测到”；覆盖低于可配置阈值时不能判通过。
- AC-F09-04：保存配准矩阵、目标版本、容差、采样/滤波参数；同输入可复核。
- AC-F09-05：真实皮面与对应 target_surface 比较，不与下凸模直接比较。

### F10 照片质检与精修任务（R2）

基线功能：照片标准视角与状态记录，多方向侧光图并排，手工框选缺纹/断纹/压糊/褶皱/破损，关联三维区域。可做图像处理建议，但未标定的单张照片不输出毫米深度。

AI 报告是可选增强，先用确定性模板组织测量与人工标注即可；显示报告来源。报告引用证据、位置、需要补采的数据。模型的自述置信度不是经过校准的统计概率。

验收：
- AC-F10-01：点击问题列表可定位照片或三维区域。
- AC-F10-02：输出“可补纹/需改模或工艺/需复查”，允许人工修改并留记录。
- AC-F10-03：缺证据不输出确定原因或压力数值；无 AI 时模板报告可导出。
- AC-F10-04：自动识别若接入，必须在独立标注样本上报告误检、漏检、数据量与限制，不用训练样本证明有效。

### F11 补加工路径预览（R2 后段）

输入确认的缺陷区域、原毛发曲线、实际表面和工具几何。输出设备无关 path.json 和三维预览。

每个路径段包含 points_mm、orientation/normal（若可用）、operation、curve_id、tool_id、建议速度/目标力字段（未知为 null）。本期不补造工艺参数、不输出可直接执行的机器人程序。

先支持竖直工具与无倒扣浅曲面，按实际表面投影；超坡度、缺扫区域、工具不可达区拒绝生成。工具接触点与工具中心须区分，预览考虑工具尺寸和抬刀段。当前不实现机器人逆运动学时，明确“未校验机械臂可达性”。

验收：
- AC-F11-01：只选取指定缺陷范围相关曲线，原曲线和源版本不变。
- AC-F11-02：解析平面/缓坡测试中接触点位置符合工具几何，误差 ≤0.05 mm。
- AC-F11-03：缺测或不支持区域标红并阻止导出为可加工路径。
- AC-F11-04：JSON 显示 preview_only=true；程序不包含连接设备或发送运动命令的行为。

## 9. 端口与数据契约

使用 typing.Protocol 或 ABC 定义，返回数据类/结构化结果，不返回 Qt Widget。以下为最低接口语义，具体签名须在代码中固定并测试：

```python
class ReliefBuilder(Protocol):
    def build(self, request: ReliefRequest, context: JobContext) -> ReliefResult: ...

class ModelProvider(Protocol):
    def capabilities(self) -> CapabilitySet: ...
    def infer(self, request: InferenceRequest, context: JobContext) -> InferenceResult: ...

class ExternalEditor(Protocol):
    def probe(self, executable: Path) -> ToolCapability: ...
    def export_session(self, request: EditorRequest) -> EditorSession: ...
    def import_result(self, session: EditorSession) -> EditedArtifact: ...

class SimulationProvider(Protocol):
    def capabilities(self) -> CapabilitySet: ...
    def validate(self, request: SimulationRequest) -> ValidationReport: ...
    def solve(self, request: SimulationRequest, context: JobContext) -> SimulationResult: ...

class InspectionEngine(Protocol):
    def compare(self, request: InspectionRequest, context: JobContext) -> InspectionResult: ...

class ToolpathPlanner(Protocol):
    def preview(self, request: ToolpathRequest, context: JobContext) -> ToolpathResult: ...
```

JobContext 提供取消查询、阶段进度与 job_id，不依赖 Qt。CapabilitySet 必须含 available、supported_features、version、reason。未实现端口明确报 FeatureUnavailable，不返回空成功结果。

大型数组可通过 .npy/.npz 文件传递；跨进程传文件路径与 hash，不频繁序列化百万三角形对象。数组明确 dtype、shape、单位；外部 JSON 必须有 schema_version。

## 10. 任务调度、线程与恢复

- Qt 事件循环和 VTK 渲染只在主线程。
- 耗时 I/O 使用 worker + signal/slot；CPU 密集网格与推理优先工作进程，不能靠 QThread 绕过 GIL 的问题。
- Blender 使用独立 subprocess；传 argv，shell=False，明确 cwd、env、timeout，捕获 stdout/stderr。
- 任务状态：queued → running → succeeded/failed/cancelled；支持 cancelling 和崩溃后的 interrupted。
- 默认同时一个重几何/AI 任务，下载可单独一项；可配置但防止内存耗尽。
- 每次任务绑定不可变输入版本。过时任务可以保存为历史结果，但不能激活覆盖当前状态。
- 可取消算法在阶段边界检查；无法中断的第三方调用通过独立进程终止，清理本任务临时目录，不能误杀用户手开的 Blender。
- 工作进程不直接改项目数据库；主应用接收已验证结果后事务提交。
- 关闭应用遇到任务时提供等待/取消退出；禁止 GUI 阻塞式 join 长时间假死。
- UI 操作反馈目标 ≤200 ms；任务取消请求目标 ≤1 s 内得到状态反馈，不等同底层计算必在 1 s 内退出。

## 11. Python 代码与接口规范

### 11.1 基础风格

- 遵守 PEP 8、PEP 257、类型标注规范；统一 UTF-8，四空格，不使用 Tab。
- 文件/变量/函数 snake_case，类 PascalCase，常量 UPPER_SNAKE_CASE。
- 英文标识符，中文用户文本；领域术语建立 docs/glossary.md，统一使用 mold、relief、inspection、toolpath 等。
- 行宽 100，Ruff format 为唯一格式真源；不同时引入另一套冲突格式器。
- 公共函数、端口、DTO 必须类型标注；domain/application mypy strict。
- 科学库边界缺类型时在最小 adapter 范围抑制，注明原因；禁止全仓忽略类型错误。
- 公开 docstring 包含单位、坐标、前置条件、返回内容和可能错误。复杂算法解释为什么，不逐行翻译代码。

### 11.2 模块职责与体积

- 单个业务模块目标 ≤400 行、函数目标 ≤60 行；超过不是机械拆碎，而是需解释职责并评审。
- 自动生成资源和数据表可例外，不允许借例外塞入业务逻辑。
- 禁止大型 MainWindow 同时处理数据库、AI、建模与导出。
- 不滥用继承；优先组合与显式依赖注入。
- 禁止裸 except、静默吞异常、用 print 替代运行日志、在 import 时运行下载/推理/打开窗口。
- 数值常量有名字与单位；验证 NaN/Inf、数组维度、最小分辨率与输入范围。
- dataclass/Pydantic 模型不使用可变默认参数；不以任意 dict 串联整个业务。
- 本地文件操作用 pathlib；命令参数列表传递；不使用 os.system。

### 11.3 错误与日志

定义可识别错误码，例如 INVALID_IMAGE、UNIT_UNCONFIRMED、INVALID_MESH、RESOURCE_MISSING、TOOL_UNAVAILABLE、JOB_CANCELLED、SCAN_COVERAGE_LOW。

用户错误与程序缺陷分开处理。日志包含 UTC 时间、level、job_id、project_id、component、error_code；不默认记录照片内容、token 和完整隐私数据。日志轮转，用户可导出诊断包并预览包含内容。

### 11.4 配置与依赖

- 默认值在 configs/defaults.toml，用户覆盖在本地 runtime/config.toml；参数快照写入每个 revision。
- 环境变量用于运行路径/离线模式，不承包全部业务参数。
- 依赖先论证再加入，禁止为一个小功能引入第二套重型 3D 框架。
- pyproject.toml 定义入口和 optional groups；AI/求解器不加入强制启动导入链。
- 不在导入失败时自动 pip install。
- uv.lock 必须提交；不同环境用 doctor 报告依赖版本。

### 11.5 最低工具配置方向

Ruff 启用 E/F/I/B/UP 等基础规则，按选定版本固定配置；mypy 对 core 严格。测试/格式命令统一在 README，禁止交付者各用一套临时命令。

```text
python scripts/doctor.py
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
uv run --frozen pytest tests/unit tests/integration tests/architecture
uv run --frozen pytest tests/gui
```

这些命令应由启动/开发脚本注入第 5 章的本地路径，README 中提供完整可复制运行方式，不要求用户记忆环境变量。

## 12. 性能、稳定性与测试标准

### 12.1 可验证性能预算

在 doctor 记录的参考机器上测试，而不是无条件承诺所有电脑同样速度：
- 普通启动不加载 AI，目标 ≤5 s。
- 20 万三角形预览在参考机器上目标 ≥20 FPS；达不到则记录数据并优化 LOD，不能降低导出精度掩盖问题。
- 512×512 高度场的基础生成目标 ≤10 s；大任务不阻塞 UI。
- 预览分辨率 256/512 可选；高精度导出另行配置，估算内存并设置预算。
- 不预先宣称百万面精细网格可实时布尔运算；高开销步骤后台执行。

性能未达标时必须提供实测及限制，不能只凭主观“很流畅”验收。

### 12.2 测试分层

- 单元：坐标变换、单位、版本依赖、参数合法性、几何不变量。
- 集成：文件往返、SQLite 原子提交、下载校验、Blender 桥接、真实扫描比较算法。
- GUI：核心点击流程、撤销、状态禁用、任务取消、重开恢复。
- 架构：依赖方向、禁止 UI 导入求解器、禁止 domain 导入 Qt。
- 端到端：断网、无模型、无 FreeCAD，完成 R1 基线。

覆盖率目标：domain/application 行覆盖率 ≥80%，几何算法不能只靠覆盖率，还必须测试解析形体、随机有效输入和失败边界。不要为凑覆盖率写只复制实现逻辑的断言。

### 12.3 固定测试数据

合成平面、坡面、椭球浅浮雕、带已知宽深纹理的测试块、已知刚性变换扫描、局部 0.5 mm 偏移、缺失扫描区、反法向网格、损坏文件、中文路径样例。

照片测试使用用户许可图片或自制示例。真实相似度与物理可制造性不能由合成测试替代。仿真、模拟扫描、真实扫描分别标记来源。

## 13. 质检闭环与变更规则

1. 先冻结目标皮面与模具版本。
2. 样品关联实际压制参数、材料状态与模具使用次数。
3. 原始照片/扫描只读保存，滤波与配准作为派生产物。
4. 分别报告形体偏差、纹理缺陷、扫描覆盖与数据质量。
5. 人工确认修复路径：当前件补纹、重做样品、修改模具、修改工艺或补采数据。
6. 当前件精修不能自动修改设计主模型；改模必须新建版本。
7. 比较至少重复样品，避免从一次缺陷推断稳定工艺结论。
8. 后续校准模型使用训练/校准样本与独立验证样本分离，保留误差、适用材料批次与条件。

## 14. 文件与外包交付标准

打样包包括 README.md、目标预览、目标外表面、上下模 STL、尺寸与单位、参数 JSON、源版本、校验和、材料/间隙待确认项。可以附 OBJ；不把 OBJ 作为唯一本体数据。

精修包包括原图、问题标记图、区域编号、测量依据、人工确认状态与建议，区分“补纹”与“形体问题”。

上色包包括原照片、色区参考和认可样板，AI 色卡未经实物核对不能当成精确涂料配方。

代码交付包括 README、架构图或依赖说明、接口文档、环境锁、离线安装说明、各里程碑演示步骤、真实测试日志摘要和已知限制。

## 15. 实施顺序与里程碑门槛

### M0 环境与骨架

交付：本地目录管理、doctor、锁定依赖、Qt+VTK 真机冒烟、架构空骨架、最小日志。

通过条件：从不同 cwd 启动成功；普通启动不联网；未安装 FreeCAD 不报致命错误；本地环境可重复安装。记录 Blender 检测结果，不未经验证宣称已集成。

### M1 第一个垂直闭环

交付：F01/F02/F03 基线与三维预览。

通过条件：导入照片 → 手画轮廓/五官 → 调整鼻高 → 查看侧面 → 导出封闭 STL → 重开项目。无 AI 也全程可用。对应 AC 全通过。

### M2 打样设计

交付：F04/F05/F06，优先测试块，再细毛纹与头像模具。

通过条件：Blender 往返测试通过或明确环境问题；编号测试块和候选模具可重新导入验收；细节为真实几何。导出包含近似假设与待评审项。

### M3 R1 完整版

交付：F07 的材料/规则部分、F08、资源管理、恢复与工程迁移。

通过条件：无 FreeCAD、无 FEM 仍可全部运行；下载权重本地化与校验路径通过测试；提供 R1 演示项目。可选 AI 未通过本机验证时标未启用，不拖累基础验收。

### M4 质检闭环

交付：F09/F10。

通过条件：模拟扫描验证已知变形与缺扫；真实文件可导入，报告数值可复核；未经真实样本验证不得称自动质检生产可用。

### M5 补纹路径预览

交付：F11 与预览测试，不连接机器。

通过条件：指定曲线在实测表面有效覆盖区投影，工具几何/抬刀段可见；不支持部分明确拒绝；无实际设备发送能力。

### M6 后续可选工程

另立 ADR 与验收合同再做 FreeCAD/FEM、真实皮革本构标定、图像自动判缺、相机 SDK、机器人或数控后处理。不能因为“预留接口”就一次安装所有依赖。

## 16. GLM 实施交付纪律

每次开始一个里程碑时，先给出修改文件范围、受影响端口和验收编号。每次结束提交如下记录到 docs/reports/：

```text
里程碑：
实现功能及 AC 编号：
实际运行命令：
测试结果：
手工演示步骤：
新增依赖/模型及本地路径：
真实能力与模拟能力：
未通过项、原因和后续处理：
```

- 不以“后续完善”为由省略本里程碑核心闭环。
- 未实现功能隐藏或禁用并说明，不提供返回固定成功的按钮。
- 不修改已有用户文件来凑测试，不覆盖原图或旧模型。
- 不无故替换已通过里程碑的技术栈；变更须记录迁移影响。
- 不一次性生成上千行混杂 UI/算法主程序。
- 与本规范冲突时在 ADR 中提出具体差异，不能静默改变约束。
- 优先提交可以验证的小步结果，先真实跑通再优化自动化和美观。

## 17. 首个可用版本的总体验收清单

- [ ] 本地环境、依赖和下载物目录明确，无全局 Python 安装。
- [ ] 无网络、无 AI 权重、无 FreeCAD 可正常启动。
- [ ] 用户照片、标注、尺寸和模型版本可保存重开。
- [ ] 照片到浮雕全过程可查看和修改。
- [ ] 模型包含真实几何，导出尺寸正确且实体有效。
- [ ] 测试块编号、曲线、纹理参数可追溯。
- [ ] 上下模候选可以装配查看，适用范围和近似清楚。
- [ ] Blender 使用已有安装，失败可降级，不修改用户原文件。
- [ ] 材料参数与几何规则检查可用，无虚构 FEM 结果。
- [ ] 试压记录和外包交付包可生成。
- [ ] 后台计算不冻结窗口，过期结果不覆盖新状态。
- [ ] 任务失败、取消、磁盘错误不会损坏已保存工程。
- [ ] Ruff、类型检查、核心测试和真机 GUI 验证有实际结果。
- [ ] README 提供从安装到第一次导出的可复制步骤。

## 18. 技术依据与查阅入口

以下为实现参考，不替代本项目对版本、实际硬件和材料的验证：

- Qt for Python 线程与信号示例：https://doc.qt.io/qtforpython-6/examples/example_widgets_thread_signals.html
- PyVistaQt 嵌入 QtInteractor 与 PySide6 绑定：https://qt.pyvista.org/usage.html
- uv 环境变量与本地存储：https://docs.astral.sh/uv/reference/environment/
- uv 缓存：https://docs.astral.sh/uv/concepts/cache/
- Hugging Face 本地路径与离线变量：https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables
- Blender 雕刻文档：https://docs.blender.org/manual/en/latest/sculpt_paint/sculpting/index.html
- FreeCAD 功能与 Python 扩展：https://www.freecad.org/features.php
- FreeCAD CAM 范围：https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/CAM_Workbench.md
- CloudCompare 刚性配准参考：https://cloudcompare.org/doc/wiki/index.php/ICP
- CloudCompare 点云到网格距离：https://cloudcompare.org/doc/wiki/index.php/Cloud-to-Mesh_Distance
- 树脂打印细节与尺寸设计指南：https://formlabs.com/support/Design-specifications-for-3D-models-Form-4-generation/
- 皮革各向异性有限元研究：https://www.jstage.jst.go.jp/article/mej/7/4/7_20-00072/_article
- 含水量与皮革刚度研究：https://pubmed.ncbi.nlm.nih.gov/30340070/

---

实施起点：先完成 M0 与 M1，获得一个真实可运行、可保存、可修改、可导出的小闭环；随后严格按里程碑增加能力。
