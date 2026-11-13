# probe5.sh · 预期输出

**用途**：查**硬件与系统底盘**——SD 卡在不在、网络怎么配的、IMU 设备有没有、温度/降频。

| 项 | 说明 |
|---|---|
| 只读 | ✅ 只 `lsblk`/`cat`/`systemctl is-active`/`vcgencmd`（脚本注释明确写了 no writes / no mounts） |
| 前置 | `export ROBOT_PASS=...`；部分命令需要 `sudo -n` |
| 耗时 | ~10 s |

---

## 正常输出（节选）

```
==== 块设备（看 SD 卡在不在） ====
NAME        MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
mmcblk0     179:0    0 29.7G  0 disk
├─mmcblk0p1 179:1    0  512M  0 part /boot/firmware
└─mmcblk0p2 179:2    0 29.2G  0 part /
--- /dev/sd* ---
none

==== 网络：netplan / NetworkManager ====
01-wlan0.yaml  50-cloud-init.yaml
--- netplan 内容 ---
network:
  version: 2
  wifis:
    wlan0:
      addresses: [10.211.121.22/24]
--- 连接 ---
（nmcli 空 = 没用 NetworkManager）
--- 服务 ---
NetworkManager     inactive
systemd-networkd   active
hostapd            inactive
dnsmasq            inactive
wpa_supplicant     active

==== 当前 IP / 路由 / WiFi ====
10.211.121.22/24 dev wlan0 ...
--- route ---
default via 10.211.121.1 dev wlan0
--- iw ---
Connected to xx:xx:xx (on wlan0)

==== IMU：udev 规则与配置 ====
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d4", ATTRS{serial}=="5C98182597", SYMLINK+="EPRobot_imu", ...
--- 设备 ---
lrwxrwxrwx ... /dev/EPRobot_imu -> ttyACM0
crw-rw-rw- ... /dev/ttyACM0

==== 温度 / 降频 / 频率 ====
temp=52.3'C
throttled=0x0
1500000
4
 21:40:02 up 2:15, 1 user, load average: 0.42, 0.51, 0.48
```

**判据**

| 指标 | 正常 | 不对说明 |
|---|---|---|
| 根分区 | 挂载在 `mmcblk0p2` | 挂到 `sda*` 说明**系统卡不是内置 SD**（可能是 USB 启动） |
| `/dev/sd*` | `none`（平时） | 有 `sda` → 插着读卡器/U 盘。**`.21` 的卡就曾经在这里** |
| `systemd-networkd` | `active` | 本车用 netplan+networkd，不是 NetworkManager |
| `hostapd` / `dnsmasq` | `inactive` | **`.22` 是 STA 模式，本来就该 inactive**；`.21` 才是 AP |
| `/dev/EPRobot_imu` | 存在，指向 `ttyACM0` | 不存在 → udev 序列号不匹配（换过 IMU） |
| `temp` | **< 75°C** | 过高会降频，Nav2 时序抖动 |
| `throttled` | **`0x0`** | 非 0 → 供电不足/过热降频（`0x50000` = 曾经降频过，`0x50005` = 正在降） |
| `scaling_cur_freq` | 1.5~1.8 GHz | 长时间 600 MHz → 省电策略没关（`.21` 有 `cpu-performance.service`，`.22` 没有） |

---

## 典型故障 1：`/dev/EPRobot_imu` 不存在

```
--- 设备 ---
ls: cannot access '/dev/EPRobot_imu': No such file or directory
crw-rw-rw- 1 root dialout 188, 0 ... /dev/ttyACM0
```
→ 设备在，但**别名没建**。九成是换过 IMU，序列号不匹配：
```bash
udevadm info -a -n /dev/ttyACM0 | grep -E 'idVendor|idProduct|serial'
# 拿到的 serial 与规则里的 5C98182597 不同 → 改规则
sudo sed -i 's/ATTRS{serial}=="[^"]*"/ATTRS{serial}="<新的>"/' /etc/udev/rules.d/99-eprobot-h30.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```
详见 `cars/car22/rootfs/etc/udev/rules.d/README.md` §1.2。

## 典型故障 2：`throttled=0x50000`

```
throttled=0x50000
```
→ **曾经**发生过欠压/降频（bit 16 = 曾经 under-voltage，bit 18 = 曾经 throttled）。
| 值 | 含义 |
|---|---|
| `0x0` | 干净 |
| `0x50000` | 历史上欠压过（可能只是开机瞬间） |
| `0x50005` | **正在欠压或降频** → 立刻处理 |

处理：换电源（5V/3A 以上）、换短线、去掉 USB 大功率外设。欠压下 Pi 会无预警重启，
比赛前必须看到 `0x0`。

## 典型故障 3：两个 netplan 文件都在，但 IP 不对

```
01-wlan0.yaml  50-cloud-init.yaml
```
→ **知名坑**：netplan 按文件名字典序合并，`50-cloud-init.yaml` **后读，会覆盖 `01-wlan0.yaml`**。
只看"生效值"：
```bash
sudo netplan get
```
处置见 `docs/竞赛笔记.md` §18.2（推荐删掉 cloud-init 那份 + 禁用 cloud-init 网络配置）。

---

## 什么时候跑这个脚本

- 换车/重刷后第一次开机
- 相机、雷达、IMU 任何一个"设备节点不存在"
- 车莫名重启（查 `throttled`）
- 换 WiFi 环境（查 netplan 生效值）
