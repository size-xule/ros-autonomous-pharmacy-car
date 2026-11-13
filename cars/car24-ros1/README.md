# car24（ROS 2 升级前的出厂状态）· 归档索引

> 这台是**升级到 ROS 2 之前**的车：`EPRobot / Ubuntu 18.04 / ROS 1 Melodic / Python 2.7`，历史 IP `10.211.121.24`。
> 2026-11 之后整车换到 ROS 2 Lyrical（`cars/car22/`），**ROS 1 这套已经停用**，但出厂程序与原始驱动仍有参考价值，故归档在此。
>
> 本目录**不是可运行镜像**，而是"从 git 里能捞到的出厂物" + "捞不到的东西在哪"的索引。

---

## 0. 先回答"出厂固件在哪"

### ① 真正的出厂镜像（SD 卡整盘）—— **不在 git 里**

厂商说明书原话（`factory/smart_pharmacy/智慧药房-竞赛程序说明-V4.pdf` 第 1 页）：

> 智慧药房-竞赛程序说明 V4（**配 EprobotV2.3-rpi-ubuntu18-20231017 镜像**）

| 项 | 值 |
|---|---|
| 镜像名 | **`EprobotV2.3-rpi-ubuntu18-20231017`** |
| 内容 | Ubuntu 18.04 + ROS Melodic + 出厂 demo（`smart_pharmacy`）+ 出厂地图 |
| 位置 | **不在任何 git 仓库**（我扫过 Gitea 仓库全历史：只有 `reference/*.tar.gz` 和 `maps/*.7z` 两个压缩包，没有任何 `.img`） |
| 怎么拿 | ①找厂商（EPRobot / 北京塔洛斯）要这个镜像名；②问队里老硬盘/旧 SD 卡；③百度网盘（说明书里给的视频链接同目录通常有镜像） |

### ② 出厂竞赛程序包 —— **在 git 里，已抽到 `factory/smart_pharmacy/`**

这是厂商随镜像一起发的官方 demo，**仓库 2025-10-10 的第一个提交就带着它**（`62234c7`），说明是整个工程的起点。

| 文件 | 作用 |
|---|---|
| `script/smart_pharmacy.py` | 出厂主逻辑（`nav_pharmacy` 节点），按固定点位循环 |
| `script/diaodu.py` | 厂商给的**调度 demo**：识别 → 判断 → 选点 → 送药 |
| `script/detect_abc_for_EPRobot.py` | 识别板一（A/B/C 模板比对） |
| `script/{A,B,C,NULL}.jpg` | 字母模板 |
| `config/compitation_para.yaml` | 6 个点位之间的延时 |
| `launch/{smart_pharmacy_demo_init,robot_race_init}.launch` | 启动 |
| `智慧药房-竞赛程序说明-V4.pdf` | **厂商说明书**（4 页，见下方要点） |

### ③ 出厂驱动 —— **在 git 里，已抽到 `factory/vendor_driver/`**

| 文件 | 说明 |
|---|---|
| `base_control/`（7 文件） | 厂商驱动包：`script/base_control.py`（25 KB）+ README + launch |
| `art_racecar.py.orig590` | **厂商原版驱动**，590 行，GBK，头部 `Copyright 2019 Wechange Tech. / Developer: FuZhi, Liu` |
| `art_racecar.py.orig590_planb` | 592 行，planb 分支版本 |

> ⚠️ 历史文档说"605 行原版"，但 **git 里只有 590 / 592 两个**；605 那个可能只在某台车的备份里，未入库。

### ④ 我们自己的 2025 版（**不是厂商**，容易看混）

`reference/summer_best_pharmacy_pkg_2025.tar.gz`（2.76 MB，80 条目，tag `summer-best-2025`）
是 **2025-05 我们自己的 `pharmacy_pkg`**，来自 `G:\pharmacy_pkg`。名字像"出厂"，其实是"暑假最好的一版"。
标签 `summer-best-2025` 指向 `93827a6`（2026-10-26 归档提交）。

### ⑤ 缺口：5 个厂商包只有 gitlink

这些在仓库里是 `160000 commit`（子模块指针），**内容不在仓库**，clone 出来是空目录：

| 包 | 重要性 |
|---|---|
| **`ros_astra_camera`** | ★★★ ROS 1 的 Astra 相机驱动（出厂相机链核心） |
| **`ros_astra_launch`** | ★★★ 上者的 launch（`astra.launch`） |
| `robot_localization` | ★★ EKF（可 apt 装） |
| `robot_upstart` | ★ 开机自启（可 apt 装） |
| `yujin_ocs` | ★ 老设备包（基本用不到） |

**要补只能从实物捞**：`.24` 车的系统卡（若还在）或厂商镜像里的 `~/robot_ws/src/`。

---

## 1. 厂商说明书要点（PDF 原文摘录，对理解出厂逻辑很有用）

**启动顺序（出厂版）**
```bash
roslaunch astra_camera astra.launch
rosrun web_video_server web_video_server
rosrun eprobot_start detect_abc_for_EPRobot.py
roslaunch eprobot_start smart_pharmacy_demo_init.launch
rosrun eprobot_start diaodu.py          # 自动取送
```

**三个控制话题（出厂协议，与现在的 `/pharmacy/*` 完全不同）**

| 话题 | 取值 |
|---|---|
| `/cmd_send` | `1`=配药区(A/B/C) `3`=答题区(识别板二) `5`=取药区(化验区) `7`=起点 `9`=识别区(板一) |
| `/dispense_window` | `0`=C 窗口 `1`=A 窗口 `2`=B 窗口 |
| `/pick_up_num` | `3`=4 号窗口 `4`=3 号窗口 `5`=2 号窗口 `6`=1 号窗口 |

> **注意顺序**：先设窗口号，再发 `/cmd_send`，否则无效。

**出厂调度逻辑（`diaodu.py`）**
> 先到识别区 → 识别板 1 → **有 C 先取 C，没有就看 B，再没有看 A** → 到对应配药窗口 → 到答题区 → 送药 → 回原点 → 再来一轮。

**出厂地图**：`map_compitation.pgm / .yaml`（仓库里仍在：`D:\ISCC\_gitea_robot_ws_src\robot_navigation\maps\`）

> 这套逻辑与我们后来写的 `F1_yaofang.py` 最大的区别：出厂版是**固定点位循环 + 简单延时**；
> 我们改成了**事件驱动 + 到点判据 + 语音状态机 + MD5 取证**（见 `docs/竞赛笔记.md` §7）。

---

## 2. 怎么从 git 里再取出这些（可复现）

```bash
# 完整克隆那个仓库（公开可读）
git clone http://10.211.121.210:3000/gitadmin/robot_ws_src.git car24-ros1
cd car24-ros1

# ① 出厂程序包（含厂商 PDF）
git archive --format=zip -o smart_pharmacy.zip HEAD smart_pharmacy

# ② 厂商驱动包
git archive --format=zip -o base_control.zip HEAD base_control

# ③ 原版驱动（590 / 592 行）
git archive --format=zip -o orig.zip HEAD \
  eprobot_start/script/art_racecar.py.bak \
  eprobot_start/script/art_racecar.py.bak_planb

# ④ 我们自己的 2025 版
git show 93827a6:reference/summer_best_pharmacy_pkg_2025.tar.gz > summer_best_2025.tar.gz

# ⑤ 升级前最后状态（整棵工作区）
git checkout 40e6ec6        # 2026-10-28，ROS 1 最后一个提交
```

---

## 3. 时间线（为什么"出厂"和"我们的版本"容易混）

| 时间 | 事件 |
|---|---|
| 2019 | 厂商驱动 `art_racecar.py` 版权年（`Copyright 2019 Wechange Tech.`） |
| 2023-10-17 | **出厂镜像** `EprobotV2.3-rpi-ubuntu18-20231017` 的构建日期（PDF 提到） |
| 2025-05 | 我们自己的 `pharmacy_pkg` 一版（`G:\pharmacy_pkg`，后来归档成 `reference/*.tar.gz`） |
| 2025-10-10 | Gitea 仓库第一个提交（`3057a23`），此时 `smart_pharmacy` 已在库里 |
| 2026-06-15 | 厂商原版驱动（590 行）作为 `.bak` 入库（`d61f21f`） |
| 2026-10-17 | `chore(sync): snapshot working tree before moving to Gitea`（`4bd5153`），厂商版 `base_control.py` 正式受管 |
| 2026-10-26 | 归档 2025 版并打 tag `summer-best-2025`（`93827a6`） |
| 2026-10-28 | **ROS 1 最后一个提交** `40e6ec6`（本仓 `cars/car24-ros1` 对应的"升级前状态"） |
| 2026-11-02 起 | 整车升级 ROS 2 Lyrical（`cars/car22/`） |

---

## 4. 和 `cars/car22` 的关系

| 维度 | car24（出厂 / ROS 1） | car22（现在 / ROS 2） |
|---|---|---|
| 系统 | Ubuntu 18.04 + Melodic | Ubuntu 26.04 + Lyrical |
| 任务包 | `smart_pharmacy`（出厂）+ `pharmacy_pkg`（我们的） | `pharmacy_pkg`（**仅二进制**） |
| 相机 | `ros_astra_camera`（gitlink，缺） | Orbbec OpenNI2 + C++ `mono8_relay` |
| 导航 | move_base + TEB | Nav2 + MPPI + Smac |
| 控制话题 | `/cmd_send` `/dispense_window` `/pick_up_num` | `/pharmacy/*` + Nav2 action |
| 状态 | 停用（车已升级） | 在用 |

**用途**：car24 这套是"对照组"——想搞清"为什么要改"，对着看最清楚（`docs/竞赛笔记.md` §5 就是按它写的）。

---

## 5. 版权

`smart_pharmacy/`、`base_control/`、`art_racecar.py.orig590*`、厂商 PDF 均为 **EPRobot（北京塔洛斯科技）** 材料，此处仅作学习与竞赛复现，见根目录 [`NOTICE.md`](../../NOTICE.md)。
