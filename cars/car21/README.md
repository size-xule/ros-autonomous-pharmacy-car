# car21 档案（10.211.121.21 / EPRobot1）· 初代机

> **2026-11-13 从 SD 卡只读取出并归档**（卡当时插在 `.22` 的 USB 读卡器上，`/dev/sda2`）。
> 取件方式：`mount -o ro` → `tar -chzf -`（`-h` 解引用软链）→ `umount`。**全程只读，卡未写入一个字节。**
> 车本体目前无卡、开不了机；把卡插回去并开机即恢复。

---

## 1. 身份卡（实测，不是抄来的）

| 项 | 值 | 证据 |
|---|---|---|
| IP（AP 模式） | `10.211.121.21` | `/etc/hostapd/iscc-ap.conf` + `iscc-hotspot.service` 的 `ip addr replace` |
| 主机名 | `EPRobot1` | `<卡>/etc/hostname` |
| **登录账号** | **`ubuntu`**（uid 1000，家目录 `/home/ubuntu`） | `<卡>/etc/passwd` |
| **sudo** | **免密**：`ubuntu ALL=(ALL) NOPASSWD:ALL` | `<卡>/etc/sudoers.d/*` |
| 遗留账号 | `EPRobot`（uid 1001，`/home/EPRobot`） | 从别的车复刻时留下的 |
| 系统 / ROS | Ubuntu 26.04.1 LTS / ROS 2 **Lyrical**（`/opt/ros/lyrical`） | `<卡>/etc/os-release`、`opt/ros/` |
| 工作空间 | `/opt/eprobot_ws` | `opt/eprobot_ws/{src,install}` |
| 相机 | **Astra Pro HD（`2bc5:0501`，有 UVC）** + Astra Pro（`2bc5:0403`） | 用户提供；卡里**没有** `camera_shim` / `relay_ws`，印证不需要 relay |
| 网络模式 | **AP**：自己发热点 | 见 §3 |
| 裁判 ID | `25`（`pharmacy.yaml` 的 `car_id`） | `config/pharmacy.yaml` |
| 状态 | **离线**（无系统卡） | — |

> ⚠️ **`.21` 和历史上的 `.24`（ROS 1 车）都叫 `EPRobot1`** —— 认车只能靠 IP + 账号 + ROS 版本。

---

## 2. 和 `.22` 的六处硬差异（**互抄必翻车**）

| 维度 | car21 | car22 | 影响 |
|---|---|---|---|
| **相机** | Astra Pro HD，**有 UVC**，直出 mono8 | Astra S，**无 UVC**，必须 `openni2-camera + mono8-relay` | 两套相机链不能互换 |
| **WiFi** | **AP**（发 `yaofang`） | **STA**（连 `OnePlusAce5`） | 见 §3 |
| **`board2` 点位** | **`-1.62, 3.76`** | `-0.903, 3.76` | **差 0.72 m**，抄了直接撞墙 |
| **`board1` 点位** | `0.518, 0` | `0.618, 0` | 差 10 cm，二维码大小会变 |
| `C` / `A` / `ac_transit` | `1.47` / `0.605` / `1.49,2.88` | `1.46` / `0.610` / `1.46,2.78` | 差 1~10 cm |
| OCR 路径 | `/home/EPRobot/board2_ocr` | `/home/keyuan22/board2_ocr` | 家目录不同 |
| `pharmacy_pkg` 体积 | **53 MB**（含大量 `.bak`） | 36 MB | .21 的备份更多 |

> 结论：**航点必须按车各自标**。这也解释了为什么 `docs/竞赛笔记.md` §7.5 要列四套值。

---

## 3. ★ WiFi：AP ↔ STA 的**现成实现**（`.22` 上没有这套）

这是本次归档最有价值的发现。`.21` 用 **hostapd + dnsmasq + 一个 oneshot service** 做热点：

```
/etc/hostapd/iscc-ap.conf            ← ssid=yaofang, channel 6, WPA2-PSK, max 8 客户端
/etc/dnsmasq.d/iscc-ap.conf          ← DHCP 池 10.211.121.150–199, domain=iscc
/etc/systemd/system/iscc-hotspot.service
    ExecStartPre: ip link down / addr flush / ip addr replace 10.211.121.21/24 / link up
    ExecStart:    /usr/sbin/hostapd /etc/hostapd/iscc-ap.conf
/etc/netplan/50-cloud-init.yaml      ← 只配 eth0 10.0.0.1/24（有线调试口）
/etc/netplan/99-wlan0-client.yaml.disabled
                                     ← 客户端模式（10.211.121.21 + OnePlusAce5），带 .disabled = 当前不用
/usr/local/bin/iscc-wifi-ap.sh       ← 一键切 AP
/usr/local/bin/iscc-wifi-client.sh   ← 一键切 STA
```

**切换逻辑（脚本原文语义）**

| 动作 | `iscc-wifi-ap.sh` | `iscc-wifi-client.sh` |
|---|---|---|
| netplan | 把 `99-wlan0-client.yaml` 改名成 `.disabled`，`netplan apply` | 重新生成 `99-wlan0-client.yaml`，`netplan apply` |
| 服务 | `disable hostapd` → `enable dnsmasq iscc-hotspot` → `restart iscc-hotspot` | `disable --now iscc-hotspot hostapd dnsmasq` → `ip link down` + `addr flush` |
| 结果 | `wlan0 = 10.211.121.21/24`，发 `yaofang` | `wlan0` 连 `OnePlusAce5`，静态 `.21` |

> ⚠️ **两处不一致，别被注释骗了**：
> 1. `iscc-wifi-ap.sh` 的注释和 echo 写 "SSID **NDKY**"，但 `iscc-ap.conf` 里实际是 **`ssid=yaofang`** —— **真正的 SSID 是 `yaofang`**。
> 2. `iscc-hotspot.service` 的 `Description` 也写 "SSID NDKY"，同样是旧文案。
>
> ⚠️ **密码已脱敏**：`iscc-ap.conf` 的 `wpa_passphrase=AP_PASSWORD_HERE`、`iscc-wifi-client.sh` 里的 `WIFI_PASSWORD_HERE` 都要填真值。

**安全提醒**：`iscc-wifi-ap.sh` 会**当场断掉你正在用的 WiFi**。要在本机（键盘/HDMI）或先挂一条定时回滚（见 `docs/竞赛笔记.md` §18.3）。

---

## 4. 三条 `.22` 上没有（或实现不同）的优化

| 项 | 做什么 | 为什么 |
|---|---|---|
| `cpu-performance.service` | `echo performance > /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` | **锁 CPU 性能模式**，减少 ROS 2 控制环抖动（默认 `ondemand` 会降频到 600 MHz） |
| `wifi-powersave-off.service` | `iw dev wlan0 set power_save off` | 关 WiFi 省电，**降低 DDS 延迟与丢包** |
| **systemd drop-in** | 见下表 | `.22` 把 `Environment=` 直接写在每个 unit 里；`.21` 用 **drop-in** 叠加，改起来不用动原 unit |

**`.21` 的 drop-in（`/etc/systemd/system/<unit>.service.d/`）**

| 文件 | 内容 | 作用 |
|---|---|---|
| `eprobot-{base,imu,nav}.service.d/20-dds-udp.conf`、`lslidar.service.d/20-dds-udp.conf` | `Environment=FASTDDS_BUILTIN_TRANSPORTS=UDPv4` | **根治 `Failed init_port fastdds_port70xx`**（避开 SHM，见竞赛笔记 §6.7） |
| `eprobot-nav.service.d/30-log-level-warn.conf`、`lslidar.service.d/30-log-level-warn.conf` | `Environment=RCUTILS_DEFAULT_LOGGER_DEFAULT_LEVEL=WARN` | **降日志级别**，减少 journal 写入（SD 卡 IO 与 CPU 都省） |
| `dnsmasq.service.d/iscc-ap.conf` | `After=` / `Wants=iscc-hotspot.service` | 保证 dnsmasq 在热点起来之后再起 |

> 这三条比"关 unattended-upgrades"更直接，且**不需要改原 unit**，建议照搬到 `.22`。

---

## 5. 目录 → 车上目标路径

`rootfs/` 下相对路径 = 车上绝对路径。

| 本仓库 | 车上 |
|---|---|
| `rootfs/opt/eprobot_ws/install/pharmacy_pkg/` | `/opt/eprobot_ws/install/pharmacy_pkg/` |
| `rootfs/home/ubuntu/{eprobot_navigation,eprobot_cartographer,maps,nav_tune_web}` | `/home/ubuntu/…` |
| `rootfs/home/ubuntu/lifted_pid_sweep.py` | 架空 PID 扫描工具 |
| `rootfs/home/ubuntu/iscc_perf_opt_backup_*` | 性能优化**前**的 `nav2_params.yaml` 备份（26 KB）+ 打包 |
| `rootfs/etc/systemd/system/*.service` | `/etc/systemd/system/` |
| `rootfs/etc/{hostapd,dnsmasq.d,netplan,default,udev,chrony,wpa_supplicant}/` | 同路径 |
| `rootfs/usr/local/bin/{iscc-wifi-ap.sh,iscc-wifi-client.sh,lslidar-ctl}` | `/usr/local/bin/` |
| `src/opt_eprobot_ws_src/*` | `/opt/eprobot_ws/src/`（**要 colcon build**） |

**未归档的两个 unit**：`hostapd.service`、`wpa_supplicant.service` 是指向 `/lib/systemd/system/` 的绝对软链，跨文件系统解引用会指错，故跳过 —— `apt install hostapd` / `wpasupplicant` 会重建。

---

## 6. 一个重要的"坏消息"：卡里**没有 `pharmacy_pkg` 源码**

`opt/eprobot_ws/src/` 里只有 7 个包，和 `.22` 完全一样：

```
cartographer  cartographer_ros  eprobot_base  lslidar_ros2
serial_ros2   yesense_interface  yesense_std_ros2
```

**没有 `pharmacy_pkg`。** 说明：

- 之前希望"从 `.21` 的卡里捞到任务层源码"——**落空了**；
- 任务层（`f1_mission_node` 等）**依然只有二进制**，两车一样；
- 想拿源码只能找厂商/队友要 colcon 工程。

顺带确认：`.21` 的 `f1_mission_node` 是 **2,534,200 字节**，与 `.22` 的完全相同（同一份二进制，差异全在 YAML）。

---

## 7. 这台车的服务表

| unit | 作用 |
|---|---|
| `eprobot-base` / `eprobot-imu` / `lslidar` / `eprobot-nav` / `eprobot-pharmacy` | 与 `.22` 同名同义 |
| `eprobot-slam` / `eprobot-carto` | 建图（与 nav 互斥） |
| `iscc-hotspot` | **AP 热点（`.22` 没有）** |
| `hostapd` / `dnsmasq` | 热点依赖（`iscc-hotspot` 直接调 hostapd） |
| `cpu-performance` | **锁性能模式（`.22` 没有）** |
| `wifi-powersave-off` | **关 WiFi 省电（`.22` 没有）** |
| `nav-tune-web` | 网页调参 8766 |

---

## 8. 怎么用这份归档

**只取配置看差异**（推荐）：
```bash
diff -r cars/car21/rootfs/home/ubuntu/eprobot_navigation/config \
        cars/car22/rootfs/home/keyuan22/eprobot_navigation/config
```

**恢复这台车**：把卡插回去、开机，先 `iscc version` 确认 IP/domain，再按 `docs/新车部署手册.md` 的思路（但注意相机链不同：**它不需要 relay**）。

**从卡里再导出**：`export_from_sd.sh`（在本目录，跑在 `.22` 上，只读 + trap 自动 umount）。

---

## 9. 版权

`pharmacy_pkg` 二进制、`eprobot_*` 源码包均为 **EPRobot（北京塔洛斯科技）** 材料，见根目录 [`NOTICE.md`](../../NOTICE.md)。
