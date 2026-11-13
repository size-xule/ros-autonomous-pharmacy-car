# NOTICE · 第三方与厂商材料声明

本仓库为**竞赛与学习用途**的工程快照，包含以下**非本项目原创**的材料。其版权归各自权利人所有，本仓库不主张任何权利，也不提供任何形式的担保。

| 材料 | 位置 | 来源 / 权利方 | 说明 |
|---|---|---|---|
| STM32 底盘固件源码（RT-Thread 工程） | `cars/car22/firmware/chassis_mcu/EPRobot_controller_1.3-*.7z` | EPRobot（北京塔洛斯科技有限公司） | 下位机运动学/PID/舵机控制 |
| 底盘原理图 | `.../EPRobot_base_sch_V1.3.pdf` | 同上 | 硬件设计资料 |
| 底层通信协议表 | `.../EPRobot智能小车底层通信协议.xlsx` | 同上 | 串口帧格式 |
| Orbbec OpenNI2 SDK | `cars/car22/rootfs/opt/oni2-orbbec/` | Orbbec（奥比中光） | Astra 系列深度相机驱动库 |
| 任务层二进制（`f1_mission_node` 等） | `cars/car22/rootfs/opt/eprobot_ws/install/pharmacy_pkg/lib/` | EPRobot 提供 | 无源码，二进制为唯一产物 |
| PP-OCRv6 tiny 模型 | `cars/car22/rootfs/home/keyuan22/board2_ocr/models/` | PaddleOCR / 百度 | 文字识别模型（ONNX） |
| ROS 2 / Nav2 / Cartographer / OpenCV 等 | 不在本仓库 | 各自开源项目 | 通过 apt / colcon 安装 |

## 使用限制

1. 上述厂商材料**仅限个人学习、教学与竞赛复现**，不得用于商业用途或二次分发牟利。
2. 若你是权利人且不希望这些材料出现在本仓库，请提 issue 或联系仓库所有者，我们会立即移除。
3. 本仓库**不含**任何账号密码、SSH 私钥或第三方密钥；WiFi 密码等均为占位符（`WIFI_PASSWORD_HERE`）。

## 本项目原创部分

- `docs/` 下全部文档（竞赛笔记、部署手册、仓库维护说明）
- `install/`、`tools/` 下的脚本
- `cars/car22/rootfs/home/keyuan22/` 下的标定参数、限速脚本、板二 OCR worker、相机中继配置
- `cars/car22/firmware/README.md` 等整理性说明

原创部分建议以 **CC BY-NC-SA 4.0**（署名-非商业性使用-相同方式共享）授权；如需其它许可请与作者联系。

## 作者

**cxy**、**xl** —— 2026 年于宁波大学科学技术学院（宁大科院）共同调试完成。
