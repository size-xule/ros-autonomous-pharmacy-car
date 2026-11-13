#!/usr/bin/env bash
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
S="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8"

echo "==== ros2 node list ===="
$S $H 'source /opt/ros/lyrical/setup.bash >/dev/null 2>&1; source /opt/eprobot_ws/install/setup.bash >/dev/null 2>&1; export ROS_DOMAIN_ID=1 FASTDDS_BUILTIN_TRANSPORTS=UDPv4; timeout 20 ros2 node list 2>/dev/null | sort' 2>&1

echo "==== /scan info + hz ===="
$S $H 'source /opt/ros/lyrical/setup.bash >/dev/null 2>&1; export ROS_DOMAIN_ID=1 FASTDDS_BUILTIN_TRANSPORTS=UDPv4; timeout 12 ros2 topic info -v /scan 2>&1 | grep -E "Publisher count|Node name|Endpoint type" ; timeout 6 ros2 topic hz /scan 2>&1 | tail -2' 2>&1

echo "==== lslidar unit state ===="
$S $H 'systemctl is-active lslidar 2>&1; systemctl is-enabled lslidar 2>&1; ls -l /dev/EPRobot_laser /dev/ttyUSB* 2>&1' 2>&1

echo "==== .24 / .21 可达性 (from WSL) ===="
for ip in 10.211.121.24 10.211.121.21 10.211.121.38; do
  if timeout 3 bash -c "echo > /dev/tcp/$ip/22" 2>/dev/null; then echo "$ip:22 OPEN"; else echo "$ip:22 closed/unreachable"; fi
done

echo "==== arp ===="
ip neigh 2>/dev/null | head -10
