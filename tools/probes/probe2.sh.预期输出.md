# probe2.sh · 预期输出

**用途**：验证**数据面**——话题在不在、帧率对不对、电池够不够、DDS 共享内存有没有泄漏。

| 项 | 说明 |
|---|---|
| 只读 | ✅ 只 `ros2 topic list/hz/echo` + `ls`/`free` |
| 前置 | `export ROBOT_PASS=...`；**主机侧还要有 `iscc`**（脚本第一段调它） |
| 耗时 | ~40 s（`hz`/`echo` 都带 `timeout`） |

---

## 正常输出（节选，2026-11-13 实测）

```
==== iscc version (WSL side) ====
iscc 20261103-wsl
robot: keyuan22@10.211.121.22
car_id: 25
domain: 1
distro: lyrical
maps: /home/ubuntu/maps

==== ros2 topic list ====
/battery_state
/camera/color/image_raw
/camera/rgb/image_raw
/cmd_vel
/detect_qrcode
/imu/data
/odom
/scan
/tf
/tf_static
...

==== /camera/rgb/image_raw hz ====
average rate: 7.62
	min: 0.098s max: 0.152s std dev: 0.012s window: 8

==== /odom one msg ====
header:
  stamp: {sec: 1763..., nanosec: ...}
  frame_id: odom
child_frame_id: base_footprint
pose:
  pose:
    position: {x: ..., y: ..., z: 0.0}

==== battery ====
voltage: 12.01
percentage: 0.72

==== /dev/shm fastdds count ====
0
               total        used        free
Mem:            3792        1104        1533
/dev/root        29G   12G   16G   44% /
```

**判据**

| 指标 | 正常范围 | 不对说明 |
|---|---|---|
| `/camera/rgb/image_raw` | **7~10 Hz** | 0 → relay 没起 / 相机没出图；>10 → `max_fps` 被改 |
| `/odom` | 有消息（约 **50 Hz**） | 没消息 → `eprobot-base` 挂了 / 串口被占 |
| `battery.voltage` | **≥ 11.0**（比赛前 ≥ 11.5） | 低于 11 V 别跑，会出现莫名其妙的失败 |
| `fastdds count` | **0~个位数** | 两位数以上 → DDS 泄漏，`iscc kill` 清一遍 |
| `Mem used` | < 2.5 GB（共 3.8 GB） | 接近满 → 有进程泄漏 |

---

## 典型故障 1：话题列表是空的

```
==== ros2 topic list ====
（无输出）
```

| 原因 | 排查 |
|---|---|
| **`ROS_DOMAIN_ID` 不一致** | 脚本里已经 `export ROS_DOMAIN_ID=1`；若车上 unit 改成别的值就会空。`grep ROS_DOMAIN_ID /etc/systemd/system/*.service` |
| 一个 unit 都没起 | 先 `iscc pre` 或 `systemctl start eprobot-base` |
| Fast DDS SHM 冲突 | `ls /dev/shm \| grep fastdds`；`iscc kill` 后重试 |
| 时钟跳变 | `date` 与主机差 > 1 s → `chronyc tracking` |

> **注意**：`ros2 topic list` 在 Pi 上偶发 >20 s，脚本用 `timeout 20` 兜底，空输出**优先怀疑 domain**。

## 典型故障 2：有话题但 hz 是 0

```
==== /camera/rgb/image_raw hz ====
（无输出，或 "no new messages"）
```
→ 发布者在，但没有帧。按顺序查：
```bash
ros2 topic hz /camera/color/image_raw     # 上游有没有？
systemctl status mono8-relay openni2-camera
journalctl -u mono8-relay -n 30
```
上游有、下游无 → relay 的问题；上游也没 → 相机（`pkill -f orbbec_as` + `iscc-usb-reset`）。

## 典型故障 3：电池读数为 0 或字段缺

```
==== battery ====
（没有 voltage 字段 / 全 0）
```
→ `0x07`→`0x08` 帧不通。查 `eprobot-base` 日志；`fuser -v /dev/EPRobot_base` 看有没有双实例抢串口。

---

## 与 `iscc pre` 的关系

`probe2.sh` 只**看**，不**拉**。车刚开机时很多话题不存在是正常的——先 `iscc pre`，再跑本脚本对比。
