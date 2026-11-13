# ros-autonomous-pharmacy-car

> **项目原名**：ROS 自主避障小车（ISCC「智慧药房」赛项用车）
> **成果说明**：本项目为 **cxy** 与 **xl** 于 **2026 年在宁波大学科学技术学院（宁大科院）** 共同调试完成的成果。
> 平台：EPRobot / 树莓派 4B / Ubuntu 26.04 + ROS 2 Lyrical（另有历史 ROS 1 Melodic 车）
> 仓库性质：**公开**。内含厂商固件与任务层二进制，版权归原厂所有，仅用于学习与竞赛复现（见 [`NOTICE.md`](NOTICE.md)）。

---

## 这个仓库是干什么的

把一个**能跑的比赛车**完整地存下来，做到三件事：

1. **换车/重刷后能恢复**：把 `cars/car22/rootfs/` 铺到一台同型号车上，装 unit、建软链、编 src，就能跑到和现在一样的水平。
2. **下位机也能重烧**：`cars/car22/firmware/` 放了 STM32 底盘固件源码（RT-Thread）、原理图、底层通信协议表。
3. **让 AI 或新人接手时不用从零摸索**：所有"为什么这么配""踩过什么坑""参数改了会怎样"都写在 `docs/` 里。

**一句话**：`cars/` 是"能跑的东西"，`docs/` 是"为什么能跑"，`tools/wsl/` 是"平时怎么操作它"。

---

## 新人从这里开始（30 秒）

1. **先读** [`docs/竞赛笔记导读.md`](docs/竞赛笔记导读.md) —— 按学习路径跳读，**不要从头啃 3100 行**。
2. **想复现一辆车** → [`docs/新车部署手册.md`](docs/新车部署手册.md)（详细打勾清单见 `docs/最小可复现清单.md`，待建）。
3. **想改代码 / 调参** → [`cars/car22/src/README.md`](cars/car22/src/README.md) + [`docs/竞赛笔记.md`](docs/竞赛笔记.md) §22；
   先确认"能不能改"：[`docs/学弟上手路径.md`](docs/学弟上手路径.md) §4（任务层只有二进制）。

> 三条路径（看原理 / 复现车 / 改任务）的入口表在 [`docs/学弟上手路径.md`](docs/学弟上手路径.md) §0。
> 仓库哪里乱、还缺什么，看 [`docs/仓库结构诊断.md`](docs/仓库结构诊断.md)。

---

## 目录

```
README.md                   ← 你在这里
NOTICE.md                   ← 第三方/厂商材料声明
LICENSE / LICENSE-DOCS      ← 许可（待建：脚本 MIT / 文档 CC BY-SA 4.0）
SECRETS.md                  ← 凭据索取流程（待建）
.gitattributes / .gitignore ← 保证 LF、挡住敏感文件

docs/
  竞赛笔记导读.md           ← ★ 先读：23 章索引 + 八段学习路径
  学弟上手路径.md           ← ★ 三条路径 + 能改/不能改边界
  竞赛笔记.md               ← ★ 主文档 3100+ 行：从零 ROS 到独立跑一圈
  新车部署手册.md           ← 把本仓库铺到一台新车上的步骤
  仓库结构与维护.md         ← 目录约定 / 更新纪律 / 迁移记录
  仓库结构诊断.md           ← 14 个已知问题与处置
  附录-文件清单.md          ← 自动生成：702 个文件逐个列大小
  （待建）依赖清单 · 航点标定手册 · unit依赖关系 · 版本矩阵
          最小可复现清单 · 故障恢复手册 · 外部材料与索取清单 · adr/

cars/
  car22/                    ← 现在这台车（10.211.121.22 / EPRobot2）
    README.md               ← 本车档案（含『原理索引』表 → 笔记章节）
    rootfs/                 ← 直接可拷到 / 的成品：install 产物、配置、unit、脚本、模型
    src/                    ← 源码，README 索引 6 个包（Python 参考实现 + 4 C++ + relay）
    firmware/
      chassis_mcu/          ← ★ STM32 底盘固件源码（两个版本）+ 原理图 + 协议表
      README.md             ← 固件四层划分、关键参数、烧录/核对方法
  car21/                    ← ★ 初代机（10.211.121.21 / EPRobot1）· 从 SD 卡只读取件
    README.md               ← 档案：账号/AP 热点实现/与 car22 的六处硬差异
    rootfs/ src/            ← 成品与源码
    export_from_sd.sh       ← 从 .21 的卡再导出一次（只读 + trap 自动 umount）

install/
  apply_to_car22.sh         ← 一键铺到新车（默认 dry-run，需 --yes 才写；拒绝对 .22 直接铺）

tools/
  selfcheck.sh              ← ★ 仓库自检（链接/二进制 SHA/unit 语法/凭据/命名/红线）
  gen_manifest.sh           ← 生成 docs/附录-文件清单.md
  wsl/                      ← ★ WSL 快捷指令全套（iscc / car* / rviz-car / ros_env.sh）
  host-iscc/                ← 主机侧（WSL）iscc 工具箱 + 配置模板
  probes/                   ← 只读诊断脚本（网络/相机/IMU/CPU）
  backup_car.sh             ← 从车上只读打包一份快照回来
```

---

## 30 秒上手（已经在一台同型号新车上）

```bash
git clone https://github.com/size-xule/ros-autonomous-pharmacy-car.git
cd ros-autonomous-pharmacy-car

# 1) 先看要做什么（不写任何东西）
bash install/apply_to_car22.sh --dry-run

# 2) 真干（会先把冲突文件备份到 ~/.backup_<时间戳>/）
bash install/apply_to_car22.sh --yes

# 3) 编译需要 build 的包（eprobot_base / lidar / IMU / relay）
bash install/apply_to_car22.sh --build

# 4) 起车
iscc kill && iscc pre      # 主机侧（WSL）；车不动
iscc start                 # ★ 车会动
```

详细步骤、前置条件、失败处理：**`docs/新车部署手册.md`**。

---

## 全套脚本一览（三层，别混）

| 层 | 跑在哪 | 入口 | 说明 |
|---|---|---|---|
| **主机层** | Windows 里的 WSL | `iscc` | 远程操作车：`pre / start / stop / kill / status / gray / camtime / rviz2`。见 `tools/wsl/` |
| **车上成品层** | 车的 `/opt` `/home` `/etc` | `eprobot-*` systemd unit | 底盘/IMU/雷达/相机/Nav2/识别/裁判，见 `cars/car22/rootfs/` |
| **下位机层** | STM32 底盘板 | 串口 `0x5A` 协议 | 运动学 + PID + 舵机，见 `cars/car22/firmware/` |

> ⚠️ **四个"固件"不是一回事**（详见 [`cars/car22/firmware/README.md`](cars/car22/firmware/README.md)）：
> - **下位机固件**（`firmware/chassis_mcu/`）= STM32 上的 RT-Thread 工程，管电机/舵机/PID。**与 ROS 1/ROS 2 都无关**，只认串口字节流。
> - **ROS 2 驱动 · Python 版**（`src/opt_eprobot_ws_src/eprobot_base/`）= **参考实现**，含完整测试；C++ 版就是照它写的。
> - **ROS 2 驱动 · C++ 版**（`rootfs/opt/eprobot_ws/install/eprobot_base_cpp/`）= **车上实际在跑的那个**，只有头文件 + 二进制，`.cpp` 缺失。
> - **任务层**（`rootfs/.../lib/pharmacy_pkg/`）= 比赛逻辑，只有二进制。

---

## 两台车（别搞混）

| | **car22（本仓库主目标）** | **car21（初代机）** |
|---|---|---|
| IP | `10.211.121.22` | `10.211.121.21` |
| 主机名 | `EPRobot2` | `EPRobot1` |
| 账号 | `keyuan22` | `ubuntu` |
| 系统 / ROS | Ubuntu 26.04.1 / Lyrical | 同 |
| 相机 | Astra S（无 UVC，Orbbec OpenNI2 + C++ mono8 relay） | Astra Pro HD（有 UVC）+ Astra Pro |
| WiFi | 连外部热点 `OnePlusAce5` | 自发热点 `yaofang` |
| 状态 | 在线 | **已归档**（2026-11-13 只读取件；车本体仍无卡） |

> ⚠️ **主机名会撞**：如果哪天遇到一台也叫 `EPRobot1` 的机器，别假设是 `.21`。
> **认车只用 IP + 账号 + ROS 版本**，不要用 `hostname`。
>
> 🔎 **`.21` 和 `.22` 的航点差得很大**（`board2` 差 0.72 m、`board1` 差 10 cm），**绝不要互抄**，见 `cars/car21/README.md` §2。

---

## 这个仓库里有什么 / 没有什么

**有**（`cars/car22/`）：
- 任务层全部二进制（`f1_mission_node`、`judge_tcp_node`、`pharmacy_qr_node`、板二两个后端、`pharmacy_speech_node`）——**源码厂商没给，二进制就是唯一产物**
- 全部 launch / config / 航点 / 地图 / 语音 wav（77 条）
- 15 个 systemd unit、udev 规则、netplan、`/etc/default` 环境文件
- `/usr/local/bin` 全部辅助脚本（`iscc-*`、`openni2-camera`、`lslidar-ctl`）
- 相机链：C++ `mono8_relay` **源码**、Orbbec OpenNI2 SDK（2.8 MB）
- 板二 OCR：worker 源码 + PP-OCRv6 tiny 模型 + 13 张验收样图
- **ROS 2 底盘驱动两套**：`eprobot_base`（**Python 参考实现，含 7 个测试文件**）+ `eprobot_base_cpp`（**车上实际在跑**：头文件 + 二进制，`.cpp` 实现缺失）
- `lslidar_ros2` / `serial_ros2` / `yesense_*` **源码**（要 build）
- **STM32 底盘固件源码**（RT-Thread，两个版本）+ 原理图 + 底层通信协议表

**没有**（见 `docs/仓库结构与维护.md` 的"未入库清单"）：
- `cartographer` / `cartographer_ros`（9 MB，上游标准包，apt 装）
- `board2_ocr/runtime_arm64`（**276 MB** 的打包 Python 运行时，按 `requirements.txt` 重装）
- ROS 本体 `/opt/ros/lyrical`（apt 装）
- 任何密码、密钥、`iscc.conf` 真本（只放 `iscc.conf.example`；WiFi 密码也是占位符）

---

## 状态与免责

- **最后同步**：2026-11-13，从 `keyuan22@10.211.121.22` 只读打包（未改动车上任何文件）。
- 仓库内容按"**能恢复**"标准整理，**但恢复后仍需现场标定航点**——坐标是"这辆车+这块场地"的量出来的，换了车必须重标（见竞赛笔记 §7.5）。
- 二进制为 **aarch64**，不能在 x86 上跑。
- 厂商固件/SDK/二进制的版权归原厂，本项目仅作学习与竞赛复现用途，**不提供任何担保**。详见 [`NOTICE.md`](NOTICE.md)。

---

## 怎么拿到"项目压缩包"

- **网页**：打开仓库 → 绿色 `Code` 按钮 → **Download ZIP**（含全部二进制、模型与固件，约 60 MB）
- **命令行**：
  ```bash
  git clone https://github.com/size-xule/ros-autonomous-pharmacy-car.git
  # 或者只要快照、不要 .git：
  curl -L -o car.zip https://github.com/size-xule/ros-autonomous-pharmacy-car/archive/refs/heads/main.zip
  ```

## 把压缩包交给 AI 时，这样说话

> 这是一个 ROS 2（Lyrical / 树莓派 4B / Ubuntu 26.04）比赛车的完整运行时快照。
> `cars/car22/rootfs/` 里的路径就是车上的绝对路径，`cars/car22/src/` 需要 colcon build，
> `cars/car22/firmware/chassis_mcu/` 是 STM32 下位机固件（烧到 MCU，不是树莓派）。
> 请读 `docs/新车部署手册.md`，帮我把这套东西铺到一台新车上；先做 dry-run 给我看要改哪些文件，
> 再按 `install/apply_to_car22.sh` 的步骤执行。注意：WiFi 密码和 SSH 密码是占位符，要我提供真值；
> 航点必须重新标定，不要直接沿用 `mission_waypoints.yaml` 里的坐标。

**三条红线**（写在提示词里，避免 AI 乱来）：
1. 不要改 `cars/car22/rootfs/opt/.../lib/pharmacy_pkg/` 下的**二进制**（无源码，改了就用不了）。
2. 不要跳过备份；`install/apply_to_car22.sh` 默认 dry-run，别一上来就 `--yes`。
3. 不要在 `.22` 这台上直接铺（脚本会拒绝，除非 `--force`）。

---

## 致谢

本项目由 **cxy** 与 **xl** 于 **2026 年**在 **宁波大学科学技术学院（宁大科院）** 共同调试完成。
硬件平台与底层固件来自 EPRobot（北京塔洛斯科技），赛项规则来自中国机器人及人工智能大赛组委会。
仓库中的调试记录、参数标定与文档由两位作者整理。
