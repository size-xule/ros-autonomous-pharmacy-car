#!/usr/bin/env bash
# READ-ONLY size survey of candidate upload paths
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
S="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"

echo "==== 候选目录体积 ===="
$S $H 'for p in \
 /opt/eprobot_ws/install/pharmacy_pkg \
 /opt/eprobot_ws/src \
 /home/keyuan22/eprobot_navigation \
 /home/keyuan22/camera_shim \
 /home/keyuan22/relay_ws \
 /home/keyuan22/board2_ocr \
 /home/keyuan22/nav_tune_web \
 /home/keyuan22/maps \
 /home/keyuan22/prematch_hiscore \
 /opt/oni2-orbbec \
 /usr/local/bin ; do
   if [ -e "$p" ]; then printf "%-45s %s\n" "$p" "$(sudo -n du -sh $p 2>/dev/null | cut -f1)"; else printf "%-45s MISSING\n" "$p"; fi
 done'

echo "==== board2_ocr 细分 ===="
$S $H 'sudo -n du -sh /home/keyuan22/board2_ocr/* 2>/dev/null'

echo "==== relay_ws 细分 ===="
$S $H 'sudo -n du -sh /home/keyuan22/relay_ws/* 2>/dev/null; echo "--- src ---"; find /home/keyuan22/relay_ws/src -maxdepth 3 -type f | head -20'

echo "==== pharmacy_pkg install 细分 ===="
$S $H 'sudo -n du -sh /opt/eprobot_ws/install/pharmacy_pkg/* 2>/dev/null'

echo "==== /opt/eprobot_ws/src 顶层 ===="
$S $H 'ls /opt/eprobot_ws/src/; echo "--- 各包体积 ---"; sudo -n du -sh /opt/eprobot_ws/src/* 2>/dev/null'

echo "==== /usr/local/bin 清单 ===="
$S $H 'ls -l /usr/local/bin/ | head -30'

echo "==== 关键单文件大小 ===="
$S $H 'ls -lh /opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/* 2>/dev/null | head -20; echo ---; ls -lh /home/keyuan22/maps/ 2>/dev/null'
