# Pet Leather Studio · 0.1.0

目标：照片 → 精细浮雕母版 → 阴阳模 → 皮革试压。

当前实现为本地 PySide6 工作台：导入已有 OBJ/STL/PLY 母版、无贴图三维查看、生成配套阴阳模候选、保留和切换数据版本。**照片自动重建尚未实现；候选模具尚未经过实物验证。**

实施入口见 [GLM 阅读顺序](docs/00-GLM-START-HERE.md)，范围和参数见 [收敛实施路径](docs/IMPLEMENTATION-REFOCUS-v0.1.md)，验证记录见 [v0.1 报告](docs/reports/mold-workbench-v0.1.md)。旧区域凸起实验保留追溯，不作为目标效果。

## 启动

```bash
# 首次安装；下载保存在仓库本地目录
python3 scripts/bootstrap.py

# 打开桌面工作台；工程目录不存在时自动建立
scripts/dev.sh run --frozen python -m pet_leather_studio --project workspace/my_project

# 查看本次真实参考模型与候选（限已有此本地工程的电脑）
scripts/dev.sh run --frozen python -m pet_leather_studio --project workspace/refocus_reference
```

导入浮雕主体，确认正面朝 +Z，设置宽度/深度/间隙/底板/采样和最小特征后生成。阴模单独预览默认从接触面查看。历史选择仅预览，点击激活旧版本才切换工作基线。低采样提示必须认真检查。

## 命令行

```bash
scripts/dev.sh run --frozen python -m pet_leather_studio --project workspace/my_project import-master /absolute/path/master.obj
scripts/dev.sh run --frozen python -m pet_leather_studio --project workspace/my_project generate --width 60 --depth 2 --gap 1 --backing 3 --grid 128 --feature 0.2 --accept-top-projection
scripts/dev.sh run --frozen python -m pet_leather_studio --project workspace/my_project history
scripts/dev.sh run --frozen python -m pet_leather_studio --project workspace/my_project activate REVISION_ID
```

生成目录 `workspace/<project>/revisions/<id>/` 包括两份 STL、高度数据与参数/hash 清单。数据不随 Git 提交，需另行备份。

## 检查与本地依赖

```bash
scripts/dev.sh run --frozen ruff check .
scripts/dev.sh run --frozen ruff format --check .
scripts/dev.sh run --frozen mypy src/pet_leather_studio/domain src/pet_leather_studio/application
scripts/dev.sh run --frozen pytest tests/unit tests/architecture tests/integration
# 需要图形会话
scripts/dev.sh run --frozen pytest tests/gui
```

Python 运行时、依赖和缓存留在 `.tools/`、`.venv/`、`.cache/`。本次未新增第三方依赖或下载 AI 权重；不需要 FreeCAD。已有 Blender 可用于人工调整母版朝向。

旧代码标签 `baseline-before-mold-refocus-20260920`，新版标签 `mold-workbench-v0.1.0`；回退方式见实施路径第 5 节。
