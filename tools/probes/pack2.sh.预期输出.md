# pack2.sh · 预期输出

**用途**：`pack.sh` 的修正版——**只打 systemd unit**，用 `-print0 | tar --null -T -` 避免路径空格/中文问题。

| 项 | 说明 |
|---|---|
| 只读 | ✅ 只读车上文件；本地写 `/mnt/d/ISCC/_stage/systemd.tgz` |
| 前置 | `export ROBOT_PASS=...` |
| 耗时 | ~5 s |
| 为什么单独一个 | `pack.sh` 那段用 `find -printf '%p '` 拼参数，遇到空格/软链会出错 |

---

## 正常输出

```
==== systemd 单元清单 ====
etc/systemd/system/camera-shim.service
etc/systemd/system/eprobot-base.service
etc/systemd/system/eprobot-carto.service
etc/systemd/system/eprobot-imu.service
etc/systemd/system/eprobot-nav.service
etc/systemd/system/eprobot-pharmacy.service
etc/systemd/system/eprobot-slam.service
etc/systemd/system/image-relay.service
etc/systemd/system/lslidar.service
etc/systemd/system/mono8-relay.service
etc/systemd/system/nav-tune-web.service
etc/systemd/system/openni2-camera.service
etc/systemd/system/openni2-mono8.service
etc/systemd/system/orbbec-astra-s.service
etc/systemd/system/scan-viz.service

==== 打包 ====
  -> 8.0K
etc/systemd/system/eprobot-base.service
...

==== etc-home.tgz 顶层 ====
etc/default
etc/netplan
etc/udev
...
```

**判据**

| 项 | 期望 | 不对说明 |
|---|---|---|
| 清单行数 | **15** | 少于 15 → 有 unit 被删或没权限 |
| 每个路径都是**普通文件**（不是软链） | ✅ | 出现 `-> /lib/systemd/system/...` 说明软链混进来了 |
| `systemd.tgz` 体积 | ~8 KB | 几十 KB → 混入了 snapd 之类的大文件 |

> **为什么只收普通文件**：`/etc/systemd/system` 里有大量指向 `/lib/systemd/system/` 的软链
> （发行版自带的）。把它们收进仓库没有意义（目标机本来就有），而且跨文件系统解引用会指错。
> 见 `cars/car21/README.md` §5 的同款说明。

---

## 典型故障 1：清单为空

```
==== systemd 单元清单 ====
（无输出）
```
→ `sudo -n` 不可用，`find` 静默失败。自查 `ssh ... 'sudo -n true; echo rc=$?'`。

## 典型故障 2：`tar: Cowardly refusing to create an empty archive`

```
tar: Cowardly refusing to create an empty archive
```
→ `find` 没输出（同故障 1），`-T -` 读到空列表。

## 典型故障 3：`etc-home.tgz 顶层` 报 `No such file`

```
==== etc-home.tgz 顶层 ====
tar: etc-home.tgz: Cannot open: No such file or directory
```
→ 还没跑过 `pack.sh` 的第二段。**这是提示，不是错误**——本脚本只负责 systemd，
`etc-home.tgz` 若不存在就跳过这段即可。

---

## 收完之后怎么用

```bash
mkdir -p /tmp/units && tar xzf /mnt/d/ISCC/_stage/systemd.tgz -C /tmp/units
# 与仓库对比，看车上有没有手改过
diff -r /tmp/units/etc/systemd/system \
        cars/car22/rootfs/etc/systemd/system
```
**Diff 有差异 = 车上被手改过**（这是 `docs/仓库结构与维护.md` §2 "先 diff 再覆盖"的实际操作）。
