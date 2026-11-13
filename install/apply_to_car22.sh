#!/usr/bin/env bash
# apply_to_car22.sh —— 把 cars/car22/rootfs 铺到一台（新）车上
#
# 设计原则：
#   * 默认 dry-run，什么都不写
#   * 写之前先把会被覆盖的东西备份到车上 ~/.backup_<时间戳>/
#   * 拒绝在 .22 本人身上跑（除非 --force），避免手滑覆盖在用车
#   * 远端逻辑放在一个临时脚本里执行，避免嵌套引号出错
#
# 用法：
#   bash install/apply_to_car22.sh --host 10.211.121.30 --user keyuan22 --dry-run
#   bash install/apply_to_car22.sh --host 10.211.121.30 --user keyuan22 --yes
#   bash install/apply_to_car22.sh --host 10.211.121.30 --user keyuan22 --yes --build
#
# 密码：优先用 SSH 密钥；否则 --pass 'xxx' 或环境变量 CAR_PASS（需 sshpass）
set -euo pipefail

HOST=""; USER_NAME="keyuan22"; PASS="${CAR_PASS:-}"; PORT=22
MODE=dry; DO_BUILD=0; DO_ENABLE=1; FORCE=0
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ROOTFS="$REPO_ROOT/cars/car22/rootfs"
SRC_WS="$REPO_ROOT/cars/car22/src/opt_eprobot_ws_src"
SRC_RELAY="$REPO_ROOT/cars/car22/src/relay_ws"

log()  { printf '\033[36m[apply]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[apply] WARN: %s\033[0m\n' "$*"; }
die()  { printf '\033[31m[apply] ERROR: %s\033[0m\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --user) USER_NAME="$2"; shift 2 ;;
    --pass) PASS="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --dry-run) MODE=dry; shift ;;
    --yes) MODE=real; shift ;;
    --build) DO_BUILD=1; shift ;;
    --no-enable) DO_ENABLE=0; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done

[ -n "$HOST" ] || die "必须给 --host <新车IP>"
[ -d "$ROOTFS" ] || die "找不到 $ROOTFS（请在仓库根目录跑）"
TARGET="$USER_NAME@$HOST"
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/$USER_NAME/.backup_$TS"

# ---------- ssh/scp 封装 ----------
if [ -n "$PASS" ]; then
  command -v sshpass >/dev/null || die "没装 sshpass（或改用 SSH 密钥登录）"
  export SSHPASS="$PASS"
  SSH=(sshpass -e ssh -p "$PORT" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
  SCP=(sshpass -e scp -P "$PORT" -o StrictHostKeyChecking=accept-new)
else
  SSH=(ssh -p "$PORT" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
  SCP=(scp -P "$PORT" -o StrictHostKeyChecking=accept-new)
fi
rsh() { "${SSH[@]}" "$TARGET" "$@"; }

log "=== 目标：$TARGET   模式：$([ "$MODE" = real ] && echo 真实执行 || echo DRY-RUN) ==="

# ---------- 1. 校验 ----------
log "1/8 校验目标车"
[ "$HOST" = "10.211.121.22" ] && [ "$FORCE" -ne 1 ] && \
  die "目标是 10.211.121.22（正在用车）。确认要覆盖请加 --force"
rsh 'true' || die "ssh 连不上 $TARGET"

INFO=$(rsh 'hostname; . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"; uname -m; ls -d /opt/ros/* 2>/dev/null | tr "\n" " "')
log "  实测：$(echo "$INFO" | tr '\n' ' ')"
echo "$INFO" | grep -q '/opt/ros/lyrical' || die "车上没有 /opt/ros/lyrical（ROS 2 Lyrical 未安装）"
rsh 'test -d /opt/eprobot_ws' || warn "没有 /opt/eprobot_ws —— 需要 --build 或手工建工作空间"

# ---------- 2. 生成远端脚本 ----------
log "2/8 生成远端执行脚本"
REMOTE_SH=$(mktemp)
trap 'rm -f "$REMOTE_SH"; rsh "rm -f /tmp/_apply_car22.sh" 2>/dev/null || true' EXIT

cat > "$REMOTE_SH" <<'REMOTE'
#!/usr/bin/env bash
# 在车上以 root 执行。环境变量：TARGET_USER / BACKUP_DIR / DO_ENABLE
set -euo pipefail
U="${TARGET_USER:-keyuan22}"
B="${BACKUP_DIR:?}"
ENABLE="${DO_ENABLE:-1}"

echo "[remote] 备份 -> $B"
mkdir -p "$B"
for p in \
  opt/eprobot_ws/install/pharmacy_pkg opt/oni2-orbbec \
  "home/$U/eprobot_navigation" "home/$U/camera_shim" "home/$U/board2_ocr" \
  "home/$U/nav_tune_web" "home/$U/maps" \
  usr/local/bin etc/default/eprobot-pharmacy etc/netplan etc/udev/rules.d etc/chrony ; do
  if [ -e "/$p" ]; then
    mkdir -p "$B/$(dirname "$p")"
    cp -a "/$p" "$B/$p" || echo "[remote] WARN: 备份 $p 失败"
  fi
done
du -sh "$B" || true

echo "[remote] 修正属主"
chown -R "$U":"$U" "/home/$U" || true

echo "[remote] OpenNI2 软链"
if [ -d /opt/oni2-orbbec ]; then
  cd /opt/oni2-orbbec
  ln -sf libOpenNI2.so libOpenNI2.so.0
  ln -sf libOpenNI2.so libOpenNI2.so.0.0
  ldconfig || true
  ls -l libOpenNI2.so* || true
fi

echo "[remote] systemd / udev"
systemctl daemon-reload || true
udevadm control --reload-rules || true
udevadm trigger || true
if [ "$ENABLE" = "1" ]; then
  systemctl enable eprobot-base eprobot-imu openni2-camera mono8-relay scan-viz 2>&1 | tail -6 || true
fi
for u in eprobot-base eprobot-imu openni2-camera mono8-relay scan-viz; do
  printf '  %-18s %s\n' "$u" "$(systemctl is-enabled "$u" 2>/dev/null || echo '-')"
done
echo "[remote] done"
REMOTE
chmod 755 "$REMOTE_SH"

# ---------- 3. 推送 ----------
if [ "$MODE" = real ]; then
  log "3/8 上传远端脚本"
  "${SCP[@]}" "$REMOTE_SH" "$TARGET:/tmp/_apply_car22.sh" >/dev/null

  log "4/8 推送 rootfs（$(du -sh "$ROOTFS" | cut -f1)）→ /"
  tar czf - -C "$ROOTFS" . | rsh "sudo -n tar xzf - -C /"

  log "5/8 执行远端步骤（备份/属主/软链/unit）"
  rsh "sudo -n env TARGET_USER='$USER_NAME' BACKUP_DIR='$BACKUP_DIR' DO_ENABLE='$DO_ENABLE' bash /tmp/_apply_car22.sh"
else
  log "3/8 [dry] scp 远端脚本 → /tmp/_apply_car22.sh"
  log "4/8 [dry] tar czf - -C cars/car22/rootfs . | ssh $TARGET 'sudo tar xzf - -C /'  ($(du -sh "$ROOTFS" | cut -f1))"
  log "5/8 [dry] sudo env TARGET_USER=$USER_NAME BACKUP_DIR=$BACKUP_DIR DO_ENABLE=$DO_ENABLE bash /tmp/_apply_car22.sh"
fi

# ---------- 6. 编译 ----------
if [ "$DO_BUILD" -eq 1 ]; then
  log "6/8 colcon build"
  if [ "$MODE" = real ]; then
    [ -d "$SRC_WS" ] && tar czf - -C "$SRC_WS" . | rsh "sudo -n tar xzf - -C /opt/eprobot_ws/src"
    [ -d "$SRC_RELAY" ] && tar czf - -C "$SRC_RELAY" . | rsh "mkdir -p ~/relay_ws/src && tar xzf - -C ~/relay_ws/src"
    rsh "bash -lc 'set -e; source /opt/ros/lyrical/setup.bash; cd /opt/eprobot_ws; colcon build --symlink-install 2>&1 | tail -25'"
    rsh "bash -lc 'set -e; source /opt/ros/lyrical/setup.bash; cd ~/relay_ws; colcon build --packages-select mono8_relay 2>&1 | tail -12'"
  else
    log "  [dry] 推 src → /opt/eprobot_ws/src 与 ~/relay_ws/src"
    log "  [dry] colcon build --symlink-install（/opt/eprobot_ws）"
    log "  [dry] colcon build --packages-select mono8_relay（~/relay_ws）"
  fi
else
  log "6/8 跳过编译（加 --build 才会编）"
fi

# ---------- 7/8 收尾 ----------
log "7/8 之后必须人工做："
cat <<NEXT
    ① 改 IP/热点（两个 netplan 文件都要改）→ sudo netplan try
    ② iscc version && iscc kill && iscc pre
    ③ iscc gray      # 相机有图
    ④ iscc rviz2     # 激光贴墙
    ⑤ 重标航点（换车必做，见 docs/新车部署手册.md §4）
    ⑥ 改 pharmacy.yaml 的 judge_tcp.host
    ⑦ iscc start     # ★ 车会动
NEXT
log "8/8 车上备份目录：$BACKUP_DIR"
[ "$MODE" = dry ] && log "（以上全是 dry-run，没有写任何东西）"
