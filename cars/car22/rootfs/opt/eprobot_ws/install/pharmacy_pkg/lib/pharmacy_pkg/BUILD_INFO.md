# BUILD_INFO · 任务层二进制的来源与校验

> 目录：`lib/pharmacy_pkg/`（车上 `/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/`）
> **这 9 个 ELF 是"唯一产物"——厂商没给源码，改不了、也修不了。**
> 本文件只记录**来源与校验**，不解释行为（行为见 [`../../../../../../../docs/竞赛笔记.md`](../../../../../../../docs/竞赛笔记.md) §7）。

---

## 1. 校验结论（2026-11-13）

**本仓库的 9 个二进制与车上 `car22` 的同名文件逐字节一致（9/9 SHA-256 匹配）。**

```bash
bash verify.sh          # 在本目录执行
```

| 文件 | 大小 | mtime（车上） |
|---|---:|---|
| `f1_mission_node` | 2,534,200 | 2026-11-07 03:12 |
| `judge_tcp_node` | 3,013,176 | 2026-10-26 21:28 |
| `pharmacy_qr_node` | 3,030,504 | 2026-10-27 04:01 |
| `pharmacy_board2_node` | 1,730,688 | 2026-10-26 21:27 |
| `pharmacy_board2_fast_node` | 1,738,712 | 2026-10-28 10:26 |
| `pharmacy_speech_node` | 1,132,680 | 2026-10-26 21:26 |
| `board_benchmark` | 253,056 | 2026-10-28 10:22 |
| `pharmacy_detection_backtest` | 624,800 | 2026-10-28 10:25 |
| `pharmacy_mission_backtest` | 238,728 | 2026-10-27 18:00 |

> 精确哈希见 [`SHA256SUMS`](SHA256SUMS)。

---

## 2. 构建环境（从 ELF 里读出来的，不是猜的）

| 项 | 值 | 来源 |
|---|---|---|
| 架构 | **aarch64**, ELF 64-bit LSB **PIE** | `file` |
| 编译器 | **GCC 15.2.0**（`gcc (Ubuntu 15.2.0-16ubuntu1) 15.2.0`） | `strings \| grep GCC:` |
| CMake | 4.2.3 | 车上 `cmake --version` |
| 链接器 | GNU ld 2.46 | 车上 `ld --version` |
| 内核 | `Linux EPRobot2 7.0.0-1020-raspi aarch64` | `uname -a` |
| 系统 | Ubuntu 26.04.1 LTS | `/etc/os-release` |
| ROS | ROS 2 **Lyrical**（`ros-lyrical-ros-base 0.13.0-3resolute.20260919.195359`） | `dpkg-query` |
| 构建日期 | **2026-10-26 ~ 2026-11-07**（逐个文件 mtime） | `ls -l` |

**动态依赖**（`f1_mission_node` 的 `NEEDED`，节选）：
```
libnav2_msgs__rosidl_typesupport_cpp.so   libnav_msgs__rosidl_typesupport_cpp.so
librclcpp_action.so  librcl_action.so  librclcpp.so  librcl.so
libament_index_cpp.so  libtracetools.so
libgeometry_msgs__rosidl_typesupport_cpp.so  libstd_msgs__rosidl_typesupport_cpp.so
```
→ 全部来自 `/opt/ros/lyrical`。**没有静态链接，也没有 RPATH**，所以新车上必须装同一代 ROS 2，
否则会出现 `error while loading shared libraries`。

---

## 3. 构建命令：❌ 未知（需向作者索取）

车上**找不到** `pharmacy_pkg` 的 `CMakeLists.txt` / `package.xml` / `src/`：

```bash
# 2026-11-13 实测（只读）
find / -name 'CMakeLists.txt' -path '*pharmacy*' 2>/dev/null     # 无输出
ls /opt/eprobot_ws/src/                                          # 只有 7 个第三方包
```

**需向厂商/原作者索取**：
1. `pharmacy_pkg` 的 **colcon 工程**（`CMakeLists.txt`、`package.xml`、`src/*.cpp`）；
2. 构建命令（`colcon build --packages-select pharmacy_pkg ...` 的完整参数）；
3. 是否有 `-DCMAKE_BUILD_TYPE=Release`、`-O2/-O3`、`-march=` 之类的编译选项（影响性能与浮点行为）；
4. 是否使用了厂商私有头文件（`judge_wire.hpp` / `mission_logic.hpp` 等**已随 install 一起发布**，在 `include/pharmacy_pkg/`）。

> 在拿到源码之前，**任何"重新编译"的尝试都不可行**。能改的只有 YAML/参数（见 `docs/学弟上手路径.md` §4）。

---

## 4. 版本时间线（从车上 `.bak_*` 文件名反推）

车上的备份命名本身就带语义，按时间排出来就是一次"改动史"（这些 `.bak` **未入库**，只在车上）：

| 时间（车上 mtime） | 备份文件名 | 推断的改动 |
|---|---|---|
| 2026-10-26 21:23 | `board_benchmark.bak_multitemplate_20261027_134803` | 板二从"单模板"改成"多模板"之前 |
| 2026-10-27 21:48 | `board_benchmark.bak_digitrank_20261028_103256` | 加"数字评分/排序"之前 |
| 2026-10-28 10:22 | `board_benchmark`（现行） | 数字评分版 |
| 2026-10-26 21:29 | `pharmacy_qr_node.bak_bc_pref_20261026_200129` | 二维码"BC 优先"策略之前 |
| 2026-10-27 04:01 | `pharmacy_qr_node`（现行） | BC 优先版 |
| 2026-10-27 18:00 | `f1_mission_node.bak_speech_home_20261027_191900` | "回家播报"改动之前 |
| 2026-10-27 19:19 | `f1_mission_node.bak_20261107_031223` | 11-07 改动前的版本 |
| **2026-11-07 03:12** | **`f1_mission_node`（现行）** | 最后一次改动（大小与上一版相同，仅内容变化） |
| 2026-10-27 22:11 | `pharmacy_detection_backtest.bak_busy6_8_10_20261027_221145` | 支持 `BUSY_6/8/10` 之前 |
| 2026-10-28 10:25 | `pharmacy_detection_backtest`（现行） | 数字评分版 |

> ⚠️ **`f1_mission_node` 是 2026-11-07 的版本，比其它 8 个都新**。如果行为异常，
> 先确认车上跑的是不是这一份：`sha256sum /opt/.../f1_mission_node` 对比 [`SHA256SUMS`](SHA256SUMS)。

---

## 5. 怎么校验

```bash
# ① 校验本仓库里的副本
cd cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg
bash verify.sh

# ② 校验车上跑的那一份（在车上执行）
cd /opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg
sha256sum -c <(sed 's/^/ /' /dev/null)  # 或把本目录的 SHA256SUMS 传上去再 -c
```

`verify.sh` 支持 `--remote <user>@<ip>`：直接把本仓库的哈希与车上逐个对比。

---

## 6. 红线

1. **不要 `strip` / `upx` / 打补丁**——改了哈希，`verify.sh` 会失败，也没人知道改出了什么。
2. **不要替换**成自己编的版本（你没有源码，编不出来）。
3. **不要单独删某个**（`pharmacy_*.launch.py` 会按名字 `Executable=` 去起，缺一个就整栈起不来）。
4. 二进制变了**必须**在 commit message 里写新哈希，并同步更新 `SHA256SUMS`。
