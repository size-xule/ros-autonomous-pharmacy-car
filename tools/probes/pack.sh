#!/usr/bin/env bash
# READ-ONLY: stream tar from the car to Windows. Nothing is written on the car.
set -u
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 keyuan22@10.211.121.22"
OUT=/mnt/d/ISCC/_stage

mkdir -p "$OUT"

echo "==== [1/2] 软件与源码（/opt） ===="
$SSH "sudo -n tar czf - -C / \
  --exclude='*.bak_*' --exclude='*.pyc' --exclude='__pycache__' \
  opt/eprobot_ws/install/pharmacy_pkg \
  opt/eprobot_ws/src/eprobot_base \
  opt/eprobot_ws/src/lslidar_ros2 \
  opt/eprobot_ws/src/serial_ros2 \
  opt/eprobot_ws/src/yesense_interface \
  opt/eprobot_ws/src/yesense_std_ros2 \
  opt/oni2-orbbec" > "$OUT/opt.tgz"
echo "  -> $(du -h "$OUT/opt.tgz" | cut -f1)"

echo "==== [2/2] 配置/脚本/模型（/home + /etc + /usr/local） ===="
$SSH "sudo -n tar czf - \
  --exclude='*.bak_*' --exclude='*.pyc' --exclude='__pycache__' \
  --exclude='board2_ocr/runtime_arm64' \
  -C / home/keyuan22/eprobot_navigation home/keyuan22/camera_shim \
       home/keyuan22/relay_ws/src home/keyuan22/board2_ocr home/keyuan22/nav_tune_web \
       home/keyuan22/maps \
       usr/local/bin \
       etc/default/eprobot-pharmacy \
       etc/netplan etc/udev/rules.d etc/chrony" > "$OUT/etc-home.tgz"
echo "  -> $(du -h "$OUT/etc-home.tgz" | cut -f1)"

echo "==== systemd 单元（只取 .service 普通文件） ===="
$SSH "sudo -n tar czf - -C / \$(sudo -n find etc/systemd/system -maxdepth 2 -name '*.service' -type f -printf '%p ') 2>/dev/null" > "$OUT/systemd.tgz"
echo "  -> $(du -h "$OUT/systemd.tgz" | cut -f1)"
$SSH "sudo -n tar tzf - -C / \$(sudo -n find etc/systemd/system -maxdepth 2 -name '*.service' -type f -printf '%p ') 2>/dev/null | head -30" < "$OUT/systemd.tgz"

echo "==== 完成 ===="
ls -lh "$OUT"
