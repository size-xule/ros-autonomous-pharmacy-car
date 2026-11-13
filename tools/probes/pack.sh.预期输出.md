# pack.sh · 预期输出

**用途**：把车上的关键字目录**流式打包**回本地（`tar czf -` 通过 ssh 管道），**车上不落任何文件**。
当初做仓库快照就是用它。

| 项 | 说明 |
|---|---|
| 只读 | ✅ 只读车上的文件；**但会在本地写** `/mnt/d/ISCC/_stage/*.tgz` |
| 前置 | `export ROBOT_PASS=...`；本地目录 `/mnt/d/ISCC/_stage` 可写 |
| 耗时 | 1~3 min（约 40 MB） |
| 注意 | 目标路径写死 `keyuan22@10.211.121.22`，**换车要改脚本** |

---

## 正常输出

```
==== [1/2] 软件与源码（/opt） ====
  -> 34M
==== [2/2] 配置/脚本/模型（/home + /etc + /usr/local） ====
  -> 5.2M
==== systemd 单元（只取 .service 普通文件） ====
  -> 8.0K
etc/systemd/system/eprobot-base.service
etc/systemd/system/eprobot-imu.service
...
==== 完成 ====
total 40M
-rw-rw-rw- 1 ... etc-home.tgz
-rw-rw-rw- 1 ... opt.tgz
-rw-rw-rw- 1 ... systemd.tgz
```

**判据**

| 产物 | 期望 | 说明 |
|---|---|---|
| `opt.tgz` | **30~40 MB** | 太小 → 排除规则写错了；太大 → `.bak_*` 没排掉 |
| `etc-home.tgz` | **4~7 MB** | 明显偏小 → `board2_ocr/models` 没进去 |
| `systemd.tgz` | **~8 KB** | 里面应是 15 个 `.service` 纯文件，**不含软链** |

---

## 典型故障 1：`ROBOT_PASS: unbound variable`

```
pack.sh: line 3: ROBOT_PASS: export ROBOT_PASS first
```
→ 没导出密码。`export ROBOT_PASS='<密码>'` 再跑。（这是**故意**的硬失败，防止把空密码传给 sshpass。）

## 典型故障 2：`opt.tgz` 只有几十 KB

```
==== [1/2] 软件与源码（/opt） ====
  -> 24K
```
→ `sudo -n tar` 失败（无免密 sudo 时 tar 会把错误写进 stdout 的**同时**产出空 tar）。
自查：
```bash
ssh keyuan22@10.211.121.22 'sudo -n true; echo rc=$?'
```
`rc≠0` 就要配免密 sudo，或者改成 `sudo -S` 交互。

## 典型故障 3：`tar: Exiting with failure status due to previous errors`

```
tar: opt/eprobot_ws/install/pharmacy_pkg/share/.../stale: file changed as we read it
```
→ 打包期间车上**有进程在写**（几乎都是 `board2_ocr` 的 `runtime_arm64/__pycache__`）。
影响：该文件可能不完整。
处理：**停掉相关服务再打包**，或加重试：
```bash
sudo systemctl stop eprobot-pharmacy
# 打包
sudo systemctl start eprobot-pharmacy
```
> 本仓库的 `opt.tgz` 排除了 `--exclude='__pycache__'`，所以只在**没排除**时才遇到这个。

---

## 为什么不用 `rsync`

`rsync` 需要在车上装 rsync、且默认会建临时文件；`tar czf -` 是**纯流**，对车上零副作用，
这也是本仓库"只读"红线的一部分（见 `docs/仓库结构与维护.md` §2）。

## 与 `pack2.sh` 的关系

第一版的 systemd 打包（本脚本最后一段）用 `find ... -printf '%p '` 传参，**路径含空格就会错**，
而且拿不到软链。`pack2.sh` 是修正版（用 `-print0 | tar --null -T -`）。**要打 systemd 就用 `pack2.sh`。**
