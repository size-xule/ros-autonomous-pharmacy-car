#!/usr/bin/env bash
# backup_car.sh —— 从车上【只读】打包一份快照到本地（用于更新本仓库）
#
# 用法：
#   CAR_PASS=xxx bash tools/backup_car.sh --host 10.211.121.22 --user keyuan22 --out ~/car22-snapshot
#   bash tools/backup_car.sh --host ... --user ... --out ... --full   # 连 src/ 与模型一起
#
# 保证：车上不写任何文件（tar 流式输出到本地管道）
set -euo pipefail

HOST=""; USER_NAME="keyuan22"; PASS="${CAR_PASS:-}"; OUT="./car22-snapshot"; PORT=22; FULL=0
log() { printf '[backup] %s\n' "$*"; }
die() { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER_NAME="$2"; shift 2 ;;
    --pass) PASS="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --full) FULL=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done
[ -n "$HOST" ] || die "必须给 --host"

if [ -n "$PASS" ]; then
  command -v sshpass >/dev/null || die "没装 sshpass"
  export SSHPASS="$PASS"
  SSH=(sshpass -e ssh -p "$PORT" -o StrictHostKeyChecking=accept-new)
else
  SSH=(ssh -p "$PORT" -o StrictHostKeyChecking=accept-new)
fi
TARGET="$USER_NAME@$HOST"

mkdir -p "$OUT"
log "目标 $TARGET → $OUT"

PATHS=(
  opt/eprobot_ws/install/pharmacy_pkg
  opt/oni2-orbbec
  "home/$USER_NAME/eprobot_navigation"
  "home/$USER_NAME/camera_shim"
  "home/$USER_NAME/board2_ocr"
  "home/$USER_NAME/nav_tune_web"
  "home/$USER_NAME/maps"
  usr/local/bin
  etc/systemd/system
  etc/default/eprobot-pharmacy
  etc/netplan
  etc/udev/rules.d
  etc/chrony
)
if [ "$FULL" -eq 1 ]; then
  PATHS+=(opt/eprobot_ws/src "home/$USER_NAME/relay_ws/src")
fi

EXCL="--exclude=*.bak_* --exclude=*.pyc --exclude=__pycache__ --exclude=chrony.keys"
[ "$FULL" -eq 1 ] || EXCL="$EXCL --exclude=board2_ocr/runtime_arm64"

log "打包 ${#PATHS[@]} 个路径（${FULL:+full 模式}）"
"${SSH[@]}" "$TARGET" "sudo -n tar czf - -C / $EXCL $(printf '%q ' "${PATHS[@]}")" > "$OUT/rootfs.tgz"

log "已保存 $OUT/rootfs.tgz （$(du -h "$OUT/rootfs.tgz" | cut -f1)）"
log "解包：mkdir -p $OUT/rootfs && tar xzf $OUT/rootfs.tgz -C $OUT/rootfs"
log "对比：diff -r $OUT/rootfs cars/car22/rootfs | head -50"
