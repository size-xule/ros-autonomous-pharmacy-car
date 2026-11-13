#!/usr/bin/env bash
# read-only ROS 2 probe on the car (domain 1)
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
S="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"

echo "==== iscc version (WSL side) ===="
iscc version 2>&1 | head -20

echo "==== ros2 topic list ===="
$S $H 'source /opt/ros/lyrical/setup.bash >/dev/null 2>&1; source /opt/eprobot_ws/install/setup.bash >/dev/null 2>&1; export ROS_DOMAIN_ID=1 FASTDDS_BUILTIN_TRANSPORTS=UDPv4; timeout 20 ros2 topic list 2>/dev/null | sort' 2>&1

echo "==== /camera/rgb/image_raw hz ===="
$S $H 'source /opt/ros/lyrical/setup.bash >/dev/null 2>&1; source /opt/eprobot_ws/install/setup.bash >/dev/null 2>&1; export ROS_DOMAIN_ID=1 FASTDDS_BUILTIN_TRANSPORTS=UDPv4; timeout 8 ros2 topic hz --qos-reliability best_effort /camera/rgb/image_raw 2>&1 | tail -3' 2>&1

echo "==== /odom one msg ===="
$S $H 'source /opt/ros/lyrical/setup.bash >/dev/null 2>&1; source /opt/eprobot_ws/install/setup.bash >/dev/null 2>&1; export ROS_DOMAIN_ID=1 FASTDDS_BUILTIN_TRANSPORTS=UDPv4; timeout 10 ros2 topic echo --once --qos-reliability best_effort /odom 2>&1 | head -14' 2>&1

echo "==== battery ===="
$S $H 'source /opt/ros/lyrical/setup.bash >/dev/null 2>&1; source /opt/eprobot_ws/install/setup.bash >/dev/null 2>&1; export ROS_DOMAIN_ID=1 FASTDDS_BUILTIN_TRANSPORTS=UDPv4; timeout 10 ros2 topic echo --once --qos-reliability best_effort /battery_state 2>&1 | head -12' 2>&1

echo "==== /dev/shm fastdds count ===="
$S $H 'ls /dev/shm | grep -c fastdds; free -m | head -2; df -h / | tail -1' 2>&1
