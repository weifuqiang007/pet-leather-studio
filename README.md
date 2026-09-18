# pet-leather-studio

宠物皮革浮雕工作台：照片 → 浅浮雕设计 → 3D 打印模具候选 → 皮革压制的本地桌面工具。

规范见 [docs/PRD.md](docs/PRD.md)（v1.1）；实施入口见
[docs/00-GLM-START-HERE.md](docs/00-GLM-START-HERE.md)；里程碑记录见
[docs/reports/](docs/reports/)。

## 环境要求

- macOS（当前验证机器：Apple M1 / 16 GB / macOS 14.2）
- 可选：已有 Blender（用于 F04 往返；缺失不阻塞）

所有依赖、Python 运行时与缓存都安装在**本仓库本地目录**（PRD 5.2）：
`.venv/`、`.tools/`、`.cache/`，不写入全局 Python 或用户全局缓存。

## 快速开始

```bash
# 1. 引导本地环境（首次需联网：下载 Python 3.11 与依赖到项目本地目录）
python3 scripts/bootstrap.py

# 2. 系统体检（写入 runtime/system_profile.json）
scripts/dev.sh run --frozen python scripts/doctor.py

# 3. 质量检查与测试
scripts/dev.sh run --frozen ruff check .
scripts/dev.sh run --frozen ruff format --check .
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
scripts/dev.sh run --frozen pytest tests/unit tests/architecture

# 4. M0.5 算法自测（合成样本）
scripts/dev.sh run --frozen python experiments/relief_spike/relief_spike.py selftest

# 5. 真机渲染冒烟（会打开窗口约 6 分钟）
scripts/run_render_smoke.sh
```

日常命令统一经 `scripts/dev.sh`（注入本地路径环境变量后调用项目本地 uv）。

## 当前状态

- M0：环境/骨架/CI/冒烟——见 [docs/reports/](docs/reports/)
- M0.5：算法可行性短验证——管线自测 + 相似度评审（pending，待用户提供照片）
- M1+：未开始
