# probe.sh · 预期输出

**用途**：一次摸清"这台车是什么状态"——身份 / ROS / 运行中的 unit / 关键配置 / 进程。**最常用，先跑这个。**

| 项 | 说明 |
|---|---|
| 只读 | ✅ 全程 `cat`/`ls`/`systemctl list`，不写任何东西 |
| 前置 | WSL 里 `export ROBOT_PASS=<密码>` + 装了 `sshpass` |
| 目标 | 固定 `keyuan22@10.211.121.22`（改车要改脚本里的 `H=`） |
| 耗时 | ~10 s |

---

## 正常输出（节选，2026-11-13 实测）

```
---- identity ----
keyuan22
EPRobot2
10.211.121.22/24
Ubuntu 26.04.1 LTS
aarch64
Thu Nov 13 21:34:02 CST 2026

---- ros ----
/opt/eprobot_ws/install
/opt/ros/lyrical

---- units ----
  eprobot-base.service    loaded active running ISCC_CAR ROS 2 chassis driver
  eprobot-imu.service     loaded active running ISCC_CAR WHEELTEC H30 IMU
  mono8-relay.service     loaded active running Convert Orbbec color to mono8 ...
  openni2-camera.service  loaded active running Orbbec Astra S via OpenNI2
  scan-viz.service        loaded active running Throttled /scan copy for remote RViz

---- judgecfg ----
JUDGE_CAR_ID=25

---- domain ----
/etc/systemd/system/eprobot-base.service:Environment=FASTDDS_BUILTIN_TRANSPORTS=UDPv4
/etc/systemd/system/eprobot-base.service:Environment=ROS_DOMAIN_ID=1
...
```

**判据**
- `identity` 里 **IP 与主机名必须对得上**（`.22` / `EPRobot2`）；对不上说明连错车。
- `units` 里**至少 5 个** running（base / imu / openni2-camera / mono8-relay / scan-viz）。
- `judgecfg` 的 `JUDGE_CAR_ID=` 是 **25**（不是 unit 里写的 24）。

---

## 典型故障 1：连不上车

```
---- identity ----
ssh: connect to host 10.211.121.22 port 22: No route to host
```

| 可能原因 | 排查 |
|---|---|
| 车没开机 / 没连上热点 | `ping 10.211.121.22` |
| 主机不在同一网段 | `ip -4 addr` 看是否 `10.211.121.x` |
| 密码没导 | `echo $ROBOT_PASS` |
| 车 IP 变了（换过 netplan） | 扫网段：`nmap -p22 10.211.121.0/24` 或 `for i in $(seq 1 254); do ...` |

## 典型故障 2：只有 1~2 个 unit 在跑

```
---- units ----
  eprobot-base.service    loaded active running ISCC_CAR ROS 2 chassis driver
```
→ `eprobot-imu` / 相机链 / `scan-viz` 都没起。这是**刚开机**的正常状态（unit 是 `disabled`，靠 `iscc pre` 拉起来），
也可能是 `iscc kill` 之后的正常状态。**不是故障**。
判据：`unitfiles` 段看 `enabled/disabled`——`eprobot-nav`、`lslidar`、`eprobot-pharmacy` 本来就该是 `disabled`。

## 典型故障 3：`ros` 段只有一行

```
---- ros ----
/opt/ros/lyrical
```
缺 `/opt/eprobot_ws/install` → 工作空间**没装好或被删**。此时任务层二进制可能也丢了，先跑 `verify.sh`。

---

## 看什么、下一步做什么

| 段 | 异常说明什么 | 下一步 |
|---|---|---|
| `identity` | 连错车 / 网络问题 | 停，先解决连接 |
| `units` | 该跑没跑 | `systemctl status <unit>` |
| `domain` | domain 不是 1 → 话题串台 | 改 unit 或环境变量 |
| `waypoints` | 坐标与 `cars/car22/` 里不一致 | 可能有人现场手改过，`diff` 一下 |
| `procs` | 有 `unattended-upgrade`/`dpkg` 在跑 | 等它跑完再测，否则 CPU 抢光 |
