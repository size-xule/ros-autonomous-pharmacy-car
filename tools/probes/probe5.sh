#!/usr/bin/env bash
# READ-ONLY probe. No writes, no service changes, no mounts.
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
S="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"

echo "==== 块设备（看 SD 卡在不在） ===="
$S $H 'lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT 2>/dev/null; echo "--- /dev/sd* ---"; ls -l /dev/sd* 2>/dev/null || echo none'
echo
echo "==== 网络：netplan / NetworkManager ===="
$S $H 'ls /etc/netplan/ 2>/dev/null; echo "--- netplan 内容 ---"; sudo -n cat /etc/netplan/*.yaml 2>/dev/null || echo "需要密码或无权限"; echo "--- 连接 ---"; nmcli -t -f NAME,TYPE,DEVICE con show 2>/dev/null; echo "--- 服务 ---"; for s in NetworkManager systemd-networkd hostapd dnsmasq wpa_supplicant; do printf "%-18s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"; done'
echo
echo "==== 当前 IP / 路由 / WiFi ===="
$S $H 'ip -4 -o addr show | grep -v " lo "; echo "--- route ---"; ip route; echo "--- iw ---"; iw dev wlan0 link 2>/dev/null | head -6'
echo
echo "==== IMU：udev 规则与配置 ===="
$S $H 'cat /etc/udev/rules.d/99-eprobot-h30.rules 2>/dev/null; echo "--- 设备 ---"; ls -l /dev/EPRobot_imu /dev/ttyACM* 2>/dev/null; echo "--- unit ---"; systemctl cat eprobot-imu 2>/dev/null | grep -E "ExecStart|Environment"'
echo
echo "==== yesense 配置（前 30 行） ===="
$S $H 'head -30 /opt/eprobot_ws/install/yesense_std_ros2/share/yesense_std_ros2/config/yesense_config.yaml 2>/dev/null'
echo
echo "==== 温度 / 降频 / 频率 ===="
$S $H 'vcgencmd measure_temp 2>/dev/null; vcgencmd get_throttled 2>/dev/null; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null; nproc; uptime'
