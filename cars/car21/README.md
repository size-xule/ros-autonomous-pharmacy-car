# car21（预留位）· 10.211.121.21 / EPRobot1

> **本目录现在是空的占位。** 因为 `.21` 的系统卡被拔下来插在 `.22` 的 USB 读卡器上，
> 车本体无系统、开不了机，没法直接 ssh 拉文件。

---

## 1. 这台车是什么

| 项 | 值 |
|---|---|
| IP | `10.211.121.21` |
| 主机名 | `EPRobot1`（⚠️ 与历史 ROS 1 车 `.24` 同名，**别用 hostname 认车**） |
| 账号 / 密码 | `ubuntu` / `<REDACTED>` |
| 系统 / ROS | Ubuntu 26.04.1 / ROS 2 Lyrical |
| 工作空间 | `/opt/eprobot_ws` |
| 家目录 | `/home/ubuntu` |
| 相机 | **Astra Pro HD**（`2bc5:0501`，**有 UVC**）+ Astra Pro（`2bc5:0403`） |
| 相机链 | **无 relay**，相机直出 `mono8` |
| WiFi | **AP 模式**：自己发 `yaofang`（密码 `<REDACTED>`） |
| 任务包 | `pharmacy_pkg`（二进制，与 `.22` 同源但参数不同） |
| 状态 | **离线**（无卡） |

**和 `.22` 的三处关键差异**（部署/排障时必须分开看）
1. **相机不同** → `.22` 的 `openni2-camera + mono8-relay` 这套**不要**装到 `.21`；它有 UVC，用 `v4l2_camera` 或厂商 launch。
2. **网络模式不同** → `.21` 是 AP（车发信号），`.22` 是 STA（连热点）。
3. **参数可能不同** → 航点、限速、曝光都是各自标定的，**不要互抄**。

---

## 2. 怎么把 `.21` 的内容填进来

### 步骤 A：在 `.22` 上只读挂载 `.21` 的卡

```bash
ssh keyuan22@10.211.121.22

lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT
#   要看到 sda1 vfat system-boot + sda2 ext4 writable，且都无挂载点

sudo mkdir -p /mnt/sd21
sudo mount -o ro /dev/sda2 /mnt/sd21     # ★ 必须 -o ro
sudo cat /mnt/sd21/etc/hostname          # 确认是 EPRobot1，别读错卡
```

### 步骤 B：用本目录的脚本导出成同样的结构

```bash
# 在 .22 上（脚本会 read-only 读取，输出到 /tmp/car21-export.tgz）
bash export_from_sd.sh

# 在主机上拉回来
scp keyuan22@10.211.121.22:/tmp/car21-export.tgz .
mkdir -p /tmp/car21 && tar xzf car21-export.tgz -C /tmp/car21
# 然后按 cars/car22/ 的布局搬进本目录
```

### 步骤 C：卸载（**必做**）

```bash
sudo umount /mnt/sd21
lsblk -o NAME,MOUNTPOINT | grep sda      # 挂载点必须为空
```

> ⚠️ 不卸载就拔读卡器 = 脏文件系统，`.21` 开机可能 `fsck` 失败甚至起不来。

---

## 3. 卡里最值得捞的三样

| # | 东西 | 为什么值钱 |
|---|---|---|
| 1 | `/opt/eprobot_ws/src/` 里**有没有 `pharmacy_pkg`** | 如果有 → 那就是 `.22` 缺的**任务层源码**，直接解决"只能改参数"的困境 |
| 2 | `/boot/firmware/firstrun.sh`、`/etc/hostapd/hostapd.conf`、`/etc/systemd/system/*hotspot*` | **`yaofang` 热点是怎么配出来的**（竞赛笔记 §18.3 的"路线①"） |
| 3 | `~/eprobot_navigation/{config,scripts}`、`.../config/mission_waypoints.yaml` | `.21` 的**真实标定值**（航点/限速/曝光），和 `.22` 对比就知道哪些是"车特性"、哪些是"场地特性" |

顺带能确认：`.21` 的 `ROS_DOMAIN_ID`（多车同网必须分域，见竞赛笔记 §18.4）。

---

## 4. 填进来之后的目标结构

```
cars/car21/
  README.md                 ← 本文件（到时候补上"实测参数"）
  rootfs/
    opt/eprobot_ws/install/pharmacy_pkg/...
    home/ubuntu/<REDACTED>_navigation/...
    etc/systemd/system/...
  src/
    opt_eprobot_ws_src/...
  MANIFEST.md               ← 从卡里导出的文件清单 + md5
```
