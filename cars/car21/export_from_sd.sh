#!/usr/bin/env bash
# export_from_sd.sh —— 在 .22 上【只读】导出 .21 的系统卡内容
#
# 用法（在 .22 车上执行）：
#   bash export_from_sd.sh                 # 自动找 /dev/sda2
#   bash export_from_sd.sh /dev/sdb2       # 指定分区
#   OUT=/tmp/my.tgz bash export_from_sd.sh # 指定输出
#
# 安全保证：
#   1. 只读挂载（-o ro）
#   2. 退出/中断时自动 umount（trap）
#   3. 从不写卡；不 fsck、不 resize、不 chmod -R
set -euo pipefail

DEV="${1:-}"
OUT="${OUT:-/tmp/car21-export.tgz}"
MNT="${MNT:-/mnt/sd21}"

log() { printf '[export] %s\n' "$*"; }
die() { printf '[export] ERROR: %s\n' "$*" >&2; exit 1; }

# ---------- 1. 找分区 ----------
if [ -z "$DEV" ]; then
  DEV=$(lsblk -ln -o NAME,FSTYPE | awk '$2=="ext4"{print "/dev/"$1}' | grep -v mmcblk | head -1 || true)
fi
[ -n "$DEV" ] || die "找不到 ext4 分区；请手动指定（lsblk 看一眼）"
[ -b "$DEV" ] || die "$DEV 不是块设备"

# 安全闸：绝不能是 .22 自己的系统盘
case "$DEV" in
  *mmcblk*) die "$DEV 看起来是本机系统盘（mmcblk*），拒绝操作" ;;
esac

# 已经挂载就拒绝
if mountpoint -q "$MNT" 2>/dev/null; then
  die "$MNT 已挂载，先 sudo umount $MNT"
fi

log "目标分区：$DEV"
log "输出文件：$OUT"

# ---------- 2. 只读挂载 ----------
sudo mkdir -p "$MNT"
cleanup() {
  if mountpoint -q "$MNT" 2>/dev/null; then
    log "卸载 $MNT ..."
    sync
    sudo umount "$MNT" && log "已卸载 ✅" || log "⚠️ 卸载失败，请手动 sudo umount $MNT"
  fi
}
trap cleanup EXIT INT TERM

sudo mount -o ro "$DEV" "$MNT"
log "已只读挂载到 $MNT"

# 身份确认：防止读错卡
HOST=$(sudo cat "$MNT/etc/hostname" 2>/dev/null || echo "?")
log "卡内主机名：$HOST"
if [ "$HOST" != "EPRobot1" ]; then
  log "⚠️ 主机名不是 EPRobot1（是 $HOST），确认后再继续"
  read -r -p "继续？[y/N] " a
  [ "$a" = "y" ] || die "用户取消"
fi

# ---------- 3. 选路径 ----------
PATHS=(
  etc/hostname
  etc/os-release
  etc/netplan
  etc/hostapd
  etc/dnsmasq.d
  etc/default
  etc/udev/rules.d
  etc/systemd/system
  etc/chrony
  boot/firmware/config.txt
  boot/firmware/cmdline.txt
  boot/firmware/firstrun.sh
  usr/local/bin
  opt/eprobot_ws/src
  opt/eprobot_ws/install/pharmacy_pkg
  home/ubuntu/eprobot_navigation
  home/ubuntu/maps
  home/ubuntu/camera_shim
  home/ubuntu/board2_ocr
  home/ubuntu/nav_tune_web
  home/ubuntu/relay_ws/src
)

EXIST=()
for p in "${PATHS[@]}"; do
  if sudo test -e "$MNT/$p"; then EXIST+=("$p"); else log "跳过（不存在）：$p"; fi
done
[ "${#EXIST[@]}" -gt 0 ] || die "一个路径都没找到，检查挂载"

# ---------- 4. 打包 ----------
log "打包 ${#EXIST[@]} 个路径（跳过 .bak/pyc/大运行时）"
sudo tar czf "$OUT" -C "$MNT" \
  --exclude='*.bak_*' --exclude='*.pyc' --exclude='__pycache__' \
  --exclude='board2_ocr/runtime_arm64' \
  --exclude='opt/eprobot_ws/src/cartographer' \
  --exclude='opt/eprobot_ws/src/cartographer_ros' \
  "${EXIST[@]}"

log "完成：$OUT （$(du -h "$OUT" | cut -f1)）"
log "下一步（主机上）："
log "  scp keyuan22@10.211.121.22:$OUT ."
log "  mkdir -p /tmp/car21 && tar xzf $(basename "$OUT") -C /tmp/car21"

# trap 会负责 umount
