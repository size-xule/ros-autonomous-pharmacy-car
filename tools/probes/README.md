# tools/probes —— 只读诊断脚本

> 这一组脚本是**排查问题**用的，全部**只读**（除 `pack*.sh` 会在**本地**写 `.tgz`）。
> 每个脚本的"正常长什么样、坏了长什么样"都写在同名 `<脚本>.预期输出.md` 里。

---

## 0. 通用前置

```bash
# 在 WSL / Linux 里
sudo apt install -y sshpass          # 只需一次
export ROBOT_PASS='<车的 SSH 密码>'   # 每个新 shell 都要
```

> 所有脚本都硬编码 `keyuan22@10.211.121.22`。**换车要先改脚本里的 `H=`**（或用 `ROBOT_IP` 环境变量改造）。
> 密码**不要写进脚本**——`export ROBOT_PASS` 是故意设计成"不导出就直接报错退出"。

---

## 1. 按问题选脚本

| 我想查… | 跑这个 | 只读 | 耗时 |
|---|---|---|---|
| 这台车现在什么状态（身份/unit/配置/进程） | [`probe.sh`](probe.sh.预期输出.md) | ✅ | 10 s |
| 话题在不在、帧率对不对、电池够不够 | [`probe2.sh`](probe2.sh.预期输出.md) | ✅ | 40 s |
| 雷达链路 + 网段里谁在线 | [`probe3.sh`](probe3.sh.预期输出.md) | ✅ | 20 s |
| 任务层二进制里有什么线索 | [`probe4.sh`](probe4.sh.预期输出.md) | ✅ | 15 s |
| 设备节点（IMU/串口）/ 网络配置 / 温度降频 | [`probe5.sh`](probe5.sh.预期输出.md) | ✅ | 10 s |
| 哪些目录占空间（决定收什么入库） | [`survey.sh`](survey.sh.预期输出.md) | ✅ | 20 s |
| 把车上目录打包回本地 | [`pack.sh`](pack.sh.预期输出.md) | ⚠️ 本地会写 | 1~3 min |
| 只打 systemd unit（修正版） | [`pack2.sh`](pack2.sh.预期输出.md) | ⚠️ 本地会写 | 5 s |

---

## 2. 推荐顺序（车"不对劲"时）

```
① probe.sh      → 还活着吗？unit 起了几个？
② probe2.sh     → 有数据吗？帧率/电压对吗？
③ probe5.sh     → 硬件层（设备节点/温度/降频）有问题吗？
④ probe3.sh     → 只有雷达坏？还是整条链？
⑤ probe4.sh     → 只有任务层怪？看二进制线索
```

跑完把输出贴进 issue / 群里，比描述"车不动了"有用十倍。

---

## 3. 这些脚本的来历

它们不是"设计出来的工具"，而是**排查过程中攒下来的**（所以命名不整齐：`probe.sh`→`probe5.sh`、
`pack.sh`→`pack2.sh`）。保留原样是为了**新旧输出能对照**——当初就是用它们的输出写出了
`docs/竞赛笔记.md` 和 `docs/仓库结构诊断.md`。

---

## 4. 想加新脚本？

1. 命名 `probeN.sh`（N 递增），或按用途命名（`camera.sh`）；
2. **只读**：不 `systemctl start/stop`、不写车上文件、不改参数；
3. 必须有 `set -u` + `export SSHPASS="${ROBOT_PASS:?...}"`；
4. 每条远程命令加 `timeout`（Pi 上 `ros2` 偶发卡 20 s）；
5. **配一份 `<脚本>.预期输出.md`**（否则 `tools/selfcheck.sh` 会报"缺说明"）。
