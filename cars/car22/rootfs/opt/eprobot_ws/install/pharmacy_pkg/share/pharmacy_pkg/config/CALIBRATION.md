# 相机标定说明（CALIBRATION）

> **一句话结论：本车目前*没有*任何标定文件——没有内参、没有畸变系数，整条识别链也不做去畸变。**
> 这在当前流程下是**能跑的**（原因是相对位置识别，见 §3），但换镜头/换相机/换安装角度后必须重标或重新验一遍。

---

## 1. 事实卡（2026-11-13 核对）

| 项 | 值 | 来源 |
|---|---|---|
| 相机型号 | **Orbbec Astra S**（`2bc5:0402`，USB2.0，**无 UVC**） | `lsusb` |
| 取流方式 | Orbbec **OpenNI2** SDK（`/opt/oni2-orbbec`） | `usr/local/bin/openni2-camera` |
| 分辨率 | **640 × 480** | 同上 / `camera.yaml` |
| 输出话题（上游） | `/camera/color/image_raw`，**rgb8**，921,600 B/帧 | `openni2-camera` 的 `-r rgb/image_raw:=color/image_raw` |
| camera_info | **有发布**：`/camera/color/camera_info`（`-r rgb/camera_info:=color/camera_info`） | 同上 |
| 输出话题（下游） | `/camera/rgb/image_raw`，**mono8**，307,200 B/帧，~7.6 Hz | `mono8-relay`（`max_fps:=10`） |
| **曝光** | `-p auto_exposure:=true`（自动） | 同上 |
| **内参 / 畸变** | **无**（`camera_info_url: ''`，仓库里没有任何 `*.yaml` 标定文件） | `config/camera.yaml`、`git ls-files` |
| 坐标系 | `camera_rgb_frame` / `camera_ir_frame` / `camera_depth_frame` | 同上 |

> ⚠️ **两处容易搞混**：
> 1. `config/camera.yaml` 里的 `video_device: /dev/video0` / `pixel_format: YUYV` 是**另一条链**（UVC 相机，`.21` 那种）的配置，
>    **不是 Astra S 这条链**。Astra S 根本不出 `/dev/video0`（无 UVC）。
> 2. `camera.yaml` 的 `camera_info_url: ''` 只对那条 v4l2 链生效；**Astra S 这条链的 camera_info 是驱动自己填的**（OpenNI2 出厂内参）。
>    也就是说：**有 camera_info 消息，但没有做标定校正**。

---

## 2. 为什么"没标定也能跑"

| 消费者 | 用图做什么 | 为什么不需要内参 |
|---|---|---|
| `/detect_qrcode`（QR） | 找码 → 解码 → **只取码里的数字** | 不需要把像素反投影到 3D；码面基本正对相机 |
| `/pharmacy_board2(_ocr)` | 找亮面板 → OCR 认字 | 同上，纯 2D 文本 |
| `goal_speed_limit` | 不用图 | — |

**换句话说**：整条链是"**看画面内容**"，不是"**测距离**"。畸变会让边缘的码略微变形，
但只要码足够大（≥ 80 px）、在画面中部，解码不受影响。

**这解释了为什么历史上没人做标定**——不是漏了，是当时不需要。

---

## 3. 什么时候**必须**重标（或至少重验）

| 触发条件 | 为什么 | 要做什么 |
|---|---|---|
| 换镜头 / 换同型号但不同批次相机 | 焦距与畸变会变 | 标定内参 + 畸变 |
| 相机**安装角度/高度**改变 | 码在画面中的位置与透视变形变了 | 先重验识别；不行再标定 |
| 二维码/文字牌出现在**画面边缘** | 边缘畸变最大（Astra S 的 640×480 边缘桶形畸变肉眼可见） | 标定 → 加 `image_proc` 去畸变，或改变停车点让码居中 |
| 需要**尺寸/距离**信息（目前不需要） | 2D 像素→米 必须内参 | 标定 |
| 从 Astra S 换成有 UVC 的型号（如 Astra Pro HD） | 整条链换掉 | 见 `docs/竞赛笔记.md` §6.5，**不要去畸变前先换链** |

> **判断顺序**：先问"识别率掉了多少"。掉 5% 以内 → 调曝光/停车点；掉一半 → 查 mono8 链；
> 只有"码明明很大却总在画面边上认不出"才是畸变问题。

---

## 4. 怎么标定（ROS 2 标准流程）

```bash
# ① 装标定工具（只在需要标定时才装）
sudo apt install -y ros-lyrical-camera-calibration

# ② 打一张棋盘格（9×6 内角点，方格 25 mm），贴在硬板上保证平整
#    文件在 /opt/ros/lyrical/share/camera_calibration/doc/ 里也有现成的

# ③ 起相机（用 OpenNI2 那条链，不要起 mono8-relay）
sudo systemctl stop mono8-relay
sudo systemctl restart openni2-camera
ros2 topic hz /camera/color/image_raw        # 确认有帧（约 15 Hz）

# ④ 起标定器
ros2 run camera_calibration cameracalibrator \
  --size 9x6 --square 0.025 \
  --ros-args -r image:=/camera/color/image_raw \
             -r camera:=/camera/color
```

**操作**：把棋盘在画面里**上下左右前后**各走一遍，直到 `X`/`Y`/`Size`/`Skew` 四条都变绿 →
点 `CALIBRATE` → 点 `SAVE`。

**产物位置**：`/tmp/calibrationdata.tar.gz`，解开后有 `ost.yaml`（= `camera_info` 的 YAML 形式）。

**装到车上**：
```bash
tar xzf /tmp/calibrationdata.tar.gz -C /tmp/
sudo cp /tmp/ost.yaml /home/keyuan22/board2_ocr/../camera_calib_640x480.yaml   # 放哪都行，记住路径
```
然后把路径填进**这条链**的相机配置（注意：Astra S 走 OpenNI2，参数在 `openni2-camera` 的 `-p` 里，
不是 `config/camera.yaml`）：
```bash
# 编辑 /usr/local/bin/openni2-camera，在 ExecStart 的 -p 列表里加：
#   -p camera_info_url:=file:///home/keyuan22/camera_calib_640x480.yaml
sudo systemctl daemon-reload && sudo systemctl restart openni2-camera
```

> ⚠️ 改 `openni2-camera` 属于改**已验证运行的文件**——按仓库红线，要么不改，
> 要么改完立刻备份 + 提交 + 实车验证（见 `docs/仓库结构与维护.md` §2）。

**验收**：
```bash
ros2 topic echo --once /camera/color/camera_info | head -20   # K/D 不再是 0
# 标定器输出里看 'avg reprojection error'，应 < 0.5 px（>1.0 说明棋盘不平或拍得不够）
```

---

## 5. 记录模板（标了就填）

```markdown
## 相机标定记录 2026-11-13 / car22

- 相机：Astra S（SN `17120410825`，FW `RD109Y-007`）
- 镜头：原装（未换）
- 棋盘：9×6 内角点 / 方格 25 mm / A4 打印贴在 3 mm 亚克力上
- 分辨率：640×480
- 标定工具：ros-lyrical-camera-calibration
- 平均重投影误差：0.31 px
- 产出文件：`/home/keyuan22/camera_calib_640x480.yaml`
- 是否启用：**否**（仅存档；当前链不做去畸变）
- 备注：边缘畸变肉眼可见，但码居中时识别率 9/9
```

**关键内参（填在上面记录的下面，便于对比）**
| 参数 | 值 |
|---|---|
| `fx` / `fy` | 待填 |
| `cx` / `cy` | 待填 |
| 畸变模型 | `plumb_bob`（k1 k2 p1 p2 k3） |
| `k1` / `k2` / `p1` / `p2` / `k3` | 待填 |

---

## 6. 换车后要不要重标？

| 场景 | 要重标吗 | 理由 |
|---|---|---|
| 同型号新车 + 同安装位置 | **不必**（但要用新车自己的 SN 验一遍识别） | 出厂内参一致 |
| 同型号但换了相机本体 | 建议重标 | 个体差异（尤其 k1） |
| 换了安装高度/俯仰角 | **先重验识别**，识别率没掉就不用标 | 标定管的是镜头，不管外参 |
| 换成有 UVC 的相机（如 `.21`） | **不用 ROS 标定**，但整条链要换（`v4l2_camera` + `camera.yaml` 的 `camera_info_url`） | 见笔记 §6.5 |

---

## 7. 已知怪点

| 怪点 | 说明 | 影响 |
|---|---|---|
| `usr/local/bin/openni2-camera` **最后一行以 `\` 结尾就 EOF 了**（29 行 / 1253 B） | 车上原文就是这样（md5 `9f9c6913…`，仓库副本一致）。bash 会把 `\`+换行当作续行接一个空行，**照常执行** | 无（已实测 `echo hi \` + EOF 能正常执行）；但**别在这行后面追加参数**，否则会拼到同一条命令尾部 |
| 注释说"manual exposure 200 是标定值"，但实际参数是 `auto_exposure:=true` | 注释描述的是**曾经试过**的手动方案；当前用自动曝光 | 若板二过曝，用 `PHARMACY_EXPOSURE` 覆盖（脚本注释里的说法）→ **需实车确认该变量是否真的被读取**（列在待确认） |
| `config/camera.yaml` 与 Astra S 无关 | 见 §1 的两处容易搞混 | 改它**不会**影响本车相机 |

---

## 8. 待确认（需向作者索取）

- [ ] `PHARMACY_EXPOSURE` 环境变量是否真的被 `openni2_camera_driver` 读取（脚本注释提到，但参数表里只有 `auto_exposure`）
- [ ] 是否曾用出厂内参以外的标定（若曾标过，`ost.yaml` 在哪）
- [ ] Astra S 的固件 `RD109Y-007` 是否有已知的曝光限制
