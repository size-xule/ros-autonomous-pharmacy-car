#!/usr/bin/env bash
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
S="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"

echo "==== eprobot-pharmacy.service ExecStart ===="
$S $H 'systemctl cat eprobot-pharmacy 2>/dev/null | grep -E "ExecStart|Environment|EnvironmentFile"'
echo
echo "==== f1_mission_node 里的语音相关字符串 ===="
$S $H 'B=/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/f1_mission_node; for k in car_speech paplay aplay speech_status speech_ready "loaded" "WAV"; do printf "%-16s %s\n" "$k" "$(strings $B | grep -c "$k")"; done'
echo
echo "==== f1_mission_node 是否含 board2 后端名字 ===="
$S $H 'strings /opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/f1_mission_node | grep -E "board2|ac_transit|qr_reposition|board2_exit|C>B|A>B" | sort -u | head -20'
echo
echo "==== pharmacy_speech_node 是否被实际启动过 ===="
$S $H 'ls -l /opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/ | grep -E "speech|board2|qr|judge"; echo "--- board2_ocr 目录 ---"; ls /home/keyuan22/board2_ocr 2>/dev/null | head'
