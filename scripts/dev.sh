#!/bin/bash
# 开发命令包装器：注入 PRD 第 5 章的本地路径环境变量后调用项目本地 uv。
# 用法示例：
#   scripts/dev.sh sync
#   scripts/dev.sh run --frozen ruff check .
#   scripts/dev.sh run --frozen pytest tests/unit tests/architecture
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/runtime/tmp"

export QT_API="pyside6"
export UV_CACHE_DIR="$ROOT/.cache/uv"
export UV_PROJECT_ENVIRONMENT="$ROOT/.venv"
export UV_PYTHON_INSTALL_DIR="$ROOT/.tools/python"
export PIP_CACHE_DIR="$ROOT/.cache/pip"
export TMPDIR="$ROOT/runtime/tmp"

if [[ -x "$ROOT/.tools/uv/uv" ]]; then
  UV="$ROOT/.tools/uv/uv"
elif command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
else
  echo "未找到 uv：请先运行 scripts/bootstrap.py 或将 uv 放入 .tools/uv/" >&2
  exit 1
fi

exec "$UV" "$@"
