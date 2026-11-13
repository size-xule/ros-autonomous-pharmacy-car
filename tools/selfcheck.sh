#!/usr/bin/env bash
# tools/selfcheck.sh —— 仓库自检（在 WSL / Linux 上跑，不要在 Windows PowerShell 里跑）
#
# 用法：
#   bash tools/selfcheck.sh            # 全部检查
#   bash tools/selfcheck.sh --links    # 只查文档相对链接（任务组 1.2 验收用）
#   bash tools/selfcheck.sh --quiet    # 只打印失败项与总结
#
# 设计原则：
#   * 只读，不改任何文件
#   * 缺依赖（systemd-analyze 等）降级为 WARN，不判失败
#   * 退出码：0 = 全通过（允许 WARN）；1 = 有 FAIL
set -uo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || { echo "无法进入仓库根目录"; exit 1; }

ONLY=""; QUIET=0
for a in "$@"; do
  case "$a" in
    --links) ONLY=links ;;
    --quiet) QUIET=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  esac
done

FAIL=0; WARN=0; PASS=0
c_ok()   { PASS=$((PASS+1)); [ "$QUIET" -eq 1 ] || printf '  \033[32mPASS\033[0m %s\n' "$*"; }
c_warn() { WARN=$((WARN+1)); printf '  \033[33mWARN\033[0m %s\n' "$*"; }
c_fail() { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
sec()    { [ "$QUIET" -eq 1 ] || printf '\n\033[36m== %s ==\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. 文档相对链接
check_links() {
  sec "1/6 文档相对链接"
  local bad=0 total=0 f dir target
  while IFS= read -r f; do
    dir="$(dirname "$f")"
    # 抓 ](xxx) 里的 xxx，去掉 #anchor 和 <尖括号>
    while IFS= read -r target; do
      [ -z "$target" ] && continue
      case "$target" in
        http*|mailto:*|\#*) continue ;;
      esac
      target="${target%%#*}"
      [ -z "$target" ] && continue
      total=$((total+1))
      if [ ! -e "$dir/$target" ]; then
        c_fail "$f → 链接失效：$target"
        bad=$((bad+1))
      fi
    done < <(grep -oE '\]\([^)]+\)' "$f" 2>/dev/null | sed -e 's/^](//' -e 's/)$//' -e 's/^<//' -e 's/>$//')
  done < <(git ls-files '*.md')
  [ "$bad" -eq 0 ] && c_ok "检查 $total 个相对链接，全部可达"
}

# ---------------------------------------------------------------- 2. 二进制 SHA256
check_sha() {
  sec "2/6 二进制完整性（lib/pharmacy_pkg）"
  local d="cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg"
  if [ ! -f "$d/SHA256SUMS" ]; then
    c_warn "缺少 $d/SHA256SUMS（任务组 3.1 产出后此项生效）"
    return
  fi
  if ( cd "$d" && sha256sum -c SHA256SUMS --quiet 2>/dev/null ); then
    c_ok "SHA256SUMS 全部匹配"
  else
    c_fail "SHA256SUMS 不匹配（有人改了二进制？）"
  fi
}

# ---------------------------------------------------------------- 3. systemd unit 语法
check_units() {
  sec "3/6 systemd unit 语法"
  local n=0 bad=0 f
  for f in $(git ls-files 'cars/car22/rootfs/etc/systemd/system/*.service'); do
    n=$((n+1))
    if ! grep -q '^\[Unit\]' "$f" || ! grep -q '^\[Service\]' "$f"; then
      c_fail "$f 缺 [Unit] 或 [Service] 段"; bad=$((bad+1))
    fi
    if ! grep -q '^ExecStart=' "$f" && ! grep -q '^ExecStart=' "$f"; then
      c_warn "$f 没有 ExecStart（oneshot/template 可忽略）"
    fi
  done
  [ "$bad" -eq 0 ] && c_ok "检查 $n 个 unit 的段结构"
  if command -v systemd-analyze >/dev/null 2>&1; then
    # 只对 enable 状态无关的静态检查；缺依赖会大量 noise，故只统计明显语法错
    local vbad=0
    for f in $(git ls-files 'cars/car22/rootfs/etc/systemd/system/eprobot-*.service'); do
      systemd-analyze verify "$f" 2>&1 | grep -qiE 'Unknown section|Invalid setting|Failed to parse' && {
        c_warn "systemd-analyze 对 $f 有告警（依赖缺失属正常）"; vbad=$((vbad+1)); }
    done
    [ "$vbad" -eq 0 ] && c_ok "systemd-analyze 无语法级错误"
  else
    c_warn "无 systemd-analyze，跳过深度校验"
  fi
}

# ---------------------------------------------------------------- 4. .gitignore 覆盖
check_ignore() {
  sec "4/6 .gitignore 敏感文件覆盖"
  local pat miss=0 p
  for p in '*.key' '*.pem' 'id_rsa*' 'iscc.conf' 'chrony.keys' '__pycache__'; do
    if grep -qF "$p" .gitignore; then :; else c_fail ".gitignore 未覆盖：$p"; miss=$((miss+1)); fi
  done
  [ "$miss" -eq 0 ] && c_ok "关键敏感模式均已覆盖"
  # 反向验证：仓库里不该有真本
  if git ls-files | grep -qE '(^|/)iscc\.conf$|\.pem$|id_rsa$'; then
    c_fail "仓库里出现了疑似凭据文件"
  else
    c_ok "仓库内无 iscc.conf 真本 / 私钥 / pem"
  fi
}

# ---------------------------------------------------------------- 5. 文档命名风格
check_naming() {
  sec "5/6 docs/ 命名风格（统一中文名，允许 附录-/ADR 前缀）"
  local bad=0 f base
  for f in docs/*.md; do
    [ -e "$f" ] || continue
    base="$(basename "$f")"
    case "$base" in
      附录-*.md) : ;;                        # 生成物/附录
      *[![:ascii:]]*.md) : ;;                # 含非 ASCII（中文名），合规
      *) c_warn "docs/$base 不是中文名（新文档请用中文名或 附录- 前缀）"; bad=$((bad+1)) ;;
    esac
  done
  [ "$bad" -eq 0 ] && c_ok "docs/ 文档命名风格一致"
}

# ---------------------------------------------------------------- 6. 关键文件存在性
check_presence() {
  sec "6/6 关键文件与红线自检"
  local must=(
    "README.md" "NOTICE.md" "LICENSE" "LICENSE-DOCS" "SECRETS.md"
    "docs/竞赛笔记.md" "docs/竞赛笔记导读.md" "docs/新车部署手册.md"
    "docs/仓库结构与维护.md" "docs/学弟上手路径.md"
    "install/apply_to_car22.sh"
    "cars/car22/README.md" "cars/car21/README.md" "cars/car22/firmware/README.md"
  )
  local miss=0 m
  for m in "${must[@]}"; do
    [ -e "$m" ] || { c_warn "尚未产出：$m"; miss=$((miss+1)); }
  done
  [ "$miss" -eq 0 ] && c_ok "交接必需文件齐全"
  # 红线：二进制不得被 git 修改（对比 HEAD 与工作区）
  if git diff --quiet HEAD -- 'cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/'; then
    c_ok "lib/pharmacy_pkg 相对 HEAD 无改动（红线 1）"
  else
    c_fail "lib/pharmacy_pkg 相对 HEAD 有改动（违反红线 1）"
  fi
  # 红线：安装脚本保护逻辑仍在
  if grep -q 'MODE=dry' install/apply_to_car22.sh && grep -q '10.211.121.22（正在用车）' install/apply_to_car22.sh; then
    c_ok "apply_to_car22.sh 的 dry-run 与拒铺保护仍在（红线 4）"
  else
    c_fail "apply_to_car22.sh 保护逻辑被改动（违反红线 4）"
  fi
}

case "$ONLY" in
  links) check_links ;;
  *) check_links; check_sha; check_units; check_ignore; check_naming; check_presence ;;
esac

printf '\n\033[1m=== 结果：PASS %d / WARN %d / FAIL %d ===\033[0m\n' "$PASS" "$WARN" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
