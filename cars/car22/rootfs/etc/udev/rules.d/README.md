# udev 规则说明（/etc/udev/rules.d）

> 本目录 4 个文件，**只有 3 个是本项目的**，另 1 个是 Ubuntu 发行版自带的。
> 换车/换硬件后，最容易失效的就是这里的**序列号绑定**。

---

## 1. 逐条说明

| 文件 | 大小 | 属于 | 匹配依据 | 建出的设备名 | 换车后会不会失效 |
|---|---:|---|---|---|---|
| [`99-eprobot-base.rules`](99-eprobot-base.rules) | 267 B | 本项目 | **内核名** `ttyAMA0` | `/dev/EPRobot_base` | ❌ **不会**（树莓派 4B 的板载 UART 恒为 `ttyAMA0`） |
| [`99-eprobot-h30.rules`](99-eprobot-h30.rules) | 203 B | 本项目 | **USB 序列号** `5C98182597` + VID:PID `1a86:55d4` | `/dev/EPRobot_imu` | ✅ **会**（每颗 IMU 序列号不同） |
| [`99-orbbec.rules`](99-orbbec.rules) | 71 B | 本项目 | **VID** `2bc5`（所有 Orbbec 设备） | 无（只改权限） | ❌ 不会（同系列相机都能匹配） |
| [`70-snap.snapd.rules`](70-snap.snapd.rules) | 63 KB | **Ubuntu snapd 自带** | 大量 snap 接口规则 | — | — |

### 1.1 底盘串口

```
SUBSYSTEM=="tty", KERNEL=="ttyAMA0", SYMLINK+="EPRobot_base", MODE="0666", GROUP="dialout"
```

- **为什么用 `KERNEL==` 而不是序列号**：树莓派 4B 的硬件 UART 永远叫 `ttyAMA0`，不需要区分。
- 后果：`eprobot-base.service` 的 `Group=dialout` + 这条规则，保证 **`keyuan22` 免 sudo 打开串口**。
- ⚠️ **和蓝牙的冲突**：如果启用板载蓝牙（`dtoverlay=disable-bt` 没写），`ttyAMA0` 会被蓝牙占用 →
  串口打不开。检查：`ls -l /dev/serial*`、`cat /boot/firmware/config.txt | grep disable-bt`。

### 1.2 H30 IMU（**换车必改**）

```
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d4", ATTRS{serial}=="5C98182597", SYMLINK+="EPRobot_imu", MODE="0666", GROUP="dialout"
```

| 字段 | 含义 | 本车值 |
|---|---|---|
| `idVendor:idProduct` | CH343 USB 转串口芯片 | `1a86:55d4` |
| `ATTRS{serial}` | **IMU 内部 USB 序列号**（不是 CP210x 那种芯片序列号） | `5C98182597` |
| `SYMLINK` | 稳定设备名 | `/dev/EPRobot_imu` → 实际 `/dev/ttyACM0` |

**失效表现**：`/dev/EPRobot_imu` 不存在 → `eprobot-imu` 起不来 → `/imu/data` 没数据 →
建图会歪、EKF 只剩轮式里程（转弯时定位漂）。

**怎么查新 IMU 的序列号**：
```bash
# 插上 IMU，找出它的 ttyACM*
ls -l /dev/ttyACM* /dev/serial/by-id/
udevadm info -a -n /dev/ttyACM0 | grep -E 'idVendor|idProduct|serial' | head -6
```
或直接看 USB 层（更可靠，不受 tty 编号影响）：
```bash
for d in /sys/bus/usb/devices/*/; do
  [ -f "$d/idVendor" ] || continue
  v=$(cat "$d/idVendor"); p=$(cat "$d/idProduct"); s=$(cat "$d/serial" 2>/dev/null)
  [ "$v" = "1a86" ] && echo "$d  $v:$p  serial=$s"
done
```

**改法**（只改 `serial` 那一处）：
```bash
sudo cp -p /etc/udev/rules.d/99-eprobot-h30.rules ~/99-eprobot-h30.rules.bak_$(date +%s)
sudo sed -i 's/ATTRS{serial}=="[^"]*"/ATTRS{serial}="<新序列号>"/' /etc/udev/rules.d/99-eprobot-h30.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
ls -l /dev/EPRobot_imu        # 应出现
```

> 也可用**端口号绑定**（`KERNEL=="ttyACM0"`）：简单但脆弱——插拔顺序一变就指错设备。**不推荐**。

### 1.3 Orbbec 相机

```
SUBSYSTEM=="usb", ATTR{idVendor}=="2bc5", MODE="0666", GROUP="plugdev"
```

- 只改权限（让 `keyuan22` 能直接读写 USB 设备），**不建别名**。
- 注意这里是 `ATTR` 不是 `ATTRS`：只匹配设备自身节点，不向上遍历父设备。
- `2bc5` 覆盖 Astra 全系（`0402` Astra S / `0403` Astra Pro / `0501` Astra Pro HD），**换同系列相机不用改**。

---

## 2. 换车检查清单（按顺序做）

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | 规则已加载 | `udevadm control --reload-rules && udevadm trigger` | 无输出（成功） |
| 2 | 底盘串口 | `ls -l /dev/EPRobot_base` | 指向 `ttyAMA0` |
| 3 | IMU | `ls -l /dev/EPRobot_imu` | 指向 `ttyACM0`（**没有就是序列号没改**） |
| 4 | 权限 | `ls -l /dev/EPRobot_base /dev/EPRobot_imu` | `crw-rw-rw-` 或组为 `dialout` |
| 5 | 用户组 | `id -nG` | 含 `dialout`（缺了 → `sudo usermod -aG dialout <user>`，**要重新登录**） |
| 6 | 相机 | `lsusb \| grep 2bc5` | 能看到 `2bc5:0402` |
| 7 | 规则是否被覆盖 | `udevadm test /sys/class/tty/ttyACM0 2>&1 \| grep EPRObot` | 能看到 `EPRobot_imu` |

---

## 3. `udevadm info` 怎么用（定位失效规则的标准动作）

```bash
# ① 看某个设备节点的全部属性（含父设备，ATTRS 就靠这些）
udevadm info -a -n /dev/ttyACM0

# ② 只关心能用来匹配的字段
udevadm info -a -n /dev/ttyACM0 | grep -E 'KERNELS|SUBSYSTEMS|ATTRS\{(idVendor|idProduct|serial|manufacturer|product)\}'

# ③ 模拟应用规则（不真的改设备），看哪条命中
udevadm test /sys/class/tty/ttyACM0 2>&1 | grep -iE 'EPRobot|link'

# ④ 看 USB 层（更稳，tty 编号变了也能找到）
udevadm info -a -n $(readlink -f /dev/ttyACM0)
```

> **判断技巧**：如果 `udevadm info -a` 里 `ATTRS{serial}` 与规则里的值**不一致**，
> 那就是换过硬件——改规则里的值即可，别去改代码。

---

## 4. 关于 `70-snap.snapd.rules`

- 这是 **Ubuntu 自带的 snapd 规则**（63 KB，数百条），因为打包时整目录一起取了，所以出现在本仓库。
- **它不是本项目的内容**，装到新车上也不会改变任何行为（新车的 snapd 本来就有同名文件）。
- 本仓库**故意不删**它：删了等于"改动 rootfs 内容"，而它是发行版文件，删不删都不影响运行。
  真正需要时，`apt install --reinstall snapd` 会重建。
- 判断一个规则是否本项目的：看文件大小和注释——**我们的规则都有中文/英文注释且 < 300 B**。

---

## 5. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| `/dev/EPRobot_imu` 不存在 | 序列号变了 / 规则没 reload | §1.2 查序列号并改 |
| 串口 `Permission denied` | 用户不在 `dialout` 组 / 规则没生效 | `sudo usermod -aG dialout $USER` 后重登；`udevadm trigger` |
| `/dev/EPRobot_base` 指向 `ttyS0` | 板载蓝牙占了 `ttyAMA0` | 在 `config.txt` 加 `dtoverlay=disable-bt` |
| 相机能识别但打不开 | 权限没给（`99-orbbec.rules` 没生效） | `ls -l /dev/bus/usb/*/*` 看权限；`udevadm trigger` |
| 规则改了没反应 | 只 `reload` 没 `trigger`，或设备没重插 | 两条都跑；必要时 `echo 0 > /sys/bus/usb/.../authorized` 重枚举 |
| 插了两个 CH343 设备 | 都是 `1a86:55d4`，靠序列号区分 | 正确；规则里已绑定序列号 |

---

## 6. 同步回仓库

```bash
# 在车上改完，把文件拉回来
scp keyuan22@10.211.121.22:/etc/udev/rules.d/99-eprobot-h30.rules \
  cars/car22/rootfs/etc/udev/rules.d/

git add cars/car22/rootfs/etc/udev/rules.d/99-eprobot-h30.rules
git commit -m "fix(car22): 更新 H30 udev 序列号为 <新值>"
```

> ⚠️ 仓库里的这份是**成品镜像**，`apply_to_car22.sh` 会按路径覆盖到 `/etc/udev/rules.d/`。
> 换车时若 IMU 序列号不同，**改仓库这份**（而不是只在车上改），否则下次铺车又变回去。
