# car22 · 固件（下位机 + ROS 2 驱动）

> ⚠️ **先把四个东西分开**，否则一定会搞混：
>
> | # | 名字 | 跑在哪 | 语言 | 源码在仓库？ | 位置 |
> |---|---|---|---|---|---|
> | ① | **下位机固件**（底盘 MCU） | STM32F4 底盘板 | C / RT-Thread | ✅ **有，两个版本** | `chassis_mcu/*.7z`（本目录） |
> | ② | **ROS 2 驱动 · Python 版**（参考实现） | 树莓派 | Python / rclpy | ✅ **有，含完整测试** | `../../src/opt_eprobot_ws_src/eprobot_base/` |
> | ③ | **ROS 2 驱动 · C++ 版**（**车上实际在跑**） | 树莓派 | C++ / rclcpp | ⚠️ **只有头文件 + 二进制，`.cpp` 缺失** | `../../rootfs/opt/eprobot_ws/install/eprobot_base_cpp/` |
> | ④ | **任务层** | 树莓派 | C++ | ❌ 只有二进制 | `../../rootfs/.../pharmacy_pkg/lib/` |
>
> **下位机固件与 ROS 1 / ROS 2 无关** —— 它只认串口字节流（`0x5A` 帧）。
> 真正"适配 ROS 2"的是树莓派上的 ② 和 ③；两者协议完全一致（`eprobot_base_cpp` 的 `protocol.hpp` 头部原话：
> *"Wire protocol v2.1, mirrored one-for-one from PROTOCOL.md and the proven Python implementation in ../eprobot_base/eprobot_base/protocol.py"*），
> 所以 **② 的源码就是 ③ 的可读替代品**，改协议先看 Python 版。

**📖 原理章节**：协议逐字节解读见 [`竞赛笔记.md` §5.3](../../../docs/竞赛笔记.md)；odom 积分公式见 [`§5.4`](../../../docs/竞赛笔记.md)；IMU 选型与更换见 [`§21`](../../../docs/竞赛笔记.md)；参数值的来历见 [`§5.8` / `§22`](../../../docs/竞赛笔记.md)。

---

## 1. 本目录内容

| 文件 | 说明 |
|---|---|
| `EPRobot_controller_1.3-20210520.7z` | **首选**。RT-Thread 工程 `Bottom_controller`，最新一版（2021-05-20）；内含 **959 个 `.c` / 1053 个 `.h`**，共约 3800 个条目 |
| `EPRobot_controller_1.3-20210415.7z` | 较早一版（2021-04-15），保留对照 |
| `EPRobot_base_sch_V1.3.pdf` | 底盘原理图 V1.3 |
| `EPRobot智能小车底层通信协议.xlsx` | 厂商协议表（与本仓库文档 §5.3 的实测结论可能有出入，**以实测为准**） |

> **验证过**：`7z l` 确认包含完整源码树 `applications/` + `rt-thread/` 组件 + `Debug/` 编译产物，
> 不是"只给 hex/bin"的固件包。

解压后是 Eclipse CDT / RT-Thread Studio 工程，关键源码：

```
applications/
├── main.c                  # 主循环：电池、蜂鸣器、激光状态
├── inc/
│   └── bottom_steering.h   # ★ 轴距 L=0.1445f、轮距 B=0.155f、舵机限位 ±24°
└── src/
    ├── bottom_uart.c       # ★ 串口协议收发（0x01/0x03/0x07/0x09/0x13/0x21）
    ├── bottom_steering.c   # ★ 阿克曼运动学（rotateRadius = L / tan|δ|）
    ├── bottom_pid.c        # 速度 PID（默认 Kp=22.6 / Ki=16.5 / Kd=11.0）
    ├── bottom_mfac.c       # 无模型自适应控制
    ├── bottom_mpu6050.c    # ★ IMU 读取与量化（1 LSB = 0.061 °/s）
    └── bottom_pwm.c        # 电机 / 舵机 PWM
```

> **编码**：源码是 **GBK/ANSI**，用 UTF-8 打开会乱码。改之前先备份原压缩包。

---

## 2. 关键参数（改之前必须知道）

| 项 | 值 | 在哪 | 影响 |
|---|---|---|---|
| 轴距 `L` | **0.1445 m** | `inc/bottom_steering.h` | 转弯半径换算。上位机 `robot_lidar.launch` 里写的是 **0.160**（实测值），两者差约 9.7%，见竞赛笔记 §5.8 的未解项 |
| 轮距 `B` | 0.155 m | 同上 | 差速/阿克曼几何 |
| 舵机限位 | **±24°**（固件） | 同上 | 上位机驱动限幅 ±30°，**实测 33° 反向开始卡、38°+ 堵转** |
| 速度 PID | **22.6 / 16.5 / 11.0** | `bottom_pid.c` | 上位机每帧 `0x01` 会**显式覆盖**这组 PID（`base_kp/ki/kd = 1000/100/0`） |
| 停转 PID | 100 / 30 / 0 | 上位机 launch | 零速/超时时用 |
| 陀螺量化 | 1 LSB = **0.061 °/s** | `bottom_mpu6050.c` | 低速时 `ω` 精确输出 0，这是"IMU 全 0"的真正原因（不是掉帧） |
| 串口 | 115200 8N1 | `bottom_uart.c` | `/dev/EPRobot_base` → `ttyAMA0` |

---

## 3. 协议速查（与上位机对接的唯一接口）

```
┌──────┬─────┬─────┬─────┬──────────────┬──────┬──────┐
│ 0x5A │ LEN │ ID  │ CMD │    DATA...   │ 预留 │ CRC8 │
└──────┴─────┴─────┴─────┴──────────────┴──────┴──────┘
  LEN = 整帧字节数（含 CRC）    ID 固定 0x01    CRC-8/MAXIM (poly 0x31, init 0, xorout 0)
```

| 方向 | CMD | 长度 | 内容 |
|---|---|---|---|
| 上位机→下位机 | `0x01` | 18 | `vx(mm/s) vy steer(mrad) kp ki kd NC` |
| 上位机→下位机 | `0x07` / `0x09` / `0x13` / `0x21` | 6/7/6/28 | 查电池 / 设雷达档位+触发里程 / 查原始 IMU / 报树莓派状态 |
| 下位机→上位机 | `0x0A` | 12 | `vx(mm/s) yaw(0.01°) ω(0.01°/s)` |
| 下位机→上位机 | `0x08` / `0x14` / `0x04` | 10/38/12 | 电池 / 原始 IMU / 运动反馈 |

**两个必须记住的坑**
1. **CRC 覆盖范围上行/下行不同**：下行覆盖到"预留位（含）"，**上行只覆盖到最后一个 DATA（`len-2`）**。把上行也按 `len-1` 算，每帧都判校验失败。
2. **`0x0A` 的 yaw 与 ω 符号相反**。上位机必须 `yaw_sign=-1`、`gyro_sign=+1`，否则转向反向或 EKF 的 `vyaw` 反号。

---

## 4. 什么时候需要动下位机固件

**绝大多数情况不要动。** 只在以下场景才碰：

- 换底盘板 / MCU 损坏要重烧；
- 要改舵机限位（**危险**：改大了会堵转烧舵机）；
- 要加新的上报字段（**危险**：协议一变，上位机解析全挂）。

**烧录流程（简述）**
1. 解压 `.7z`，用 RT-Thread Studio / Eclipse CDT 打开 `Bottom_controller`；
2. 确认 `applications/inc/bottom_steering.h` 的 `L` 与你车的实际轴距一致（卷尺量：后轴中心 → 前轴中心）；
3. 编译，产物 `Debug/rtthread.bin`；
4. ST-Link / DAP-Link 接 SWD，烧 `rtthread.bin`；
5. 上电，OLED 应显示电压/速度；串口应能收到 `0x0A` 回包（发一次 `0x09` 回一帧）。

**烧完必须验证的三件事**
```bash
# 在车上（ROS 2）
ros2 topic hz /odom                 # ~50 Hz
ros2 topic echo --once /imu/data    # 有四元数
# 低速前进 + 左转，确认 odom yaw 增大（方向对）
```

---

## 5. 和 ROS 2 侧的关系（这才是"ROS2 固件"）

树莓派上的 `eprobot_base` 节点负责：

```
/cmd_vel ──► δ = atan(L·ω / v) ──► 0x01 帧 ──► STM32
                                     ▲
/odom /imu_data /battery ◄── 0x0A / 0x14 / 0x08 ◄──┘
```

它的**可调参数**（在 `/opt/eprobot_ws/install/eprobot_base_cpp/share/eprobot_base_cpp/config/base.yaml`，不在 MCU 固件里）。

> ⚠️ **一套参数只服务一代车**。下表左列是历史 ROS 1 车的值，右列才是 **`.22` 现在真在用的 C++ 驱动**。
> 换车/换驱动时以**实际加载的 yaml** 为准，不要互相抄。

| 参数 | ROS 1 车（历史） | **ROS 2 车 `.22`（在用）** | 说明 |
|---|---|---|---|
| `axle_length` / `wheelbase` | 0.160 | **0.171** | 含转向连杆/角度比例补偿；注释说物理轴距 0.160 |
| `base_kv` | 1.089 | **1.0** | `.22` 不额外放大（注释：固件 `D=0.065` 与实测轮径一致） |
| `max_vx` | 0.9（TEB 限） | **1.2** | 主机上限 |
| `max_steer_mrad` | 30000（±30°） | **567**（≈45° 舵机 / 32.5° 前轮） | 与固件 `kSteerMaxMrad` 取小值 |
| `min_vx` / `min_nonzero_speed` | 0.08 | **0.05** | 低于它车不动 |
| `kp` / `ki` / `kd` | 1000 / 100 / 0 | **500 / 100 / 0** | 每帧写入 MCU，**覆盖固件默认** |
| `publish_tf` | false（TF 归 EKF） | **true** | `.22` 由驱动自己发 `odom→base_link` |
| `cmd_rate_hz` / `odom_rate_hz` | 50 / 50 | **30 / 50** | 指令 30 Hz、里程 50 Hz |
| `h30_topic` / `h30_timeout_s` | — | `/imu/data` / 0.3 | 用 H30 的 yaw 出里程 |

**改哪个？**
- 改**协议/运动学/IMU 信任** → 看 Python 版 `../../src/opt_eprobot_ws_src/eprobot_base/`（有 `test/` 七个测试文件，可先跑通再移植到 C++）。
- 改**参数** → 只改 `base.yaml`，然后 `sudo systemctl restart eprobot-base`，**不用碰下位机**。
- 改**下位机行为**（舵机限位、PID 默认、新增上报字段）→ 才需要动 `chassis_mcu/` 里的固件源码。

**`.22` 的 C++ 驱动是"半开源"状态**：`include/eprobot_base_cpp/*.hpp`（6 个头文件）在仓库里，
但 `.cpp` 实现从未随包发布，车上也找不到（`find / -name eprobot_base_cpp -not -path '*/install/*'` 返回空）。
所以**要改 C++ 实现只能先按 Python 版重写**。

---

## 6. 免责

固件与原理图版权归 EPRobot（北京塔洛斯科技）所有，此处仅作学习与竞赛复现。
**改固件前请先备份原压缩包，并确认你有恢复手段（ST-Link + 原始 bin）。**
