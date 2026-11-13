# car22 档案（10.211.121.22 / EPRobot2）

> 这台是**当前在跑的车**。本目录是它的"可恢复镜像"。
> 详细原理见 [`../../docs/竞赛笔记.md`](../../docs/竞赛笔记.md)；部署步骤见 [`../../docs/新车部署手册.md`](../../docs/新车部署手册.md)。

**原理索引（本文件 ↔ 笔记章节）**

| 本文件的节 | 想搞懂背景，去读 |
|---|---|
| §1 身份卡 / §2 路径对照 | [`竞赛笔记.md` §2 认车](../../docs/竞赛笔记.md)、[`§19.1` 两车对照](../../docs/竞赛笔记.md) |
| §3 服务表（15 unit） | [`§6.1` systemd 才是启动器](../../docs/竞赛笔记.md)；`docs/unit依赖关系.md`（待建） |
| §4 相机链 | [`§6.5` 相机链](../../docs/竞赛笔记.md)（六坑全在这） |
| §5 关键参数 | [`§6.4` Nav2 参数](../../docs/竞赛笔记.md)、[`§22` 调参决策表](../../docs/竞赛笔记.md) |
| §6 话题与节点 | [`§4.2` 七个概念](../../docs/竞赛笔记.md) |
| §7 起车/收车 | [`§12` 一天清单](../../docs/竞赛笔记.md) |
| §8 已知问题 | [`§17.3` 未解决清单](../../docs/竞赛笔记.md) |

---

## 1. 身份卡

| 项 | 值 |
|---|---|
| IP / 网段 | `10.211.121.22/24`，网关 `10.211.121.1` |
| 主机名 | `EPRobot2` |
| 账号 / sudo | `keyuan22` / 免密（`sudo -n`） |
| 系统 | Ubuntu 26.04.1 LTS（aarch64） |
| ROS | ROS 2 **Lyrical**，`/opt/ros/lyrical` |
| 工作空间 | `/opt/eprobot_ws`（install 已就绪） |
| 家目录 | `/home/keyuan22`（另有软链 `/home/ubuntu` → 这里） |
| 网络模式 | **STA**：连外部热点 `OnePlusAce5`（静态 IP） |
| 额外网卡 | `tunx 10.7.7.2`（VPN 隧道，见竞赛笔记 §18.5） |
| 相机 | **Astra S**（`2bc5:0402`，USB2.0，**无 UVC**，走 Orbbec OpenNI2） |
| 雷达 | LSLidar（`lslidar` unit，`/scan` 10 Hz） |
| IMU | WHEELTEC **H30**（CH343 `1a86:55d4`，SN `5C98182597`，`/dev/EPRobot_imu` → `ttyACM0`，**460800**） |
| 底盘 | EPRobotV2.3（阿克曼），`eprobot_base_cpp` |
| 裁判 ID | `25`（`/etc/default/eprobot-pharmacy` 覆盖 unit 里的 24） |

---

## 2. 目录 → 车上目标路径对照

`rootfs/` 下的相对路径 = 车上绝对路径，**可以直接按路径覆盖**。

| 本仓库 | 车上 |
|---|---|
| `rootfs/opt/eprobot_ws/install/pharmacy_pkg/` | `/opt/eprobot_ws/install/pharmacy_pkg/` |
| `rootfs/opt/eprobot_ws/install/eprobot_base_cpp/` | `/opt/eprobot_ws/install/eprobot_base_cpp/`（**实际在跑的 C++ 底盘驱动**，源码缺失） |
| `rootfs/opt/oni2-orbbec/` | `/opt/oni2-orbbec/` |
| `rootfs/home/keyuan22/eprobot_navigation/` | `/home/keyuan22/eprobot_navigation/` |
| `rootfs/home/keyuan22/camera_shim/` | `/home/keyuan22/camera_shim/` |
| `rootfs/home/keyuan22/board2_ocr/` | `/home/keyuan22/board2_ocr/` |
| `rootfs/home/keyuan22/nav_tune_web/` | `/home/keyuan22/nav_tune_web/` |
| `rootfs/home/keyuan22/maps/` | `/home/keyuan22/maps/` |
| `rootfs/etc/systemd/system/*.service` | `/etc/systemd/system/` |
| `rootfs/etc/default/eprobot-pharmacy` | `/etc/default/eprobot-pharmacy` |
| `rootfs/etc/netplan/*.yaml` | `/etc/netplan/` |
| `rootfs/etc/udev/rules.d/*.rules` | `/etc/udev/rules.d/` |
| `rootfs/etc/chrony/` | `/etc/chrony/`（`chrony.keys` 未入库） |
| `rootfs/usr/local/bin/*` | `/usr/local/bin/` |
| `src/opt_eprobot_ws_src/*` | `/opt/eprobot_ws/src/`（**要 build**） |
| `src/relay_ws/mono8_relay/` | `/home/keyuan22/relay_ws/src/mono8_relay/`（**要 build**） |

> ⚠️ **两个软链要手动建**（Windows/git 存不了软链）：
> ```bash
> cd /opt/oni2-orbbec && ln -sf libOpenNI2.so libOpenNI2.so.0 && ln -sf libOpenNI2.so libOpenNI2.so.0.0
> ```

---

## 3. 服务表（15 个 unit）

| unit | 作用 | 现在 |
|---|---|---|
| `eprobot-base` | 底盘驱动 → `/odom` `/battery_state` `/cmd_vel` | **running** |
| `eprobot-imu` | H30 → `/imu/data` | **running** |
| `lslidar` | 雷达 → `/scan` | disabled（`iscc pre` 会 start） |
| `eprobot-nav` | Nav2（`nav2_bringup.launch.py`） | disabled（`iscc pre` 会 restart） |
| `eprobot-pharmacy` | 识别 + 语音 + 裁判（`competition.launch.py`） | disabled（`iscc pre` 会 start） |
| `openni2-camera` | 相机取流 → `/camera/color/image_raw` | **running** |
| `mono8-relay` | C++ 转灰度 → `/camera/rgb/image_raw` | **running** |
| `scan-viz` | `/scan` 3 Hz 副本（给远程 RViz） | **running** |
| `nav-tune-web` | 网页调参（8766） | disabled |
| `eprobot-slam` / `eprobot-carto` | 建图（与 nav 冲突） | disabled |
| `image-relay` | 旧 Python relay | disabled（被 mono8-relay 取代） |
| `openni2-mono8` | 旧方案 | disabled |
| `orbbec-astra-s` / `camera-shim` | 厂商方案 / 合成图 | disabled |

**全部 unit 都带**：`ROS_DOMAIN_ID=1`、`FASTDDS_BUILTIN_TRANSPORTS=UDPv4`。

---

## 4. 相机链（最容易坏的一环）

```
Astra S ──Orbbec OpenNI2──► openni2-camera
                              └► /camera/color/image_raw   (rgb8 640x480, 921600 B)
                                   └► mono8-relay (C++, max_fps 10)
                                        └► /camera/rgb/image_raw  (mono8 640x480, 307200 B, ~7.6 Hz)
                                             ├► /detect_qrcode      (写死要 mono8)
                                             └► /pharmacy_board2(_ocr)
```

**三条铁律**
1. **Astra S 没有 `/dev/video0`**，任何 `v4l2_camera` / `camera.launch.py` 都无效。
2. **不要加 `-p color_mode:=VGA_15Hz`**（会让每帧损坏：`Image buffer is corrupt. Size is 371790 != 921600`）。
3. **QR 节点写死 `mono8` + 话题名 `/camera/rgb/image_raw`**；上游发 rgb8 会"不报错但识别不出来"。

---

## 5. 关键参数（改之前先读竞赛笔记 §22）

### 5.1 任务层 `pharmacy_pkg/share/pharmacy_pkg/config/pharmacy.yaml`

| 参数 | 值 | 说明 |
|---|---|---|
| `judge_tcp.host` / `port` | `10.211.121.38` / `8888` | ⚠️ **与实际裁判机可能不符**，现场要改（本机是 `.222`） |
| `judge_tcp.car_id` | `25` | |
| `nav_pharmacy.max_rounds` / `max_samples` | 3 / 8 | 比赛上限 |
| `nav_pharmacy.match_seconds` | **1800.0** | 30 分钟安全帽；**设 0 = 连续练习模式**（轮次/样本限制失效） |
| `qr_timeout` / `board2_timeout` | 5.0 / 8.0 s | |
| `pickup_seconds` / `delivery_seconds` | 1.5 / 1.5 s | 规则要求"进框停 1~2 s" |
| `detect_qrcode.scan_hz` | 5.0 | |
| `pharmacy_board2.scan_period` / `need` | 0.03 / 2 | |
| `pharmacy_speech.executable` / `device` | `/usr/bin/aplay` / `plughw:0,0` | headless，无 PulseAudio |

### 5.2 航点 `config/mission_waypoints.yaml`（**必须现场重标**）

| 点 | x | y | yaw |
|---|---|---|---|
| `home` | 0.0 | 0.0 | 0° |
| `board1` | 0.618 | 0.0 | 0° |
| `C` | 1.46 | 1.85 | +90° |
| `A` | 0.610 | 2.50 | +90° |
| `B` | 1.46 | 2.88 | +45° |
| `ac_transit` | 1.46 | 2.78 | +45° |
| `1` | -2.37 | 2.41 | −90° |
| `2` | -1.62 | 1.84 | −90° |
| `3` | -2.37 | 1.41 | −90° |
| `4` | -1.63 | 0.762 | −90° |
| `board2` | -0.903 | 3.76 | 180° |

> 🔴 **`ac_transit` 不能删**：它和 B 只差 1 cm，但就是 CBA 里"B 那一段"的执行点。删了任务会退化成 **C → A**。

### 5.3 Nav2 `eprobot_navigation/config/nav2_params.yaml`

| 项 | 值 |
|---|---|
| 局部规划 | **MPPI**：`vx_max 1.2` / `vx_min -1.0` / `wz_max 2.5` / `ax_max 1.1` / `ax_min -3.0` / `az_max 4.0` / `motion_model ackermann` / `min_turning_r 0.40` |
| 全局规划 | **Smac Hybrid** + Reeds-Shepp，`minimum_turning_radius 0.48`，`reverse_penalty 3.0` |
| 到点容差 | `fine 0.15 m` / `coarse 0.22 m` / `yaw 0.35 rad` |
| 进度判据 | `required_movement_radius 0.30 m` / `movement_time_allowance 10 s` |
| 代价地图 | 局部 3×3 m；分辨率 0.05；`inflation_radius 0.28`；footprint `0.30 × 0.22 m` |
| AMCL | `transform_tolerance 0.5`；`set_initial_pose: true` → `(-0.088, 0.083, 0)`；粒子 500–2000 |
| BT | `navigate_to_pose_no_spin.xml`（**无 spin**，阿克曼不能原地转） |
| 生命周期 | `autostart: true`、**`bond_timeout: 0.0`**（关掉 bond 监控） |

### 5.4 限速 `eprobot_navigation/scripts/goal_speed_limit.py`

```python
target_speeds      = {"C>B": 0.20, "A>B": 0.12, "B": 0.15, "A": 0.22}
target_stop_radius = {"A>B": 0.65, "B": 0.45, "A": 0.35}
slow_radius 0.9 / stop_radius 0.35 / slow_speed 0.2 / cruise_speed 1.2
```
键的回退顺序：`from>to` → `to` → 全局默认。

---

## 6. 话题与节点（`iscc pre` 之后应该有）

```
/odom /imu/data /battery_state /scan /scan_viz /tf /cmd_vel /diagnostics
/camera/color/image_raw  /camera/rgb/image_raw  /camera/rgb/camera_info
/map /amcl_pose /plan /cmd_vel
/pharmacy/{qr_report,board2_status,board2_control,mission_status,judge_task,judge_cv1,judge_cv2,car_speech,speech_status}
```

节点：`eprobot_base` `yesense_pub` `lslidar` `amcl` `planner_server` `controller_server` `behavior_server` `bt_navigator` `map_server` `lifecycle_manager_navigation` `goal_speed_limit` `goal_checker_bridge` `detect_qrcode` `pharmacy_board2_ocr` `pharmacy_speech` `judge_tcp` `nav_pharmacy`

---

## 7. 起车 / 收车

```bash
# 主机侧（WSL，iscc 已指向 .22）
iscc version          # 先确认 robot: keyuan22@10.211.121.22 / domain 1
iscc kill             # 全停 + 清 /dev/shm/fastdds_*
iscc pre              # 热车（车不动）：底盘→IMU→雷达→等 /odom→相机→restart nav→等 Nav2→等图像
iscc gray             # 确认相机有图（+/- 调曝光，s 存图，q 退）
iscc start            # ★ 车会动
iscc stop             # 只停任务
```

**验收六项**：`/odom` 50 Hz、`/scan` 10 Hz、`/imu/data` 有数、电池 ≥11 V、`/camera/rgb/image_raw` 7~10 Hz、journal 里有 `Managed nodes are active`。

---

## 8. 已知问题（交接必读）

| # | 问题 | 现状 |
|---|---|---|
| 1 | **B 点蹭墙**：45° 收尾右甩 ~0.14 m，余量仅 0.28 m | 用 `A>B 0.12 m/s` 缓解，未根治 |
| 2 | **A 点余量 0.244 m** < 车体半对角 0.186 m | 偶发 `Failed to make progress` → 倒车 |
| 3 | 裁判地址写 `.38`，实际裁判机常是 `.222` | **必然连不上**，现场必改 |
| 4 | `iscc pre` 用 `journalctl --since -5min` 判 nav 成功 | 上一轮旧日志会被误判 |
| 5 | 跨机 DDS 端点匹配不稳 | 远程 RViz 常空白，**判车况以车上为准** |
| 6 | `f1_mission_node` **无源码** | 只能改 YAML/限速/Nav2 参数 |
| 7 | OCR 运行时 `runtime_arm64` 未入库（276 MB） | 按 `requirements.txt` 重装 |
| 8 | **C++ 底盘驱动源码缺失**：`eprobot_base_cpp` 只有 6 个头文件 + 二进制，`.cpp` 全盘搜不到 | 改实现只能按 `src/.../eprobot_base/`（Python 参考实现）重写；参数在 `install/eprobot_base_cpp/.../base.yaml`（`axle_length 0.171` / `kp 500/100/0`） |
