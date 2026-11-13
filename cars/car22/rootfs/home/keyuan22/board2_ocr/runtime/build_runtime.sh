#!/bin/bash
# build_runtime.sh —— 在 arm64 Ubuntu 26.04 上重建板二 OCR 的 Python 运行时
#
# 产物：./runtime_arm64/（约 276 MB，20 个包，与车上那份等价）
# 用法：bash build_runtime.sh [-f]
#   -f  强制重建（先删掉已有 runtime_arm64）
#
# 设计：只做"装 + 自证"，不改系统 Python、不建 venv（原因见 README §1）。
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HERE/runtime_arm64"
LOCK="$HERE/requirements.lock"

say() { printf '\033[36m[build]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[build] ERROR: %s\033[0m\n' "$*" >&2; exit 1; }

FORCE=0
[ "${1:-}" = "-f" ] && FORCE=1

# ---------------------------------------------------------------- 0. 环境硬校验
say "0/5 校验环境"
[ "$(uname -m)" = "aarch64" ] || die "必须在 aarch64 上构建（当前 $(uname -m)）；x86 装出来的 onnxruntime 拷到车上会 Illegal instruction"

PYV="$(/usr/bin/python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
say "   system python: /usr/bin/python3 = $PYV"
case "$PYV" in
  3.14) : ;;
  *) die "系统 Python 必须是 3.14.x（本车实测 3.14.4）。当前 $PYV —— 版本不同会导致 .so 不兼容" ;;
esac

command -v pip3 >/dev/null 2>&1 || die "缺 pip3：sudo apt-get install -y python3-pip"
[ -f "$LOCK" ] || die "缺 $LOCK"

# ---------------------------------------------------------------- 1. 清场
say "1/5 准备目录"
if [ -d "$TARGET" ]; then
  if [ "$FORCE" -eq 1 ]; then
    say "   -f 指定，删除已有 runtime_arm64（$(du -sh "$TARGET" | cut -f1)）"
    rm -rf "$TARGET"
  else
    die "$TARGET 已存在。要重建请加 -f（会先删除）"
  fi
fi
mkdir -p "$TARGET"

# ---------------------------------------------------------------- 2. 安装
say "2/5 pip install --target（这一步最慢，约 276 MB）"
# --no-compile：不生成 .pyc，省 ~40 MB，且首次 import 会慢一点（可接受）
# --upgrade    ：确保 lock 里的版本为准，不复用旧残留
pip3 install \
  --target "$TARGET" \
  --no-compile \
  --upgrade \
  --disable-pip-version-check \
  -r "$LOCK"

# ---------------------------------------------------------------- 3. 结构自检
say "3/5 核对包数与关键版本"
N=$(find "$TARGET" -maxdepth 1 -name '*.dist-info' | wc -l)
say "   已安装 $N 个包（期望 20）"
[ "$N" -ge 18 ] || die "包数明显不足（$N），检查网络或 pip 源"

for pkg in onnxruntime rapidocr cv2 numpy; do
  /usr/bin/python3 - "$TARGET" "$pkg" <<'PY' || die "import $pkg 失败"
import sys, importlib
target, pkg = sys.argv[1], sys.argv[2]
sys.path.insert(0, target)
m = importlib.import_module(pkg)
ver = getattr(m, "__version__", "(no __version__)")
print(f"   {pkg:<12} {ver}")
PY
done

# ---------------------------------------------------------------- 4. 体积
SIZE=$(du -sh "$TARGET" | cut -f1)
say "4/5 产物体积：$SIZE（车上那份是 276M，差 10% 以内属正常）"

# ---------------------------------------------------------------- 5. 下一步
say "5/5 完成。现在自证（会用 13 张真实牌面）："
cat <<EOF

   bash $HERE/../selftest_arm64.sh

   期望：先打印 READY，然后每张牌面一行 FREE / BUSY_<n>；
         pass*.png → FREE，wait5..10*.png → 对应 BUSY_5..BUSY_10。
         13 张里 ≥12 张正确即健康。

   若要端到端验证：把 runtime_arm64 放回 ~/board2_ocr/ 后
     sudo systemctl restart eprobot-pharmacy
     ros2 topic pub --once /pharmacy/board2_control std_msgs/msg/Bool "{data: true}"
     ros2 topic echo --once /pharmacy/board2_status

EOF
