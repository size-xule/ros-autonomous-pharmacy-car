# 主机侧 `iscc` 工具箱（WSL Ubuntu-20.04）

`iscc` 是**跑在你电脑的 WSL 里**、通过 SSH 远程操作小车的 bash 脚本。**车上没有这个命令。**

## 安装

```bash
# 1) 依赖
sudo apt install -y sshpass

# 2) 放脚本
sudo mkdir -p /opt/iscc/scripts
sudo cp iscc /opt/iscc/scripts/iscc
sudo chmod 755 /opt/iscc/scripts/iscc
sudo ln -sf /opt/iscc/scripts/iscc /usr/local/bin/iscc

# 3) 配置（不要用本仓库里的占位密码）
mkdir -p ~/.config/iscc
cp iscc.conf.example ~/.config/iscc/iscc.conf
chmod 600 ~/.config/iscc/iscc.conf
${EDITOR:-nano} ~/.config/iscc/iscc.conf     # 填 ROBOT_PASS

# 4) 验证
iscc version
#   期望：robot: keyuan22@10.211.121.22 / car_id: 25 / domain: 1 / distro: lyrical
```

> **`iscc.conf` 永不入库**（`.gitignore` 已挡）。本仓库只放 `iscc.conf.example`。

## 子命令

| 命令 | 作用 | 车会不会动 |
|---|---|---|
| `iscc version` | 打印配置与目标车 | 不动 |
| `iscc status` | 服务 + 节点 + 图像发布/订阅 + IMU 源 | 不动 |
| `iscc pre` | 热车：底盘→IMU→雷达→等 `/odom`→相机→restart nav→等 Nav2/图像 | **不动** |
| `iscc start` | `ros2 launch pharmacy_pkg mission.launch.py` | **★ 会动** |
| `iscc stop` | 只停任务（Nav2/雷达/底盘保留） | 停车 |
| `iscc kill` | 全停 + 清 `/dev/shm/fastdds_*` | 停车 |
| `iscc clear` | 只扫残留（僵尸 ros2 CLI / daemon / 陈旧 shm） | 不动 |
| `iscc logs` | 跟 `journalctl` | 不动 |
| `iscc gray` | 灰度实时画面（`+`/`-` 调曝光、`s` 存图、`q` 退） | 不动 |
| `iscc camtune` | 曝光扫描 | 不动 |
| `iscc costmap [--global\|--local]` | 清 Nav2 代价地图 | 不动 |
| `iscc ros [--dot]` | 导出节点/话题图 | 不动 |
| `iscc rviz2` / `iscc rviz` | 开 RViz（ROS 2 / ROS 1） | 不动 |
| `iscc create` / `iscc save [名]` | SLAM 建图 / 存地图 | 建图时手推车 |
| `iscc shell` | 交互式登录车上 | 不动 |

## 配置优先级

**环境变量 > `~/.config/iscc/iscc.conf` > 脚本内默认值**

```bash
# 临时指向另一台车
ROBOT_IP=10.211.121.30 iscc version
```

## 四个常见坑

1. **`~/.bashrc` 里的 `export ROBOT_IP=` 会覆盖配置文件** → `echo $ROBOT_IP` 自查。
2. **脚本里 `ROS_DOMAIN_ID` 默认 0，车上 unit 是 1** → 必须靠配置或环境变量对齐，`iscc version` 那行 `domain:` 要确认。
3. **`iscc pre` 用 `journalctl --since -5min` 判 Nav2 成功** → 上一轮旧日志会被误判，保守做法是先 `iscc kill`。
4. **`pre` 结束时的 Ctrl-C 只是停止看日志**，车还在跑；停车用 `iscc stop` / `iscc kill`。
