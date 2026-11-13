# ===== 小车 ROS 环境变量（WSL 端）=====
# 自动探测 WSL 在 10.211.121.x 网段的 IP，作为 ROS_IP
_robot_ip=10.211.121.22
_my_ip=$(ip -4 -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep '^10\.211\.121\.' | head -1)
[ -z "$_my_ip" ] && _my_ip=$(ip -4 -o addr show 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | grep -v '^127\.' | grep -v '^198\.18\.' | head -1)

# iscc 从 ~/.config/iscc/iscc.conf 读取车 IP/账号，这里不再覆盖
# export ROBOT_IP=$_robot_ip
# export ROBOT_USER=EPRobot
export ROS_MASTER_URI="http://${_robot_ip}:11311"
export ROS_IP="$_my_ip"
export ROS_HOSTNAME="$_my_ip"
export ROBOT_TYPE=EPRobotV2.3
unset _my_ip _robot_ip

source /opt/ros/noetic/setup.bash
[ -f "$HOME/robot_ws/devel/setup.bash" ] && source "$HOME/robot_ws/devel/setup.bash"

# rviz/tools on WSL must resolve the robot hostname used by roslaunch URIs.
export HOSTALIASES="$HOME/.hostaliases"
