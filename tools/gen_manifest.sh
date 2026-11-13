#!/usr/bin/env bash
# tools/gen_manifest.sh —— 重新生成 docs/附录-文件清单.md
#
# 用法（仓库根目录）：
#   bash tools/gen_manifest.sh              # 写到 docs/附录-文件清单.md
#   bash tools/gen_manifest.sh /tmp/x.md    # 写到指定路径（selfcheck 用它做新旧对比）
#
# 说明：
#   * 以 git ls-files 为准，不扫磁盘（避免把 __pycache__ / .pytest_cache 算进去）
#   * 只读仓库，不联网
#   * 排除清单自身，保证重复生成结果一致
#   * 按区域分组，每区一张『大小 + 路径』列表，便于 grep
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
OUT="${1:-docs/附录-文件清单.md}"

command -v git >/dev/null || { echo "需要 git"; exit 1; }

# 区域定义：顺序即输出顺序，正则匹配路径（POSIX ERE，注意转义）
AREAS=(
  "README / NOTICE / 配置|^(README\.md|NOTICE\.md|LICENSE|LICENSE-DOCS|SECRETS\.md|\.gitattributes|\.gitignore)$"
  "docs（文档）|^docs/"
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
  "（未归类）|."
)

# 排除清单自身：否则它会列出自己的大小，内容每次生成都变，永远判定为「过期」
files=$(git ls-files | grep -v '^docs/附录-文件清单\.md$')
total=$(printf '%s\n' "$files" | grep -c . || true)
totalb=$(printf '%s\n' "$files" | while IFS= read -r f; do
  [ -f "$f" ] && stat -c %s "$f" 2>/dev/null || echo 0
done | awk '{s+=$1} END{print s+0}')

fmt() { # $1 = 字节
  awk -v b="$1" 'BEGIN{
    if (b>=1048576) printf "%7.1fM", b/1048576;
    else if (b>=1024) printf "%7.0fK", b/1024;
    else printf "%7dB", b }'
}

{
  echo "# 文件清单（自动生成）"
  echo
  echo "> 由 \`tools/gen_manifest.sh\` 以 \`git ls-files\` 生成，列出**每一个受管文件**及其大小。"
  echo "> \`__pycache__\`、\`.pytest_cache\` 等本地缓存在 \`.gitignore\` 里，不在本清单内。"
  echo "> **不要手改**——重跑脚本即可。"
  echo
  printf '**总计：%d 个文件，%.1f MB**\n' "$total" "$(awk -v b="$totalb" 'BEGIN{print b/1048576}')"
  echo
  echo "## 汇总"
  echo
  echo "| 区域 | 文件数 | 大小 |"
  echo "|---|---:|---:|"

  assigned=""
  for a in "${AREAS[@]}"; do
    name="${a%%|*}"; re="${a#*|}"
    [ "$name" = "（未归类）" ] && continue
    list=$(printf '%s\n' "$files" | grep -E "$re" || true)
    [ -z "$list" ] && continue
    n=$(printf '%s\n' "$list" | grep -c . || true)
    b=$(printf '%s\n' "$list" | while IFS= read -r f; do [ -f "$f" ] && stat -c %s "$f"; done | awk '{s+=$1} END{print s+0}')
    printf '| %s | %d | %s |\n' "$name" "$n" "$(awk -v b="$b" 'BEGIN{printf "%.1f MB", b/1048576}')"
    assigned="$assigned$list
"
  done

  rest=$(printf '%s\n' "$files" | grep -vFx -f <(printf '%s' "$assigned") 2>/dev/null || true)
  if [ -n "${rest:-}" ]; then
    rn=$(printf '%s\n' "$rest" | grep -c . || true)
    rb=$(printf '%s\n' "$rest" | while IFS= read -r f; do [ -f "$f" ] && stat -c %s "$f"; done | awk '{s+=$1} END{print s+0}')
    printf '| （未归类） | %d | %s |\n' "$rn" "$(awk -v b="$rb" 'BEGIN{printf "%.1f MB", b/1048576}')"
  fi
  echo

  for a in "${AREAS[@]}"; do
    name="${a%%|*}"; re="${a#*|}"
    [ "$name" = "（未归类）" ] && continue
    list=$(printf '%s\n' "$files" | grep -E "$re" | sort || true)
    [ -z "$list" ] && continue
    n=$(printf '%s\n' "$list" | grep -c . || true)
    b=$(printf '%s\n' "$list" | while IFS= read -r f; do [ -f "$f" ] && stat -c %s "$f"; done | awk '{s+=$1} END{print s+0}')
    echo "## $name"
    echo
    printf '合计 **%d** 个文件 / **%.2f MB**\n' "$n" "$(awk -v b="$b" 'BEGIN{print b/1048576}')"
    echo
    echo '```'
    while IFS= read -r f; do
      [ -f "$f" ] || continue
      size=$(stat -c %s "$f")
      printf '%s  %s\n' "$(fmt "$size")" "$f"
    done <<< "$list"
    echo '```'
    echo
  done

  echo '---'
  echo
  echo '## 怎么重新生成'
  echo
  echo '```bash'
  echo 'bash tools/gen_manifest.sh'
  echo '```'
} > "$OUT"

echo "generated: $OUT ($(wc -l < "$OUT") 行, $total 个文件)"
