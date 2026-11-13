# survey.sh · 预期输出

**用途**：**体积调查**——决定"哪些目录值得入库、哪些太大要排除"。是当初做仓库快照时用的工具。

| 项 | 说明 |
|---|---|
| 只读 | ✅ 只 `du -sh` / `ls` / `find` |
| 前置 | `export ROBOT_PASS=...` |
| 耗时 | ~20 s（`du` 会遍历 300+ MB） |

---

## 正常输出（节选，2026-11-13 实测）

```
==== 候选目录体积 ====
/opt/eprobot_ws/install/pharmacy_pkg         36M
/opt/eprobot_ws/src                          9.1M
/home/keyuan22/eprobot_navigation            8.6M
/home/keyuan22/camera_shim                   36K
/home/keyuan22/relay_ws                      1.4M
/home/keyuan22/board2_ocr                    284M
/home/keyuan22/nav_tune_web                  48K
/home/keyuan22/maps                          128K
/home/keyuan22/prematch_hiscore              ...
/opt/oni2-orbbec                             2.7M
/usr/local/bin                               ...

==== board2_ocr 细分 ====
276M	/home/keyuan22/board2_ocr/runtime_arm64
7.3M	/home/keyuan22/board2_ocr/models
...
```

**这些数字怎么用**

| 目录 | 体积 | 结论 |
|---|---:|---|
| `install/pharmacy_pkg` | 36 MB | **必须入库**（唯一产物） |
| `src` | 9.1 MB | 入库，但 `cartographer*` 排除（上游标准包） |
| `board2_ocr/runtime_arm64` | **276 MB** | **不入库** → 只入库 `requirements.lock` + 构建脚本（见 `runtime/README.md`） |
| `oni2-orbbec` | 2.7 MB | 入库（公网已下不到） |
| `maps` | 128 KB | 入库 |
| `relay_ws` | 1.4 MB | 只入库 `src/`（build/install 是产物） |

---

## 典型故障 1：`du` 卡住 / 很慢

```
==== 候选目录体积 ====
（长时间无输出）
```

| 原因 | 排查 |
|---|---|
| 目录特别大（如 `runtime_arm64` 20 万文件） | 正常，等；或单独 `du -sh` |
| `sudo -n` 不可用（要密码） | 脚本里全是 `sudo -n`，无免密会**静默输出空**，而不是报错 |
| SD 卡 IO 慢 / 坏了 | `iostat -x 1`；`dmesg \| tail` 看有没有 `I/O error` |

> **静默空输出**是本脚本最容易误判的地方：`sudo -n du` 失败时 `cut -f1` 会得到空字符串，
> 看起来像"目录体积 0"。自查：`sudo -n true; echo $?` 应为 0。

## 典型故障 2：某个目录 `MISSING`

```
/home/keyuan22/board2_ocr    MISSING
```
→ 该目录不存在。常见于：
- 新车还没铺 `rootfs`（正常）
- 有人 `mv` 了目录（查 `~/` 下最近改动：`ls -lt ~ | head`）

## 典型故障 3：体积突然变大

```
/opt/eprobot_ws/install/pharmacy_pkg         53M     （曾 36M）
```
→ 有人塞了 `.bak_*` 进去（厂商/前届习惯，现场改前先备份）。去掉备份再算：
```bash
sudo du -sh /opt/eprobot_ws/install/pharmacy_pkg --exclude='*.bak_*'
sudo find /opt/eprobot_ws/install/pharmacy_pkg -name '*.bak_*' | wc -l
```
入库时统一排除 `*.bak_*`（见 `docs/仓库结构与维护.md` §3）。

---

## 与仓库的关系

本脚本的结论直接决定了 `cars/car22/` 里**收什么、不收什么**：

| 决策 | 出处 |
|---|---|
| 不收 `runtime_arm64` | `board2_ocr/runtime/README.md` |
| 不收 `cartographer`/`cartographer_ros` | `docs/依赖清单.md` §3.3 |
| 收 `oni2-orbbec` | 公网 403，只能从车/仓库拿 |
| 收全部 `.7z` 固件 | `cars/car22/firmware/README.md` |

改了收录规则，就要同步更新 `docs/仓库结构与维护.md` §3 的"必须入库/不能入库"两张表。
