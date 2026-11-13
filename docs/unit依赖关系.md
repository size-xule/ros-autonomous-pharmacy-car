# unit 依赖关系

> 15 个 systemd unit 的**启动顺序、依赖关系、失败表现**。
> 数据来源：`cars/car22/rootfs/etc/systemd/system/*.service` 原文（2026-11-13 逐文件读取）。
> **改 unit 前先看本文 §5 的三条铁律**——顺序错了整栈起不来，而且报错和真正原因差很远。

---

## 1. 总表（15 个 unit）

| unit | 作用 | 关键进程 | After / Wants | Restart | 现状 |
|---|---|---|---|---|---|
| **`eprobot-base`** | 底盘驱动（C++）→ `/odom` `/cmd_vel` `/battery_state` | `ros2 launch eprobot_base_cpp base.launch.py` | `network-online` | on-failure / 2s | **running** |
| **`eprobot-imu`** | H30 IMU → `/imu/data` | `ros2 launch yesense_std_ros2 …` | `network-online`, **`eprobot-base`** | on-failure / 2s | **running** |
| **`lslidar`** | 雷达 → `/scan` | `/usr/local/bin/lslidar-ctl start` | **`eprobot-base`** | **no** | disabled |
| **`eprobot-nav`** | Nav2（AMCL + 静态地图） | `nav2_bringup.launch.py` | **`base` + `imu` + `lslidar`** | **no** | disabled |
| **`eprobot-pharmacy`** | 识别 + 语音 + 裁判 | `competition.launch.py start_camera:=false` | **`base` + `imu`** | **no** | disabled |
| **`openni2-camera`** | Astra S 取流（Orbbec OpenNI2）→ `/camera/color/image_raw` | `/usr/local/bin/openni2-camera` | `network-online`；`Before=eprobot-pharmacy` | on-failure / 3s | **running** |
| **`mono8-relay`** | 彩色→灰度（C++）→ `/camera/rgb/image_raw` | `mono8_relay --max_fps 10` | **`openni2-camera`** | on-failure / 2s | **running** |
| **`scan-viz`** | `/scan` 的 3 Hz 副本（给远程 RViz） | `iscc_scan_viz.py` | `base` + `lslidar` | on-failure / 2s | **running** |
| **`nav-tune-web`** | 网页调参 `0.0.0.0:8766` | `nav_tune_web.py` | `network-online` | on-failure / 2s | disabled |
| **`eprobot-slam`** | SLAM Toolbox 建图 | `slam_mapping.launch.py` | `base` + `imu` + `lslidar` | **no** | disabled |
| **`eprobot-carto`** | Cartographer 2D 建图 | `cartographer_mapping.launch.py` | `base` + `lslidar` | **no** | disabled |
| `camera-shim` | 合成灰度图（**不是真相机**） | `camera_shim.py` | `network-online` | on-failure / 3s | disabled |
| `image-relay` | 旧 Python 灰度中继（已废弃） | `image_relay.py` | `orbbec-camera` ⚠️ | on-failure / 3s | disabled |
| `openni2-mono8` | 旧方案（OpenNI2 直出 mono8） | `/usr/local/bin/openni2-mono8` | `openni2-camera` | on-failure / 3s | disabled |
| `orbbec-astra-s` | 厂商 SDK 方案（ROS 1 风格） | `orbbec_astra_s_node` | `network-online` | **always** / 3s | disabled |

---

## 2. 启动顺序图

```mermaid
flowchart TD
  NET[network-online.target]

  subgraph 核心三件套
    BASE[eprobot-base<br/>/odom /cmd_vel]
    IMU[eprobot-imu<br/>/imu/data]
    LIDAR[lslidar<br/>/scan]
  end

  subgraph 相机链
    CAM[openni2-camera<br/>/camera/color/image_raw]
    RELAY[mono8-relay<br/>/camera/rgb/image_raw]
  end

  NAV[eprobot-nav<br/>Nav2 + AMCL]
  PHARM[eprobot-pharmacy<br/>QR/板二/语音/裁判]
  VIZ[scan-viz]
  TUNE[nav-tune-web]

  subgraph 建图（与 nav 互斥）
    SLAM[eprobot-slam]
    CARTO[eprobot-carto]
  end

  NET --> BASE
  NET --> CAM
  BASE --> IMU
  BASE --> LIDAR
  BASE --> NAV
  IMU --> NAV
  LIDAR --> NAV
  BASE --> PHARM
  IMU --> PHARM
  CAM --> RELAY
  CAM -.Before.-> PHARM
  BASE --> VIZ
  LIDAR --> VIZ
  LIDAR --> SLAM
  IMU --> SLAM
  LIDAR --> CARTO
  BASE --> SLAM
  BASE --> CARTO
  NET --> TUNE
```

**读图要点**
1. **`eprobot-base` 是根**——它不起，`imu`/`lslidar`/`nav`/`pharmacy`/`scan-viz` 全都不满足 `After=`。
2. **`eprobot-nav` 同时等三样**：`base`（`/odom`）、`imu`、`lslidar`。缺一个就起不来。
3. **相机链是串的**：`openni2-camera` → `mono8-relay`。relay 起了但相机没起来 = 有进程、没图像。
4. `eprobot-pharmacy` 只等 `base` + `imu`，**不等相机**——所以相机没好时它照样起，然后 QR 一直 `candidates=0`。

---

## 3. 谁挂了 → 你会看到什么

| 挂掉的 unit | 现象 | 第一条要跑的命令 |
|---|---|---|
| `eprobot-base` | 没有 `/odom`；`iscc pre` 卡在 "waiting for /odom"；RViz 无车模 | `systemctl status eprobot-base`；`fuser -v /dev/EPRobot_base` |
| `eprobot-imu` | `/imu/data` 没数据；Nav2 仍能起（AMCL 只用 `/scan` + `/odom`），但**建图会歪** | `ls -l /dev/EPRobot_imu`（udev 没匹配？见 udev README） |
| `lslidar` | 没有 `/scan`；Nav2 起不来（`global_costmap` 等 laser）；`iscc pre` 报 nav inactive | `systemctl status lslidar`；`/usr/local/bin/lslidar-ctl status` |
| `eprobot-nav` | 没有 `/map` `/amcl_pose`；`iscc start` 卡住；`mission_waypoints` 不生效 | `journalctl -u eprobot-nav -n 100`；找 `Managed nodes are active` |
| `eprobot-pharmacy` | 没有 QR/板二/语音/裁判；`/detection_control` 无订阅者 | `journalctl -u eprobot-pharmacy -n 100`；看 `Judge TCP connected` |
| `openni2-camera` | `/camera/color/image_raw` 无帧；relay 空转；`iscc gray` 黑屏 | `journalctl -u openni2-camera`；`lsusb \| grep 2bc5`；`pkill -f orbbec_as` |
| `mono8-relay` | 有 `/camera/color/image_raw` 但无 `/camera/rgb/image_raw` → **QR 与板二全哑** | `systemctl status mono8-relay`；`ros2 topic hz /camera/color/image_raw` |
| `scan-viz` | 只有**远程 RViz** 看不到激光；车上一切正常 | `systemctl status scan-viz`（可以不修，不影响跑） |
| `nav-tune-web` | 8766 打不开 | 只影响调参，不影响比赛 |

---

## 4. 启停顺序（`iscc` 已经按这个来，手工操作时照抄）

### 4.1 冷启动

```bash
sudo systemctl start eprobot-base eprobot-imu lslidar
# 等 /odom 有帧（最多 12 × 12 s）
ros2 topic echo --once /odom
sudo systemctl start openni2-camera mono8-relay
sudo systemctl restart eprobot-nav        # ★ 必须在 /odom 之后
sudo systemctl start eprobot-pharmacy
```

### 4.2 停车

```bash
sudo systemctl stop eprobot-pharmacy      # 先停任务层
sudo systemctl stop eprobot-nav
sudo systemctl stop mono8-relay openni2-camera
# 底盘与 IMU 可留（RViz 还能看）
```

### 4.3 为什么 `iscc kill` 要"先杀进程再 stop"

`eprobot-base` / `eprobot-imu` / `openni2-camera` / `mono8-relay` / `scan-viz` 都是 `Restart=on-failure`。
如果只 `systemctl stop`，某些异常退出码会触发**自动重启**，于是又建一个 FastDDS 共享内存段。
`iscc kill` 的做法是：`pkill` 进程 → `systemctl stop` → 清 `/dev/shm/fastdds_*`。

> `eprobot-nav` / `eprobot-pharmacy` / `lslidar` / `eprobot-slam` / `eprobot-carto` 是 **`Restart=no`**，
> 停就是停，不会自己回来。

---

## 5. 三条铁律（违反必翻车）

| # | 铁律 | 违反的后果 |
|---|---|---|
| 1 | **`eprobot-nav` 必须在 `/odom` 有帧之后才 start/restart** | `global_costmap` 拿不到 `odom→base_link` → `Failed to bring up all requested nodes` → 整栈白起；日志看不出真正原因 |
| 2 | **`mono8-relay` 必须在 `openni2-camera` 之后**（`After=` 已保证，手工起时注意） | relay 订阅不到上游 → 空转；`/camera/rgb/image_raw` 无帧 |
| 3 | **`eprobot-pharmacy` 必须在 `mono8-relay` 之后**（unit 里只有 `Before=` 单向约束） | QR/板二 收不到 mono8 → `QR scan: candidates=0`、板二一直 `UNKNOWN` |

> 第 3 条是 unit 里**没有强制**的（`eprobot-pharmacy` 只等 `base`+`imu`）。
> `iscc pre` 靠脚本顺序绕过了这个问题；**手工起的时候要自己保证**。

---

## 6. 已知怪点（都验证过，不是笔误）

| 怪点 | 事实 | 影响 |
|---|---|---|
| `image-relay` 的 `Wants=orbbec-camera.service` | **该 unit 不存在**（只有 `orbbec-astra-s`） | 无害（systemd 忽略缺失的 Wants），但 `systemctl status` 会有告警；反正它是 disabled |
| `eprobot-pharmacy` 的 `Environment=JUDGE_CAR_ID=24` | 被 `EnvironmentFile=/etc/default/eprobot-pharmacy` 的 `JUDGE_CAR_ID=25` **覆盖** | 实际用 25（正确）；**别只改 unit 里那个 24**，改 `/etc/default/` |
| 路径混用 `/home/ubuntu/...` 与 `/home/keyuan22/...` | `eprobot-slam`/`nav-tune-web` 用 `/home/ubuntu`（软链），`eprobot-nav` 用 `/home/keyuan22` | 因为有软链所以都能跑；**删软链会挂两个 unit** |
| `eprobot-carto` 存在但 cartographer 全栈没装 | 只有 `cartographer-ros-msgs` | 该 unit 一起就失败；反正 disabled |
| 所有 unit 都硬编码 `ROS_DOMAIN_ID=1` | 没有用 `EnvironmentFile` 统一 | 换车/多车要**逐个改 15 个文件**（见笔记 §18.4） |

---

## 7. 怎么自己查依赖

```bash
# 某 unit 依赖谁
systemctl list-dependencies --after eprobot-nav
systemctl list-dependencies --before eprobot-pharmacy

# 全部 unit 的启动耗时（排查"为什么起得慢"）
systemd-analyze blame | head -15

# 画一张依赖图（需要 graphviz）
systemd-analyze dot 'eprobot-*' | dot -Tsvg > /tmp/units.svg

# 校验 unit 语法（tools/selfcheck.sh 也会跑）
systemd-analyze verify /etc/systemd/system/eprobot-nav.service

# 看某个 unit 到底执行了什么
systemctl cat eprobot-base
systemctl show eprobot-base -p ExecStart -p Restart -p After
```

---

## 8. 改 unit 的规矩

1. **先备份**：`sudo cp -p /etc/systemd/system/x.service ~/x.service.bak_$(date +%s)`
2. 改完 `sudo systemd-analyze verify <file>` + `sudo systemctl daemon-reload`
3. **一次只改一个 unit**
4. 同步回仓库：`cars/car22/rootfs/etc/systemd/system/`（否则下次 `apply_to_car22.sh` 会盖回去）
5. 跑 `bash tools/selfcheck.sh`（第 3 项会校验 unit 段结构）
