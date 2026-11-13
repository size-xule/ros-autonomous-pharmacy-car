#!/usr/bin/env bash
# verify.sh —— 校验 lib/pharmacy_pkg 下 9 个二进制的 SHA-256
#
# 用法：
#   bash verify.sh                      # 校验本目录副本
#   bash verify.sh --remote keyuan22@10.211.121.22   # 同时校验车上那份（需 sshpass 或免密）
#   bash verify.sh --quiet              # 只输出结论
#
# 退出码：0 全部一致；1 有不一致或缺失
set -uo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1

QUIET=0
REMOTE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --quiet) QUIET=1 ;;
    --remote) REMOTE="${2:-}"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
  esac
  shift
done
say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }

[ -f SHA256SUMS ] || { echo "缺少 SHA256SUMS"; exit 1; }

FAIL=0
say "== 1) 本目录副本 =="
if sha256sum -c SHA256SUMS --quiet 2>/dev/null; then
  say "   ✅ 9 个文件哈希全部匹配"
else
  echo "   ❌ 有不一致："
  sha256sum -c SHA256SUMS 2>&1 | grep -v ': OK$' | sed 's/^/      /'
  FAIL=1
fi

# 缺失文件检查（sha256sum -c 对缺失会报 FAILED open，但再明确列一遍）
missing=0
while read -r _ name; do
  [ -f "$name" ] || { echo "   ❌ 缺失：$name"; missing=$((missing+1)); }
done < SHA256SUMS
[ "$missing" -eq 0 ] && say "   ✅ 9 个文件都在" || FAIL=1

# 未登记的额外 ELF（提示，不判失败）
# 注意：在 Windows 的 DrvFs 上所有文件都带执行位，不能用 -perm 判断，改看 ELF 魔数
is_elf() { [ "$(head -c 4 "$1" 2>/dev/null | od -An -tx1 | tr -d ' \n')" = "7f454c46" ]; }
extra=""
for f in $(find . -maxdepth 1 -type f -printf '%f\n' | sort); do
  case "$f" in *.md|*.sh|SHA256SUMS) continue ;; esac
  is_elf "$f" || continue
  grep -q "  $f\$" SHA256SUMS || extra="$extra $f"
done
if [ -n "$extra" ]; then
  say "   ⚠️ 有未登记的 ELF（新增二进制应补进 SHA256SUMS）："
  for f in $extra; do say "      $f"; done
fi

# ---------------------------------------------------------------- 远端对比
if [ -n "$REMOTE" ]; then
  say ""
  say "== 2) 与车上对比：$REMOTE =="
  D=/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg
  if command -v sshpass >/dev/null 2>&1 && [ -n "${ROBOT_PASS:-}" ]; then
    SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"
    export SSHPASS="$ROBOT_PASS"
  else
    SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"
  fi
  if remote_out=$($SSH "$REMOTE" "cd $D && sha256sum -c -" < SHA256SUMS 2>&1); then
    say "   ✅ 车上 9 个文件与本仓库完全一致"
  else
    echo "   ❌ 车上与本仓库不一致："
    printf '%s\n' "$remote_out" | grep -v ': OK$' | sed 's/^/      /'
    FAIL=1
  fi
fi

say ""
if [ "$FAIL" -eq 0 ]; then
  echo "=== 结论：PASS（二进制与 SHA256SUMS 一致）==="
  exit 0
else
  echo "=== 结论：FAIL（见上）==="
  exit 1
fi
