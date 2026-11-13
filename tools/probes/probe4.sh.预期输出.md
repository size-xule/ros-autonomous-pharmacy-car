# probe4.sh · 预期输出

**用途**：查**任务层的行为线索**——`eprobot-pharmacy` 到底怎么起的、二进制里有哪些字符串、
板二相关关键词在不在。属于"没有源码时的取证工具"。

| 项 | 说明 |
|---|---|
| 只读 | ✅ `systemctl cat` + `strings` + `ls` |
| 前置 | `export ROBOT_PASS=...` |
| 耗时 | ~15 s（`strings` 扫 2.5 MB 二进制） |

---

## 正常输出（节选）

```
==== eprobot-pharmacy.service ExecStart ====
Environment=JUDGE_CAR_ID=24
Environment=PHARMACY_IMAGE_TOPIC=/camera/rgb/image_raw
EnvironmentFile=-/etc/default/eprobot-pharmacy
ExecStart=/bin/bash -lc "source /opt/ros/lyrical/setup.bash && ... exec ros2 launch pharmacy_pkg competition.launch.py start_camera:=false judge_car_id:=$JUDGE_CAR_ID image_topic:=$PHARMACY_IMAGE_TOPIC"

==== f1_mission_node 里的语音相关字符串 ====
car_speech       1
paplay           2
aplay            1
speech_status    3
speech_ready     1
loaded           12
WAV              4

==== f1_mission_node 是否含 board2 后端名字 ====
ac_transit
board2
board2_exit
board2_timeout
C>B
A>B
...

==== pharmacy_speech_node 是否被实际启动过 ====
-rwxr-xr-x ... judge_tcp_node
-rwxr-xr-x ... pharmacy_qr_node
-rwxr-xr-x ... pharmacy_speech_node
...
--- board2_ocr 目录 ---
board2_ocr_worker.py
models
runtime_arm64
samples
```

**关键判据**

| 观察 | 含义 |
|---|---|
| `Environment=JUDGE_CAR_ID=24` **但** `EnvironmentFile=/etc/default/eprobot-pharmacy` | 实际生效的是文件里的 **25**；**只改 unit 里的 24 是白改** |
| `PAplay`/`aplay` 计数 > 0 | 语音节点是**调外部播放器**，不是自己解码 → `audio` 组/声卡权限会影响 |
| `strings` 里有 `ac_transit` | 任务层**真的读**这个键 → 删了会改变行为（C→A） |
| `strings` 里没有某个键 | 说明那个键**不被读取**，写进 YAML 也不会生效 |

---

## 典型故障 1：`strings` 命令报 `No such file`

```
==== f1_mission_node 里的语音相关字符串 ====
strings: '/opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg/f1_mission_node': No such file
```
→ **二进制被删或路径变了**。立刻：
```bash
cd /opt/eprobot_ws/install/pharmacy_pkg/lib/pharmacy_pkg && bash verify.sh
```
（仓库里有 `SHA256SUMS`，`verify.sh --remote` 也能直接比对车上）

## 典型故障 2：`board2_ocr` 目录里没有 `runtime_arm64`

```
--- board2_ocr 目录 ---
board2_ocr_worker.py
models
samples
requirements.txt
run_worker.sh
```
→ OCR 运行时没装（正常的新车状态）。按 `runtime/README.md` 构建或从旧车拷 276 MB。
**在此之前板二识别一定失败**，日志会报 `ModuleNotFoundError: rapidocr`。

## 典型故障 3：`systemctl cat` 输出里没有 `EnvironmentFile`

```
==== eprobot-pharmacy.service ExecStart ====
ExecStart=... judge_car_id:=$JUDGE_CAR_ID ...   （但没有 EnvironmentFile 行）
```
→ `/etc/default/eprobot-pharmacy` 没被引用，`JUDGE_CAR_ID` 就取 unit 里的 **24**（错误档位）。
修：把 `EnvironmentFile=-/etc/default/eprobot-pharmacy` 加回 unit（对照 `cars/car22/rootfs/etc/systemd/system/eprobot-pharmacy.service`）。

---

## 怎么用这个脚本回答"某个 YAML 键到底有没有用"

```bash
# 想确认 mission_waypoints.yaml 里的某个键是否被读
ssh ... 'strings /opt/.../f1_mission_node | grep -x "键名"'
```
有 → 大概率被读；没有 → **写了也没用**（常见于历史遗留键）。
