# ros-autonomous-pharmacy-car

> 项目原名：**ROS 自主避障小车**（ISCC「智慧药房」赛项用车）
> 平台：EPRobot / 树莓派 4B / Ubuntu 26.04 + ROS 2 Lyrical（另有历史 ROS 1 Melodic 车）
> 仓库性质：**私有**。含厂商二进制、比赛配置、内部文档，请勿外传。

---

## 这个仓库是干什么的

把一个**能跑的比赛车**完整地存下来，做到两件事：

1. **换车/重刷后能恢复**：把 `cars/car22/rootfs/` 铺到一台同型号车上，装 unit、建软链、编 src，就能跑到和现在一样的水平。
2. **让 AI 或新人接手时不用从零摸索**：所有"为什么这么配""踩过什么坑""参数改了会怎样"都写在 `docs/` 里。

**一句话**：`cars/` 是"能跑的东西"，`docs/` 是"为什么能跑"。

---

## 目录

```
README.md                   ← 你在这里
.gitattributes              ← 保证 Linux 上还原成 LF、二进制不被改
docs/
  竞赛笔记.md               ← ★ 主文档：从零 ROS 到独立跑一圈（3000+ 行）
  新车部署手册.md            ← ★ 把本仓库铺到一台新车上的完整步骤
  仓库结构与维护.md          ← 目录约定、怎么从车上更新、什么没入库
cars/
  car22/                    ← 现在这台车（10.211.121.22 / EPRobot2）
    README.md               ← 本车档案（硬件/服务/话题/参数/已知问题）
    rootfs/                 ← 直接可拷到 / 的成品：install 产物、配置、unit、脚本、模型
    src/                    ← 需要在新车 colcon build 的源码
  car21/                    ← 预留位（初代机 10.211.121.21，卡被拔走）
    README.md               ← 占位说明 + 从 SD 卡导出的方法
    export_from_sd.sh       ← 在 .22 上跑，把 .21 的卡内容整理成同样的结构
install/
  apply_to_car22.sh         ← 一键铺到新车（默认 dry-run，需 --yes 才写）
tools/
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

## 两台车（别搞混）

| | **car22（本仓库主目标）** | **car21（预留）** |
|---|---|---|
| IP | `10.211.121.22` | `10.211.121.21` |
| 主机名 | `EPRobot2` | `EPRobot1` |
| 账号 | `keyuan22` | `ubuntu` |
| 系统 / ROS | Ubuntu 26.04.1 / Lyrical | 同 |
| 相机 | Astra S（无 UVC，Orbbec OpenNI2 + C++ mono8 relay） | Astra Pro HD（有 UVC）+ Astra Pro |
| WiFi | 连外部热点 `OnePlusAce5` | 自发热点 `yaofang` |
| 状态 | 在线 | 离线（系统卡插在 `.22` 的读卡器上） |

> ⚠️ **主机名会撞**：`.21` 和历史上那台 ROS 1 的 `.24` 都叫 `EPRobot1`。
> **认车只用 IP + 账号 + ROS 版本**，不要用 `hostname`。

---

## 这个仓库里有什么 / 没有什么

**有**（`cars/car22/`）：
- 任务层全部二进制（`f1_mission_node`、`judge_tcp_node`、`pharmacy_qr_node`、板二两个后端、`pharmacy_speech_node`）——**源码厂商没给，二进制就是唯一产物**
- 全部 launch / config / 航点 / 地图 / 语音 wav（77 条）
- 15 个 systemd unit、udev 规则、netplan、`/etc/default` 环境文件
- `/usr/local/bin` 全部辅助脚本（`iscc-*`、`openni2-camera`、`lslidar-ctl`）
- 相机链：C++ `mono8_relay` **源码**、Orbbec OpenNI2 SDK（2.8 MB）
- 板二 OCR：worker 源码 + PP-OCRv6 tiny 模型 + 13 张验收样图
- `eprobot_base` / `lslidar_ros2` / `serial_ros2` / `yesense_*` **源码**（要 build）

**没有**（见 `docs/仓库结构与维护.md` 的"未入库清单"）：
- `cartographer` / `cartographer_ros`（9 MB，上游标准包，apt 装）
- `board2_ocr/runtime_arm64`（**276 MB** 的打包 Python 运行时，按 `requirements.txt` 重装）
- ROS 本体 `/opt/ros/lyrical`（apt 装）
- 任何密码、密钥、`iscc.conf` 真本（只放 `iscc.conf.example`）

---

## 状态与免责

- **最后同步**：2026-11-13，从 `keyuan22@10.211.121.22` 只读打包（未改动车上任何文件）。
- 仓库内容按"**能恢复**"标准整理，**但恢复后仍需现场标定航点**——坐标是"这辆车+这块场地"的量出来的，换了车必须重标（见竞赛笔记 §7.5）。
- 二进制为 **aarch64**，不能在 x86 上跑。
- 本仓库不含任何授权许可，仅限队内使用。
