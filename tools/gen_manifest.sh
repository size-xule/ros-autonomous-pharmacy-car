#!/usr/bin/env bash
# tools/gen_manifest.sh —— 重新生成 docs/附录-文件清单.md
#
# 用法（仓库根目录）：
#   bash tools/gen_manifest.sh              # 写到 docs/附录-文件清单.md
#   bash tools/gen_manifest.sh /tmp/x.md    # 写到指定路径（selfcheck 用它做新旧对比）
#
# 说明：
#   * 以 **HEAD 里已提交的 blob 大小**为准（git ls-tree -r -l），不读工作区
#     → 换平台/换行尾（CRLF↔LF）都不会让清单"抖动"，干净 clone 上也判定为最新
#   * 不扫磁盘（避免把 __pycache__ / .pytest_cache 算进去）
#   * 排除清单自身（否则它会列出自己的大小，永不稳定）
#   * git 的 core.quotepath 会对中文名做八进制转义，这里统一关掉
#   * 只读仓库，不联网
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
OUT="${1:-docs/附录-文件清单.md}"
SELF_REL="docs/附录-文件清单.md"

command -v git >/dev/null || { echo "需要 git"; exit 1; }

# path<TAB>size —— 取自已提交的树，按 path 排序，排除自身
DATA=$(git -c core.quotepath=false ls-tree -r -l HEAD \
       | awk -F'\t' '{ n=split($1,a," "); if (a[2]=="blob") print $2"\t"a[4] }' \
       | awk -F'\t' -v self="$SELF_REL" '$1 != self' \
       | sort)

total=$(printf '%s\n' "$DATA" | grep -c . || true)
totalb=$(printf '%s\n' "$DATA" | awk -F'\t' '{s+=$2} END{print s+0}')

AREAS=(
  "README / NOTICE / 许可|^(README\.md|NOTICE\.md|LICENSE|LICENSE-DOCS|SECRETS\.md|\.gitattributes|\.gitignore)$"
  "docs（文档）|^docs/[^/]+\.md$"
  "docs/adr（决策记录）|^docs/adr/"
  "install（安装脚本）|^install/"
  "tools（主机侧工具）|^tools/"
  "cars/car22 · 本车档案|^cars/car22/[^/]+$"
  "cars/car22 · 固件|^cars/car22/firmware/"
  "cars/car22 · 任务包|^cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/"
  "cars/car22 · 底盘驱动C++|^cars/car22/rootfs/opt/eprobot_ws/install/eprobot_base_cpp/"
  "cars/car22 · 相机SDK|^cars/car22/rootfs/opt/oni2-orbbec/"
  "cars/car22 · home|^cars/car22/rootfs/home/"
  "cars/car22 · etc|^cars/car22/rootfs/etc/"
  "cars/car22 · usr/local/bin|^cars/car22/rootfs/usr/"
  "cars/car22 · src（要编译）|^cars/car22/src/"
  "cars/car21|^cars/car21/"
)

fmt() {
  awk -v b="$1" 'BEGIN{
    if (b>=1048576) printf "%7.1fM", b/1048576;
    else if (b>=1024) printf "%7.0fK", b/1024;
    else printf "%7dB", b }'
}
mb()  { awk -v b="$1" 'BEGIN{printf "%.1f", b/1048576}'; }
mb2() { awk -v b="$1" 'BEGIN{printf "%.2f", b/1048576}'; }

# 按正则汇总字节数（用 bash 正则，避免 awk/grep 的反斜杠转义坑）
area_sum() {
  local re="$1" s=0 p sz
  while IFS=$'\t' read -r p sz; do
    [ -z "${p:-}" ] && continue
    [[ $p =~ $re ]] && s=$((s + sz))
  done <<< "$DATA"
  echo "$s"
}
# 按正则取路径清单（cut 出路径再 grep，锚点 ^...$ 才能正确工作）
area_list() { printf '%s\n' "$DATA" | cut -f1 | grep -E "$1" || true; }
# 单个文件的字节数
size_of() { printf '%s\n' "$DATA" | awk -F'\t' -v p="$1" '$1==p{print $2; exit}'; }

{
  echo "# 文件清单（自动生成）"
  echo
  echo "> 由 \`tools/gen_manifest.sh\` 生成，数据源是 **HEAD 里已提交的 blob 大小**（\`git ls-tree -r -l\`），"
  echo "> 因此与工作区换行符（CRLF/LF）和 \`__pycache__\` 等本地缓存无关，**干净 clone 上重跑结果一致**。"
  echo "> **不要手改**——重跑脚本即可。"
  echo
  printf '**总计：%d 个文件，%.1f MB**（不含本清单自身）\n' "$total" "$(mb "$totalb")"
  echo
  echo "## 汇总"
  echo
  echo "| 区域 | 文件数 | 大小 |"
  echo "|---|---:|---:|"

  assigned=""
  for a in "${AREAS[@]}"; do
    name="${a%%|*}"; re="${a#*|}"
    list=$(area_list "$re")
    [ -z "$list" ] && continue
    n=$(printf '%s\n' "$list" | grep -c . || true)
    b=$(area_sum "$re")
    printf '| %s | %d | %s MB |\n' "$name" "$n" "$(mb "$b")"
    assigned="$assigned$list
"
  done

  rest=$(printf '%s\n' "$DATA" | cut -f1 | grep -vFx -f <(printf '%s' "$assigned") 2>/dev/null || true)
  if [ -n "${rest:-}" ]; then
    rn=$(printf '%s\n' "$rest" | grep -c . || true)
    rb=0
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      rb=$((rb + $(size_of "$f")))
    done <<< "$rest"
    printf '| （未归类） | %d | %s MB |\n' "$rn" "$(mb "$rb")"
  fi
  echo

  for a in "${AREAS[@]}"; do
    name="${a%%|*}"; re="${a#*|}"
    list=$(area_list "$re" | sort)
    [ -z "$list" ] && continue
    n=$(printf '%s\n' "$list" | grep -c . || true)
    b=$(area_sum "$re")
    echo "## $name"
    echo
    printf '合计 **%d** 个文件 / **%s MB**\n' "$n" "$(mb2 "$b")"
    echo
    echo '```'
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      printf '%s  %s\n' "$(fmt "$(size_of "$f")")" "$f"
    done <<< "$list"
    echo '```'
    echo
  done

  echo '---'
  echo
  echo '## 怎么重新生成'
  echo
  echo '```bash'
  echo 'bash tools/gen_manifest.sh              # 写到 docs/附录-文件清单.md'
  echo 'bash tools/gen_manifest.sh /tmp/x.md    # 写到指定路径（selfcheck 用）'
  echo '```'
} > "$OUT"

echo "generated: $OUT ($(wc -l < "$OUT") 行, $total 个文件)"
