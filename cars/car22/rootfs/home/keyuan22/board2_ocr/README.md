# Board-2 化验区牌子 OCR 识别包

用「定位白板 → 裁下排文字 → 只跑识别模型」的方式读出
`化验区空闲中 / 化验区忙碌中，需等待 N 秒`，输出和 mission 一致的
`FREE` / `BUSY_<N>`。

## 为什么不是整帧 OCR

整帧跑 PP-OCR 的检测 + 识别：

- x86 约 0.6–1.1 s/帧；
- Pi 4 会到数秒，board2 的 8 s 超时窗口很紧。

牌子是固定的两行版式，先用轻量的轮廓逻辑找到白板、裁出下面一行，
再直接喂给识别模型（不跑检测、不跑角度分类）：

- x86 约 **12 ms/帧**；
- 对白天、偏暗、模糊、75%/50% 缩放、JPEG q65 共 67 张图 **全部正确**；
- 不再需要为每个新等待秒数加模板。

## 目录

| 路径 | 说明 |
| --- | --- |
| `board2_ocr_worker.py` | 识别主程序，兼 ROS worker 协议 |
| `run_worker.sh` | 给 C++ 节点用的启动包装（设置 `PYTHONPATH`） |
| `selftest_arm64.sh` | 在车上直接跑样例自测 |
| `runtime_arm64/` | Python 3.14 / aarch64 依赖（rapidocr 3.10.0 + onnxruntime 1.31.1 + OpenCV headless + 模型） |
| `samples/` | 13 张样例（6 张白天实拍 + 7 张显示模板） |
| `requirements.txt` | 在 x86/其他机器上用 venv 安装时使用 |

模型是 PP-OCRv6 small，已经打进 `runtime_arm64/rapidocr/models/`，运行时不需要联网。

## 车上使用

```sh
# 解包（示例路径）
mkdir -p /home/EPRobot/board2_ocr
tar -xzf board2_ocr_py314_arm64_20261028.tar.gz \
    -C /home/EPRobot/board2_ocr --strip-components=1

# 自测：应输出 13/13 correct
/home/EPRobot/board2_ocr/selftest_arm64.sh

# 单张
PYTHONPATH=/home/EPRobot/board2_ocr/runtime_arm64 \
  /usr/bin/python3 /home/EPRobot/board2_ocr/board2_ocr_worker.py \
  --image /home/EPRobot/board2_ocr/samples/wait8.png
```

不用建 venv、不用 pip：`runtime_arm64` 就是给系统 Python 3.14 用的
`PYTHONPATH` 目录。占用约 270 MB，解包后建议放在 `/home/EPRobot/`。

## 接到 ROS 节点

`competition.launch.py` 已经留了 OCR 后端，只需要把两个路径指过来：

```sh
ros2 launch pharmacy_pkg competition.launch.py \
  board2_backend:=rapidocr \
  ocr_python:=/home/EPRobot/board2_ocr/run_worker.sh \
  ocr_worker:=/home/EPRobot/board2_ocr/board2_ocr_worker.py
```

节点会把每帧写成 PNG，把路径一行发给 worker；worker 回一行
`FREE` / `BUSY_<n>` / `UNKNOWN`。`pharmacy.yaml` 里 OCR 节点已经是
`need=1`、`scan_period=0.1`、`request_timeout=5.0`，适合这个速度。

## 协议（自己写节点时）

- 启动后 stdout 先输出一行 `READY`；
- 之后每输入一行 PNG 路径，输出一行状态；
- 输入 `QUIT` 退出；
- 诊断信息只写 stderr。

## 实测

| 数据 | 结果 |
| --- | --- |
| `samples/` 13 张 | 13/13，p50 12 ms（x86） |
| 显示模板退化集（模糊/缩放/JPEG）30 张 | 30/30，p50 11 ms |
| 白天实拍退化集 24 张 | 24/24，p50 11 ms |
| aarch64 运行时（qemu 模拟） | 13/13 正确 |

车上原生耗时还没测；按 x86 的 12 ms 估算，Pi 4 单核大约 60–150 ms，
仍低于 7.4 fps 相机 135 ms 的帧间隔。

## 限制

- 白板占画面过大或强逆光时，白板定位可能失败，会退回整帧检测+识别
  （结果仍正确，但耗时约 0.6–1 s）。可用 `--no-fallback` 关掉兜底。
- 只解析 `FREE` 和 `BUSY_1..99` 两类状态；其它牌子会被判为 `UNKNOWN`。
- 数字归一化处理了全角数字和 `O/o → 0`，但不做通用文字理解。
