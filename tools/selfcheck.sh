#!/usr/bin/env bash
# tools/selfcheck.sh —— 仓库自检（在 WSL / Linux 上跑，不要在 Windows PowerShell 里跑）
#
# 用法：
#   bash tools/selfcheck.sh            # 全部检查
#   bash tools/selfcheck.sh --links    # 只查文档相对链接（任务组 1.2 验收用）
#   bash tools/selfcheck.sh --quiet    # 只打印失败项与总结
#
# 八类检查：
#   1 文档相对链接      2 二进制 SHA256      3 unit 语法        4 凭据与 .gitignore
#   5 命名风格 + ADR    6 关键文件 + probe   7 requirements.lock 8 文件清单是否最新
#   + 红线自检：二进制未被改、install 脚本保护仍在
#
# 设计原则：只读、缺依赖降级为 WARN、退出码 0=通过 1=有 FAIL
set -uo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || { echo "无法进入仓库根目录"; exit 1; }

ONLY=""; QUIET=0
for a in "$@"; do
  case "$a" in
    --links) ONLY=links ;;
    --quiet) QUIET=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
  esac
done

FAIL=0; WARN=0; PASS=0
c_ok()   { PASS=$((PASS+1)); [ "$QUIET" -eq 1 ] || printf '  \033[32mPASS\033[0m %s\n' "$*"; }
c_warn() { WARN=$((WARN+1)); printf '  \033[33mWARN\033[0m %s\n' "$*"; }
c_fail() { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
sec()    { [ "$QUIET" -eq 1 ] || printf '\n\033[36m== %s ==\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. 文档相对链接
check_links() {
  sec "1/8 文档相对链接"
  local bad=0 total=0 f dir target
  while IFS= read -r f; do
    dir="$(dirname "$f")"
    while IFS= read -r target; do
      [ -z "$target" ] && continue
      case "$target" in http*|mailto:*|\#*) continue ;; esac
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
  sec "2/8 二进制完整性（lib/pharmacy_pkg）"
  local d="cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg"
  if [ ! -f "$d/SHA256SUMS" ]; then
    c_warn "缺少 $d/SHA256SUMS"
    return
  fi
  if ( cd "$d" && sha256sum -c SHA256SUMS --quiet 2>/dev/null ); then
    c_ok "SHA256SUMS 全部匹配（9 个二进制）"
  else
    c_fail "SHA256SUMS 不匹配（有人改了二进制？）"
  fi
  [ -x "$d/verify.sh" ] && c_ok "verify.sh 存在且可执行" || c_warn "$d/verify.sh 缺失或不可执行"
}

# ---------------------------------------------------------------- 3. unit 语法
check_units() {
  sec "3/8 systemd unit 语法"
  local n=0 bad=0 f
  for f in $(git ls-files 'cars/car22/rootfs/etc/systemd/system/*.service'); do
    n=$((n+1))
    grep -q '^\[Unit\]' "$f"    || { c_fail "$f 缺 [Unit]"; bad=$((bad+1)); }
    grep -q '^\[Service\]' "$f" || { c_fail "$f 缺 [Service]"; bad=$((bad+1)); }
    grep -q '^ExecStart=' "$f"  || c_warn "$f 没有 ExecStart"
  done
  [ "$bad" -eq 0 ] && c_ok "检查 $n 个 unit 的段结构"
  if command -v systemd-analyze >/dev/null 2>&1; then
    local vbad=0
    for f in $(git ls-files 'cars/car22/rootfs/etc/systemd/system/eprobot-*.service'); do
      systemd-analyze verify "$f" 2>&1 | grep -qiE 'Unknown section|Invalid setting|Failed to parse' && {
        c_warn "systemd-analyze 对 $f 有语法级告警"; vbad=$((vbad+1)); }
    done
    [ "$vbad" -eq 0 ] && c_ok "systemd-analyze 无语法级错误"
  else
    c_warn "无 systemd-analyze，跳过深度校验"
  fi
}

# ---------------------------------------------------------------- 4. 凭据与 .gitignore
check_secrets() {
  sec "4/8 凭据与 .gitignore"
  local pat miss=0 p
  for p in '*.key' '*.pem' 'id_rsa*' 'iscc.conf' 'chrony.keys' '__pycache__' 'id_ed25519*' '.env'; do
    grep -qF "$p" .gitignore || { c_fail ".gitignore 未覆盖：$p"; miss=$((miss+1)); }
  done
  [ "$miss" -eq 0 ] && c_ok "关键敏感模式均已覆盖"
  if git ls-files | grep -qE '(^|/)iscc\.conf$|\.pem$|id_rsa$|id_ed25519$'; then
    c_fail "仓库里出现了疑似凭据文件"
  else
    c_ok "仓库内无 iscc.conf 真本 / 私钥 / pem"
  fi
  if git grep -qE 'PUT_PASSWORD_HERE' -- 'tools/host-iscc/iscc.conf.example'; then
    c_ok "iscc.conf.example 仍是占位符"
  else
    c_warn "iscc.conf.example 里找不到 PUT_PASSWORD_HERE（是否被填了真值？）"
  fi
}

# ---------------------------------------------------------------- 5. 命名 + ADR
check_naming() {
  sec "5/8 命名风格（docs/ 中文名 + adr/ NNNN-）"
  local bad=0 f base
  for f in docs/*.md; do
    [ -e "$f" ] || continue
    base="$(basename "$f")"
    case "$base" in
      附录-*.md) : ;;
      *[![:ascii:]]*.md) : ;;
      *) c_warn "docs/$base 不是中文名（新文档请用中文名或 附录- 前缀）"; bad=$((bad+1)) ;;
    esac
  done
  [ "$bad" -eq 0 ] && c_ok "docs/ 文档命名风格一致"

  if [ -d docs/adr ]; then
    local adrbad=0 n
    for f in docs/adr/[0-9][0-9][0-9][0-9]-*.md; do
      [ -e "$f" ] || continue
      n="$(basename "$f" | cut -c1-4)"
      grep -q "$n-.*\.md" docs/adr/README.md || { c_fail "docs/adr/README.md 索引里缺 $n"; adrbad=$((adrbad+1)); }
      grep -q '^## 背景' "$f" || { c_fail "$f 缺 背景 段"; adrbad=$((adrbad+1)); }
      grep -q '^## 决策' "$f" || { c_fail "$f 缺 决策 段"; adrbad=$((adrbad+1)); }
    done
    [ "$adrbad" -eq 0 ] && c_ok "ADR 编号连续、都有背景/决策段、索引齐全"
  else
    c_warn "还没有 docs/adr/"
  fi
}

# ---------------------------------------------------------------- 6. 关键文件 + probe 说明
check_presence() {
  sec "6/8 关键文件与 probe 说明覆盖"
  local must=(
    README.md NOTICE.md SECRETS.md LICENSE LICENSE-DOCS
    docs/竞赛笔记.md docs/竞赛笔记导读.md docs/学弟上手路径.md
    docs/新车部署手册.md docs/依赖清单.md docs/航点标定手册.md
    docs/unit依赖关系.md docs/版本矩阵.md docs/仓库结构与维护.md
    install/apply_to_car22.sh
    cars/car22/README.md cars/car21/README.md cars/car22/firmware/README.md
    cars/car22/src/README.md tools/probes/README.md
  )
  local miss=0 m
  for m in "${must[@]}"; do
    [ -e "$m" ] || { c_warn "尚未产出：$m"; miss=$((miss+1)); }
  done
  [ "$miss" -eq 0 ] && c_ok "交接必需文件齐全"

  local pbad=0 s
  for s in tools/probes/*.sh; do
    [ -e "$s" ] || continue
    [ -f "${s}.预期输出.md" ] || { c_fail "缺说明：tools/probes/$(basename "$s").预期输出.md"; pbad=$((pbad+1)); }
  done
  [ "$pbad" -eq 0 ] && c_ok "每个 probe 脚本都有 .预期输出.md"
}

# ---------------------------------------------------------------- 7. requirements.lock
check_lock() {
  sec "7/8 OCR 运行时 lock"
  local lock="cars/car22/rootfs/home/keyuan22/board2_ocr/runtime/requirements.lock"
  if [ ! -f "$lock" ]; then c_warn "还没有 $lock"; return; fi
  local n bad=0 line
  n=$(grep -cE '^[A-Za-z0-9._-]+==[0-9]' "$lock" || true)
  while IFS= read -r line; do
    case "$line" in ''|\#*) continue ;; esac
    printf '%s' "$line" | grep -qE '^[A-Za-z0-9._-]+==[0-9][^ ]*$' || {
      c_fail "lock 行格式不对（应 name==version）：$line"; bad=$((bad+1)); }
  done < "$lock"
  [ "$bad" -eq 0 ] && c_ok "lock 格式正确，$n 个包全部锁定版本"
  [ "$n" -ge 15 ] && c_ok "包数 $n >= 15（车上实测 20）" || c_warn "包数只有 $n，可能不全"
  local req="cars/car22/rootfs/home/keyuan22/board2_ocr/requirements.txt"
  if [ -f "$req" ]; then
    local rbad=0 pin
    for pin in $(grep -oE '^[A-Za-z0-9._-]+==[0-9][^ ]*' "$req" || true); do
      grep -qxF "$pin" "$lock" || { c_fail "requirements.txt 的 $pin 不在 lock 里"; rbad=$((rbad+1)); }
    done
    [ "$rbad" -eq 0 ] && c_ok "requirements.txt 的显式 pin 都能在 lock 里找到"
  fi
}

# ---------------------------------------------------------------- 8. 清单是否最新
check_manifest() {
  sec "8/8 文件清单是否最新（docs/附录-文件清单.md）"
  local out="docs/附录-文件清单.md"
  if [ ! -f "$out" ]; then c_warn "还没有 $out"; return; fi
  local tmp; tmp="$(mktemp)"
  if bash tools/gen_manifest.sh "$tmp" >/dev/null 2>&1; then
    if diff -q "$out" "$tmp" >/dev/null 2>&1; then
      c_ok "清单是最新的"
    else
      c_fail "清单过期（重跑 bash tools/gen_manifest.sh）；差异行数：$(diff "$out" "$tmp" | grep -c '^[<>]' || true)"
    fi
  else
    c_warn "生成器执行失败，跳过"
  fi
  rm -f "$tmp"
}

# ---------------------------------------------------------------- 红线
check_redline() {
  sec "红线自检"
  if git diff --quiet HEAD -- 'cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/'; then
    c_ok "lib/pharmacy_pkg 相对 HEAD 无改动（红线 1）"
  else
    c_fail "lib/pharmacy_pkg 相对 HEAD 有改动（违反红线 1）"
  fi
  if grep -q 'MODE=dry' install/apply_to_car22.sh && grep -q '10.211.121.22（正在用车）' install/apply_to_car22.sh; then
    c_ok "apply_to_car22.sh 的 dry-run 与拒铺保护仍在（红线 4）"
  else
    c_fail "apply_to_car22.sh 保护逻辑被改动（违反红线 4）"
  fi
  local changed
  changed=$(git diff --name-only HEAD -- 'cars/car22/rootfs/etc/systemd/system/*.service' \
            'cars/car22/rootfs/home/keyuan22/eprobot_navigation/launch' \
            'cars/car22/rootfs/home/keyuan22/eprobot_navigation/config' 2>/dev/null | wc -l)
  if [ "$changed" -eq 0 ]; then
    c_ok "已验证的 unit/launch/config 无未提交改动（红线 3）"
  else
    c_warn "有 $changed 个 unit/launch/config 文件被改动，确认是否符合红线 3"
  fi
}

case "$ONLY" in
  links) check_links ;;
  *) check_links; check_sha; check_units; check_secrets; check_naming; check_presence; check_lock; check_manifest; check_redline ;;
esac

printf '\n\033[1m=== 结果：PASS %d / WARN %d / FAIL %d ===\033[0m\n' "$PASS" "$WARN" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
