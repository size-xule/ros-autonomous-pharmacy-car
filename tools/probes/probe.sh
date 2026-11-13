#!/usr/bin/env bash
# read-only probe of the ROS 2 car
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
S="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"

run() { echo "---- $1 ----"; $S $H "$2" 2>&1; }

run identity 'whoami; hostname; ip -4 -o addr show wlan0 | awk "{print \$4}"; . /etc/os-release; echo "$PRETTY_NAME"; uname -m; date'
run ros '/bin/ls -d /opt/ros/* /opt/eprobot_ws/install 2>/dev/null'
run units 'systemctl list-units --type=service --state=running --no-pager --no-legend | grep -Ei "eprobot|lslidar|nav|pharmacy|camera|openni|relay|shim|scan-viz" '
run unitfiles 'systemctl list-unit-files --no-pager --no-legend | grep -Ei "eprobot|lslidar|nav|pharmacy|camera|openni|relay|shim|scan-viz"'
run judgecfg 'cat /etc/default/eprobot-pharmacy 2>/dev/null'
run domain 'grep -r "ROS_DOMAIN_ID\|FASTDDS_BUILTIN_TRANSPORTS" /etc/systemd/system/*.service 2>/dev/null | head -40'
run waypoints 'cat /opt/eprobot_ws/install/pharmacy_pkg/share/pharmacy_pkg/config/mission_waypoints.yaml 2>/dev/null'
run pharmacycfg 'cat /opt/eprobot_ws/install/pharmacy_pkg/share/pharmacy_pkg/config/pharmacy.yaml 2>/dev/null'
run bins 'ls -l /opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/ 2>/dev/null'
run procs 'ps -eo pid,pcpu,comm,args --sort=-pcpu | head -20'
run battery_bag 'ls -lt ~/bags 2>/dev/null | head -5; ls -l ~/prematch_hiscore 2>/dev/null | head'
run gitstat 'cd ~/prematch_hiscore 2>/dev/null && git log --oneline -5 2>/dev/null'
