# board2_ocr / runtime —— 板二 OCR 的 Python 运行时（未入库，需自建）

> **为什么不在仓库里**：`runtime_arm64/` 有 **276 MB**（纯 Python 包 + 模型依赖），
> 超过仓库"能 clone 得动"的合理体积，且**可以 100% 复现**——所以只入库构建方式，不入库产物。
>
> **它是什么**：一套用 `pip --target` 装出来的 **aarch64 纯 Python 包目录**，不替换系统 Python。
> `run_worker.sh` 通过 `PYTHONPATH` 把它挂到 `/usr/bin/python3` 前面，因此**系统 Python 版本必须匹配**。

---

## 1. 事实卡（2026-11-13 实测于 car22）

| 项 | 值 |
|---|---|
| 目标架构 | **aarch64**（树莓派 4B） |
| 系统 Python | **3.14.4**（Ubuntu 26.04 自带 `/usr/bin/python3`） |
| 目录 | `/home/keyuan22/board2_ocr/runtime_arm64/` |
| 体积 | **276 MB** |
| 顶层包数 | **20 个**（见 [`requirements.lock`](requirements.lock)） |
| 关键版本 | `rapidocr==3.10.0`、`onnxruntime==1.31.1`、`opencv_python_headless==5.0.0.93`、`numpy==2.5.4` |
| 模型 | PP-OCRv6 `det_tiny`(1.8 MB) + `rec_tiny`(4.5 MB)，在 [`../models/`](../models/)（**已入库**） |
| 挂载方式 | `PYTHONPATH=<runtime> /usr/bin/python3 board2_ocr_worker.py` |

> **为什么是 `--target` 而不是 venv**：venv 会绑定绝对路径且要复制解释器；
> `--target` 出来的目录可以整包拷到同架构另一台车直接 `PYTHONPATH` 使用，
> 也是"从旧车拷 276 MB 过去"这个应急方案能成立的原因。

---

## 2. 从零构建（一台空的 arm64 Ubuntu 26.04）

```bash
# 0) 只用 arm64 机器 —— x86 上装出来的是 x86 的 onnxruntime，拷到车上直接段错误
uname -m            # 必须是 aarch64
python3 -V          # 必须是 3.14.x（系统 Python，不要用 pyenv/conda 的解释器）

# 1) 一次性：pip 与基础构建工具
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv   # 后者只用于隔离，不用于产物

# 2) 在仓库这个目录下执行构建脚本（产物落在 runtime_arm64/，约 276 MB）
cd cars/car22/rootfs/home/keyuan22/board2_ocr/runtime
bash build_runtime.sh

# 3) 自证（会用 ../samples 里的 13 张真实牌面跑一遍）
bash ../selftest_arm64.sh
```

`build_runtime.sh` 做的事：
1. 校验 `uname -m` = aarch64、`python3` 主版本 = 3.14；
2. `pip install --target=./runtime_arm64 --no-compile -r requirements.lock`；
3. 装完核对**包数**与关键版本；
4. 打印下一步验证命令。

**依赖的系统包**（`pip` 之外，缺了会报 `libGL.so.1` 或 `libgomp.so.1` 之类）：

| apt 包 | 为什么需要 | 本车版本 |
|---|---|---|
| `python3` | 解释器本体（3.14.4） | Ubuntu 26.04 自带 |
| `python3-pip` | 安装用 | 随系统 |
| `libgomp1` | onnxruntime 的 OpenMP 运行时 | 系统自带 |
| `libglib2.0-0` | opencv-python-headless 在部分镜像上仍需 | 系统自带 |

> `opencv-python-headless` **不需要** `libGL`；如果你看到 `libGL.so.1` 缺失，说明装成了非 headless 版。

---

## 3. 验证方法（三档，从快到严格）

### 3.1 能 import（10 秒）

```bash
PYTHONPATH=$PWD/runtime_arm64 /usr/bin/python3 - <<'PY'
import sys, onnxruntime, cv2, numpy
print("python", sys.version.split()[0])
print("onnxruntime", onnxruntime.__version__)
print("cv2", cv2.__version__)
print("numpy", numpy.__version__)
PY
```
期望：`python 3.14.4 / onnxruntime 1.31.1 / cv2 5.0.0 / numpy 2.5.4`
（`rapidocr` **没有** `__version__` 属性，别用它判断版本——会抛 `AttributeError`。）

### 3.2 能识别（1 分钟，最关键）

```bash
bash ../selftest_arm64.sh
# 或手动喂一张
echo "$PWD/../samples/pass.png" | PYTHONPATH=$PWD/runtime_arm64 /usr/bin/python3 ../board2_ocr_worker.py
```
期望输出：第一行 `READY`，随后每条一张牌面的结果 `FREE` / `BUSY_<n>` / `UNKNOWN`。

**判定标准**（与入库的 13 张样图对照）：

| 样图 | 期望 |
|---|---|
| `pass.png` / `pass_display.png` | `FREE` |
| `wait5/6/7/8/9/10.png` 及 `*_display.png` | 对应的 `BUSY_5` … `BUSY_10` |

> 只要 13 张里有 ≥ 12 张正确，运行时就是健康的（`wait*` 里数字靠 OCR 认，允许偶发 UNKNOWN）。

### 3.3 端到端（在车上）

```bash
sudo systemctl restart eprobot-pharmacy
journalctl -u eprobot-pharmacy -f | grep -i board2
# 触发一次识别
ros2 topic pub --once /pharmacy/board2_control std_msgs/msg/Bool "{data: true}"
ros2 topic echo --once /pharmacy/board2_status
```
期望：`FREE` 或 `BUSY_n`（不是 `UNKNOWN`）。

---

## 4. 三种拿到运行时的办法（按推荐顺序）

| # | 办法 | 条件 | 耗时 |
|---|---|---|---|
| 1 | **本目录 `build_runtime.sh` 从零构建** | 有 arm64 机器 + 网络 | 10~20 min（视网速） |
| 2 | **从旧车整目录拷贝** | 旧车还在、能 SSH | 5 min（`scp -r` 276 MB） |
| 3 | 用厂商镜像里自带的 | 能拿到出厂 SD 镜像 | — |

**从旧车拷贝的命令**：
```bash
scp -r keyuan22@<旧车IP>:~/board2_ocr/runtime_arm64 ~/board2_ocr/
# 注意：scp -r 会把 .so 软链拷成 20 字节文本，拷完用下面这条自查
find ~/board2_ocr/runtime_arm64 -name '*.so*' -size -1k -exec ls -l {} \;
```

---

## 5. 已知坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `ImportError: libGL.so.1` | 装成了非 headless 的 opencv | 用 `opencv_python_headless`（lock 里已是） |
| `Illegal instruction` / 段错误 | 在 x86 上装、拷到 arm64 | 必须同架构构建 |
| `ModuleNotFoundError: rapidocr` | `PYTHONPATH` 没指对 | `run_worker.sh` 里的 `HERE` 必须指向 `board2_ocr/` 根 |
| worker 启动 20 s 才 `READY` | 模型冷加载（正常） | `pharmacy.yaml` 的 `startup_timeout: 15.0` 要够 |
| 识别很慢（>1.5 s/次） | 用了全帧检测路径 | 正常：快路径 ~110 ms，通用路径 ~500 ms |
| 拷过去后 `onnxruntime` 报 `InvalidProtobuf` | 模型文件损坏（scp 中断） | 重新 `sha256sum -c` 校验 `models/` |

---

## 6. 待确认（需向作者索取）

- [ ] 当初 v1 的构建命令是否用了 `--no-compile` / `--no-deps`（影响产物体积，不影响功能）
- [ ] `runtime_arm64/bin/` 里是否有 pip 生成的入口脚本被 worker 依赖（目前 worker 不调用它们）
- [ ] 是否曾打过 `onnxruntime` 的 `libgomp` 替换补丁（本车未见，判断为否）
