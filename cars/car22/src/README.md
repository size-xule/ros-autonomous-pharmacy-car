# car22 / src —— 需要在新车上重新编译的源码

> 这里的东西**不能直接拷二进制**，必须在新车的 `/opt/eprobot_ws` 里 `colcon build`。
> 成品（已编译、可直接铺）在 [`../rootfs/opt/eprobot_ws/install/`](../rootfs/opt/eprobot_ws/install/)。
> 原理与踩坑见 [`../../../docs/竞赛笔记.md`](../../../docs/竞赛笔记.md)。

---

## 1. 包清单与用途

| 包 | 语言 | 作用 | 车上 unit | 原理章节 |
|---|---|---|---|---|
| [`opt_eprobot_ws_src/eprobot_base/`](opt_eprobot_ws_src/eprobot_base) | **Python / rclpy** | 底盘驱动**参考实现**（协议、运动学、IMU 信任、调度，含 7 个测试文件） | —（**未运行**，见下方 §3） | [§5.3](../../../docs/竞赛笔记.md) / [§5.4](../../../docs/竞赛笔记.md) |
| [`opt_eprobot_ws_src/lslidar_ros2/`](opt_eprobot_ws_src/lslidar_ros2) | C++ | 镭神雷达驱动 → `/scan` | `lslidar` | [§3.1](../../../docs/竞赛笔记.md) |
| [`opt_eprobot_ws_src/serial_ros2/`](opt_eprobot_ws_src/serial_ros2) | C++ | 串口库（`yesense_std_ros2` 依赖） | — | — |
| [`opt_eprobot_ws_src/yesense_interface/`](opt_eprobot_ws_src/yesense_interface) | C++ | Yesense IMU 消息定义 | — | [§21](../../../docs/竞赛笔记.md) |
| [`opt_eprobot_ws_src/yesense_std_ros2/`](opt_eprobot_ws_src/yesense_std_ros2) | C++ | H30 IMU 驱动 → `/imu/data` | `eprobot-imu` | [§21](../../../docs/竞赛笔记.md) |
| [`relay_ws/mono8_relay/`](relay_ws/mono8_relay) | C++ | 彩色 → 灰度中继（`/camera/color/image_raw` → `/camera/rgb/image_raw`） | `mono8-relay` | [§6.5](../../../docs/竞赛笔记.md) |

---

## 2. 编译

```bash
# 底盘/雷达/IMU（进 /opt/eprobot_ws）
cp -a cars/car22/src/opt_eprobot_ws_src/* /opt/eprobot_ws/src/
cd /opt/eprobot_ws
source /opt/ros/lyrical/setup.bash
colcon build --symlink-install

# 灰度中继（独立工作空间）
mkdir -p ~/relay_ws/src && cp -a cars/car22/src/relay_ws/mono8_relay ~/relay_ws/src/
cd ~/relay_ws && source /opt/ros/lyrical/setup.bash
colcon build --packages-select mono8_relay
```

> ⚠️ **不要** `--packages-select eprobot_base_cpp` —— 这个包的**源码不在本仓库**（只有头文件 + 二进制，
> 见 [`../rootfs/opt/eprobot_ws/install/eprobot_base_cpp/`](../rootfs/opt/eprobot_ws/install/eprobot_base_cpp/)）。
> 详情见 [`../README.md`](../README.md) 与 [`../firmware/README.md`](../firmware/README.md) §5。

---

## 3. 为什么 `eprobot_base`（Python）编了但不跑

`eprobot-base` unit 实际启动的是 **`eprobot_base_cpp`**（C++ 二进制）。Python 版是**参考实现**：

- 它的 `protocol.py` 是 C++ 版 `protocol.hpp` 的母本（后者头部原话 *"mirrored one-for-one from … the proven Python implementation"*）；
- 它带完整测试（`test/test_*.py` 7 个文件），**改协议前先在这里跑通**；
- 想让 Python 版接管，可以把 unit 的 `ExecStart` 改成 `ros2 run eprobot_base eprobot_base`，但**性能与延迟未验证**，不建议比赛用。

---

## 4. 依赖

系统级依赖（apt 包名与版本）见 `docs/依赖清单.md`（待建）。当前已知：
`ros-lyrical-*`、`libboost-thread`、`libudev`、OpenCV（`mono8_relay` 用 `cv_bridge`）。
