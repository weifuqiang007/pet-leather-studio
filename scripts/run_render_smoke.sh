#!/bin/bash
# 渲染冒烟测试编排（PRD 3.2）：
#   1 次长跑（默认 300 秒持续交互）+ 10 次完整启停（每次 15 秒）。
# 汇总退出码，并检查测试窗口内 macOS 是否产生新的崩溃报告。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/runtime/smoke"
mkdir -p "$OUT"

if [[ ! -x "$PY" ]]; then
  echo "未找到 $PY，请先完成 scripts/bootstrap.py" >&2
  exit 1
fi

export QT_API="pyside6"
export XDG_CACHE_HOME="$ROOT/.cache"

# 崩溃报告观察窗：记录启动时刻，结束后仅检查其后新生成的报告
MARK="$OUT/marker.touch"
touch "$MARK"
CRASH_DIR="$HOME/Library/Logs/DiagnosticReports"

run_one() {
  local tag="$1" duration="$2"
  "$PY" "$ROOT/scripts/render_smoke.py" --duration "$duration" --tag "$tag" \
    > "$OUT/$tag.out" 2>&1
  local rc=$?
  echo "$rc" > "$OUT/$tag.exit"
  echo "[$tag] 退出码 $rc"
}

echo "== 长跑：300 秒持续交互 =="
run_one long 300

echo "== 完整启停 ×10 =="
for i in $(seq 1 10); do
  run_one "quick$i" 15
done

echo "== 崩溃报告检查（测试期间新增） =="
NEW_CRASHES=$(find "$CRASH_DIR" -name "*.ips" -newer "$MARK" 2>/dev/null | grep -i -E "python|smoke" || true)
if [[ -n "$NEW_CRASHES" ]]; then
  echo "发现新增崩溃报告："; echo "$NEW_CRASHES"
else
  echo "无新增 python 崩溃报告"
fi

echo "== 退出码汇总 =="
FAILED=0
for f in "$OUT"/*.exit; do
  rc=$(cat "$f")
  [[ "$rc" != "0" ]] && FAILED=1 && echo "失败: $(basename "$f" .exit) rc=$rc"
done
if [[ "$FAILED" == "0" ]]; then
  echo "全部通过（long + quick1..10 共 11 次退出码 0，日志含 SMOKE_CLEAN_EXIT）"
fi
exit "$FAILED"
