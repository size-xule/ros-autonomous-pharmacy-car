# probe3.sh · 预期输出

**用途**：查**雷达链路**（`/scan` 有无、`lslidar` unit 状态、设备节点）+ **网段里谁在线**。

| 项 | 说明 |
|---|---|
| 只读 | ✅ 只 `ros2 topic info/hz`、`systemctl is-active`、TCP 探测 |
| 前置 | `export ROBOT_PASS=...` |
| 注意 | 最后两段（可达性/arp）跑在**主机侧**，不是车上 |

---

## 正常输出（节选）

```
==== ros2 node list ====
/amcl
/controller_server
/eprobot_base
/goal_checker_bridge
/goal_speed_limit
/lslidar
/map_server
/planner_server
/scan_viz
/yesense_pub

==== /scan info + hz ====
Publisher count: 1
Node name: lslidar
Endpoint type: PUBLISHER
average rate: 10.03
	min: 0.098s max: 0.104s std dev: 0.001s window: 10

==== lslidar unit state ====
active
disabled
ls: cannot access '/dev/EPRobot_laser': No such file or directory
crw-rw-rw- 1 root dialout 188, 0 ... /dev/ttyUSB0

==== .24 / .21 可达性 (from WSL) ====
10.211.121.24:22 closed/unreachable
10.211.121.21:22 closed/unreachable
10.211.121.38:22 closed/unreachable

==== arp ====
10.211.121.1 dev wlan0 lladdr ... REACHABLE
10.211.121.22 dev wlan0 lladdr ... REACHABLE
```

**判据**

| 指标 | 正常 | 说明 |
|---|---|---|
| `/lslidar` 节点 | 存在 | 不存在 → 雷达没起 |
| `/scan` Publisher count | **1** | **2 就是双实例**（典型：手工又起了一遍驱动） |
| `/scan` hz | **~10 Hz** | 0 → 电机没转 / 串口打不开 |
| `lslidar` is-active | `active`（跑的时候）/ `inactive`（平时） | 平时 `inactive` 是正常的 |
| `is-enabled` | **`disabled`** | 这是设计如此（`iscc pre` 才 start） |
| `.21` / `.24` 可达性 | `unreachable` | 它们不在线是**正常**的（`.21` 无卡、`.24` 已退役） |

> ⚠️ **`/dev/EPRobot_laser` 不存在是正常的**——本车雷达是 **USB 串口**（`/dev/ttyUSB0`），
> 不走 `EPRobot_laser` 这个别名（那是别的车型的约定）。

---

## 典型故障 1：`/scan` 有话题但 hz 为 0

```
==== /scan info + hz ====
Publisher count: 1
Node name: lslidar
（hz 段无输出）
```

| 原因 | 排查 |
|---|---|
| 雷达电机没转（`lslidar-ctl` 只起了节点没启动电机） | `/usr/local/bin/lslidar-ctl status`；`lslidar-ctl start` |
| 串口权限 / 被占 | `ls -l /dev/ttyUSB*`；`fuser -v /dev/ttyUSB0` |
| 供电不足（雷达单独 5V） | 摸雷达是否转；换 USB 口 |
| 波特率不对 | `journalctl -u lslidar -n 50` 里找 `baud`/`open failed` |

## 典型故障 2：`Publisher count: 2`

```
Publisher count: 2
Node name: lslidar
Node name: lslidar
```
→ **两个驱动同时在发 `/scan`**。表现是 RViz 里激光"抖成两层"、Nav2 定位跳。
修：
```bash
pgrep -af lslidar          # 看有几个
sudo systemctl stop lslidar
pkill -f lslidar_driver_node
sudo systemctl start lslidar
```

## 典型故障 3：`.22` 也 unreachable

```
10.211.121.22:22 closed/unreachable
```
→ 主机不在车网段（看 `ip -4 addr`），或车没连上热点。**先修网络再谈数据。**

---

## 为什么 `.24` 会出现在探测列表里

脚本里硬编码了 `.24`（历史 ROS 1 车）。它已退役，`unreachable` 是预期结果。
新环境想改探测目标就改脚本末尾的 `for ip in ...`。
