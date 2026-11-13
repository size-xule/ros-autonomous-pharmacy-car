# WSL 快捷指令（主机侧全套）

> 这些脚本跑在 **Windows 里的 WSL**（`Ubuntu-20.04`），通过 SSH 远程操作小车。
> **车上没有这些命令。**

---

## 安装（一次性）

```bash
# 1) 依赖
sudo apt install -y sshpass

# 2) 放进 ~/bin
mkdir -p ~/bin
cp tools/wsl/car* tools/wsl/rviz-car tools/wsl/iscc21 ~/bin/
cp tools/wsl/ros_env.sh ~/
chmod +x ~/bin/*

# 3) 确保 ~/bin 在 PATH（多数发行版默认就有）
grep -q 'HOME/bin' ~/.profile || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.profile

# 4) SSH 别名（car* 全靠它）
cat >> ~/.ssh/config <<'EOF'
Host robot
    HostName 10.211.121.22
    User keyuan22
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    ServerAliveInterval 30
    ServerAliveCountMax 6
EOF
chmod 600 ~/.ssh/config

# 5) 验证
car 'hostname'      # 期望 EPRobot2
iscc version        # 期望 robot: keyuan22@10.211.121.22 / domain 1
```

---

## 指令清单（**按 ROS 版本分类，别用错**）

### A. 给 `.22`（ROS 2 Lyrical）用 —— **推荐**

| 命令 | 作用 | 车会动 |
|---|---|---|
| `iscc version` | 打印目标车/domain/地图目录 | 不动 |
| `iscc pre` | 热车（底盘→IMU→雷达→等 `/odom`→相机→restart nav→等 Nav2） | **不动** |
| `iscc start` | 跑任务 | **★ 会动** |
| `iscc stop` | 只停任务 | 停车 |
| `iscc kill` | 全停 + 清 `/dev/shm/fastdds_*` | 停车 |
| `iscc status` / `logs` / `gray` / `camtune` / `costmap` / `ros` / `rviz2` | 诊断与可视化 | 不动 |

> `iscc` 本体在 `tools/host-iscc/iscc`（28 KB），配置模板 `tools/host-iscc/iscc.conf.example`。
> 本目录的 `iscc` 只是它的软链习惯，不用重复放。

### B. 给 `.21`（另一台 ROS 2 车）用

| 命令 | 作用 |
|---|---|
| `iscc21` | 把 `ROBOT_IP` 强制指向 `10.211.121.21`，并加载 `~/iscc-car21/iscc.conf`，再调用独立 bundle `~/iscc-car21/20261026/scripts/iscc` |

> 设计意图：`~/ros_env.sh` 会在每个交互 shell 里 `export ROBOT_IP`，如果不 unset，`iscc21` 会**静默连到 `.22`**。
> 这个脚本开头就是 `unset ROBOT_IP ROBOT_USER ROBOT_PASS ...`，别删。

### C. ⚠️ **ROS 1（`.24`）时代的遗留** —— 对 `.22` 无效

| 命令 | 原本作用 | 为什么对 `.22` 无效 |
|---|---|---|
| `car` | `ssh robot` | 能用，但只会给你一个 shell（不算"操作"） |
| `car-start-nav` | 起 cartographer 导航 | 里面写死 `source /opt/ros/melodic` + `carto_ws` |
| `car-start-astra` | 起 Astra 相机 | 走的是 ROS 1 `astra_launch`，`.22` 用 systemd `openni2-camera` |
| `car-start-competition` | 起识别+裁判 | ROS 1 的 `competition.launch` |
| `car-stop` | `pkill -f "roslaunch ..."` | `.22` 是 systemd 管的，`pkill` 没用（会被 `Restart=` 拉起来） |
| `car-bag` / `car-bags` / `car-serial` | 录 ROS 1 bag + 抓串口 | 依赖车上的 `~/car_bag.sh` 与 ROS 1 环境 |
| `car-logs` | `tail -f /tmp/<name>.txt` | `.22` 的日志在 systemd journal 里（用 `iscc logs`），不是 `/tmp/*.txt` |
| `rviz-car` | source `ros_env.sh` 后开 rviz | `ros_env.sh` 里是 `noetic`；`.22` 要用 `iscc rviz2` |

**结论**：`.22` 的日常只用 **`iscc`**；`car*` 这一组留着是因为 `.24` 车（ROS 1）还在，将来若复活可以直接用。

---

## `ros_env.sh` 的两个陷阱

```bash
_robot_ip=10.211.121.22        # ← 指向 .22
export ROS_MASTER_URI="http://${_robot_ip}:11311"   # ← 但 ROS 2 没有 master！
source /opt/ros/noetic/setup.bash                    # ← ROS 1 的 setup
```

1. **ROS 2 没有 `ROS_MASTER_URI`**，这行对 `.22` 无意义，但**不会报错**，容易让人以为"环境已经配好了"。
2. 它 `source` 的是 **noetic**（ROS 1）。在 `.22` 上做 ROS 2 操作，必须自己 `source /opt/ros/lyrical/setup.bash`。

> 保留它是为了：`.24` 车复活时 `rviz-car` 还能用；以及 `ROS_IP` 的自动探测逻辑（多网卡时有用）。

---

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `car: ssh: Could not resolve hostname robot` | 没配 `~/.ssh/config` 的 `Host robot` | 见"安装 第 4 步" |
| `iscc` 连到错的车 | `~/.bashrc` 里有 `export ROBOT_IP=` 覆盖了配置 | `echo $ROBOT_IP`；删掉那行 |
| `iscc` 报 `command not found` | `~/bin` 不在 PATH，或装到了 `/root/.local` | `echo $PATH`；重装到 `/opt/iscc` |
| `iscc start` 说 nav 不 active | 没 `pre` 或 domain 不一致 | `iscc version` 看 `domain:`；`iscc pre` |
| `iscc21` 连到 `.22` | 有人删了开头的 `unset` | 恢复那行 |
| `car-bag` 卡住 | 车上 `~/car_bag.sh` 不存在或 ROS 1 没起 | `.22` 用 `iscc` 的日志，不要用它 |
