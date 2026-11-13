# NOTICE · 第三方与厂商材料声明

> 本仓库是**竞赛与学习用途**的工程快照，**混合了多种不同许可的代码**。
> **重要：本仓库不是"整体一个许可"。** 下表逐项列出归属与许可，**以本表为准**。
> 队伍原创部分的许可见 [`LICENSE`](LICENSE)（代码/MIT）与 [`LICENSE-DOCS`](LICENSE-DOCS)（文档/CC BY-SA 4.0）。

---

## 1. 一张表看清所有非原创材料

| # | 材料 | 仓库位置 | 权利方 | 许可 | 依据 |
|---|---|---|---|---|---|
| 1 | **`lslidar_driver` / `lslidar_msgs`**（雷达驱动） | `cars/car22/src/opt_eprobot_ws_src/lslidar_ros2/`、`cars/car21/.../lslidar_ros2/` | 镭神智能（LSLIDAR）/ Nick Shu | ⚠️ **GPL-3.0**（GNU GPL v3） | `lslidar_driver/package.xml` 的 `<license>` |
| 2 | **`serial`**（串口库） | `cars/car22/src/opt_eprobot_ws_src/serial_ros2/` | jinmenglei（社区作者，`841549111@qq.com`） | Apache-2.0 | `package.xml` 的 `<maintainer>` / `<license>` |
| 3 | **`yesense_interface` / `yesense_std_ros2`**（IMU 驱动） | `cars/car22/src/opt_eprobot_ws_src/yesense_*/` | 深圳市元感科技（YESENSE） | Apache-2.0 | `package.xml`（`contact@yesense.com`） |
| 4 | **STM32 底盘固件源码**（RT-Thread 工程，两个版本） | `cars/car22/firmware/chassis_mcu/EPRobot_controller_1.3-*.7z` | EPRobot（北京塔洛斯科技） | **未声明**（厂商材料，仅授权用于配套硬件） | 厂商随车提供 |
| 5 | **底盘原理图** | `.../EPRobot_base_sch_V1.3.pdf` | 同上 | 同上 | 同上 |
| 6 | **底层通信协议表** | `.../EPRobot智能小车底层通信协议.xlsx` | 同上 | 同上 | 同上 |
| 7 | **任务层二进制**（9 个 ELF：`f1_mission_node` / `judge_tcp_node` / `pharmacy_qr_node` / `pharmacy_board2_node` / `pharmacy_board2_fast_node` / `pharmacy_speech_node` / `board_benchmark` / `pharmacy_detection_backtest` / `pharmacy_mission_backtest`） | `cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/`、`cars/car21/...` | EPRobot | **未声明**（只给编译产物，无源码） | 厂商随车提供 |
| 8 | **`pharmacy_pkg` 的 launch / config / include 头文件** | `.../install/pharmacy_pkg/share/`、`.../include/` | EPRobot | 同上 | 同上 |
| 9 | **Orbbec OpenNI2 SDK** | `cars/car22/rootfs/opt/oni2-orbbec/` | 奥比中光（Orbbec） | 厂商 SDK 许可（随 SDK 分发，禁止单独再分发） | SDK 自带 |
| 10 | **PP-OCRv6 tiny 模型**（`det_tiny` / `rec_tiny`，ONNX） | `cars/car22/rootfs/home/keyuan22/board2_ocr/models/` | 百度 / PaddleOCR | Apache-2.0 | PaddleOCR 仓库声明 |
| 11 | **`eprobot_base` / `eprobot_base_cpp`**（ROS 2 底盘驱动） | `cars/car22/src/.../eprobot_base/`（Python 源码）、`cars/car22/rootfs/.../install/eprobot_base_cpp/`（C++ 头文件+二进制） | **ISCC_CAR 队伍**（`iscc@ncut.edu.cn`） | Apache-2.0（`eprobot_base`）；`eprobot_base_cpp` 未声明 | 两者 `package.xml` |
| 12 | ROS 2 / Nav2 / Cartographer / OpenCV 等 | **不在本仓库** | 各自开源项目 | 各自许可 | 由 `apt` 安装 |

> ⚠️ **第 1 项是 GPL-3.0**（copyleft）。这意味着：
> - 你**可以**原样再分发这份源码，但必须保留许可声明、并提供对应源码；
> - 你**不能**把它改成 MIT 再发布；
> - 如果你把 `lslidar_driver` 编进自己的产品并**二进制分发**，GPL-3.0 要求你同时提供该驱动的源码。
> 本仓库只是"存档"，不构成对它的再许可。

---

## 2. 队伍原创的部分（适用 [`LICENSE`](LICENSE) / [`LICENSE-DOCS`](LICENSE-DOCS)）

| 类别 | 位置 | 许可 |
|---|---|---|
| **文档** | `docs/**/*.md`、根 `README.md` / `NOTICE.md` / `SECRETS.md` / 各目录 `README.md`（除厂商自带） | **CC BY-SA 4.0**（见 `LICENSE-DOCS`） |
| **脚本与工具** | `tools/**`、`install/apply_to_car22.sh`、`cars/car21/export_from_sd.sh`、`cars/car22/rootfs/usr/local/bin/iscc-*` | **MIT**（见 `LICENSE`） |
| **队伍写的 ROS 2 / Python 代码** | `eprobot_base/`（Python 驱动，含测试）、`mono8_relay/`（C++ 灰度中继）、`camera_shim/`、`board2_ocr/board2_ocr_worker.py`、`nav_tune_web/`、`goal_speed_limit.py`、`goal_checker_bridge.py`、`iscc_scan_viz.py` | **MIT** |
| **配置与标定** | `cars/*/rootfs/etc/**`（除厂商自带 unit）、`nav2_params.yaml`、`mission_waypoints.yaml`、`pharmacy.yaml` 的**取值**、地图 | **MIT**（内容是我们的调参成果） |

> 注意：`mission_waypoints.yaml` / `nav2_params.yaml` 这些**文件本身属于厂商包**，
> 但**里面的数值**是队伍标定的。我们主张的是数值与文档，不主张文件格式/模板的版权。

---

## 3. 使用限制（对厂商材料）

1. 第 1~12 项材料**仅限个人学习、教学与竞赛复现**，不得用于商业用途或二次分发牟利。
2. 若你是权利人且不希望这些材料出现在本仓库，请提 issue 或联系仓库所有者，**我们会立即移除**（包括必要时重写 git 历史）。
3. 本仓库**不含**任何真实账号密码、SSH 私钥或第三方密钥；WiFi 密码等均为占位符（`PUT_PASSWORD_HERE` / `WIFI_PASSWORD_HERE` / `AP_PASSWORD_HERE`），见 [`SECRETS.md`](SECRETS.md)。

---

## 4. 关于"为什么把厂商二进制也放进来"

这是一个**有意识的取舍**，理由与代价见 [`docs/adr/0005-vendor-binaries-in-repo.md`](docs/adr/0005-vendor-binaries-in-repo.md)：

- 没有这 9 个 ELF，仓库作为"可恢复镜像"就**没有意义**（厂商不给个人源码）；
- 缓解措施：本文件逐项声明 + 可移除承诺 + **凭据一律不入库**（下架时无需清理历史）。

---

## 5. 引用本项目时怎么写

```
ros-autonomous-pharmacy-car（ISCC 智慧药房赛项用车运行时快照）
cxy、xl，2026，宁波大学科学技术学院
代码 MIT / 文档 CC BY-SA 4.0；含第三方材料，详见 NOTICE.md
```

---

## 6. 作者

**cxy**、**xl** —— 2026 年于宁波大学科学技术学院（宁大科院）共同调试完成。
硬件平台与底层固件来自 EPRobot（北京塔洛斯科技），赛项规则来自中国机器人及人工智能大赛组委会。
