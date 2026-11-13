# SECRETS · 凭据与现场值管理

> **一条铁律：真实密码、私钥、SSH key、`iscc.conf` 真本，永不入库。**
> 本文件列出"要真值才能跑起来"的每一项，以及**向谁要、怎么存、怎么自查**。
>
> 仓库里所有凭据位置都是**占位符**；占位符不替换，对应功能会**静默失效**（例如车连不上热点、`iscc` 报认证失败）。

---

## 0. 30 秒自查（改完东西先跑这个）

```bash
git status --short | grep -iE 'iscc\.conf|\.key$|\.pem$|id_rsa|id_ed25519|secret|\.env$'
# 期望：没有任何输出
```

更强的一次性检查（需在 WSL / Linux 下）：
```bash
bash tools/selfcheck.sh        # 第 4 项会检查 .gitignore 覆盖 + 仓库内是否混入真本
```

---

## 1. 需要真值的清单

| # | 字段 / 文件 | 在哪（仓库内路径） | 占位符 | 干什么用 | 向谁要 | 不填的后果 |
|---|---|---|---|---|---|---|
| 1 | **`ROBOT_PASS`** | `tools/host-iscc/iscc.conf.example` → 复制到 `~/.config/iscc/iscc.conf` | `PUT_PASSWORD_HERE` | 主机侧 `iscc` 通过 SSH 操作车 | 队内负责人 | `iscc` 全部子命令失败（`Permission denied`） |
| 2 | **WiFi 密码**（STA 模式） | `cars/car22/rootfs/etc/netplan/01-wlan0.yaml`、`50-cloud-init.yaml` | `WIFI_PASSWORD_HERE` | 车连手机热点 `OnePlusAce5` | 队内负责人 | 车连不上热点 → 只能网线救 |
| 3 | **WiFi 密码**（AP 模式） | `cars/car21/rootfs/etc/hostapd/iscc-ap.conf` | `AP_PASSWORD_HERE` | `.21` 自发热点 `yaofang` | 队内负责人 | 热点起不来或连不上 |
| 4 | **WiFi 密码**（`.21` 切 STA 脚本内） | `cars/car21/rootfs/usr/local/bin/iscc-wifi-client.sh` | `WIFI_PASSWORD_HERE` | 把 `.21` 切回客户端模式 | 队内负责人 | 切换后连不上 |
| 5 | **sudo 密码** | 不在仓库（车上 `/etc/sudoers.d/`） | — | `.22`/`.21` 都是**免密**，无需密码；历史 ROS 1 车有密码 | — | 无（当前两台车都不需要） |
| 6 | **裁判机 IP / 端口** | `cars/car22/rootfs/.../config/pharmacy.yaml` 的 `judge_tcp.host` / `port` | 当前值 `10.211.121.38:8888`（**现场值，非机密**） | 上报 JSON 给裁判软件 | 赛场裁判组（现场问） | 裁判收不到数据（0 分） |
| 7 | **`car_id`** | 同上，`car_id: '25'` | — | 裁判端识别车 | 赛场规则 | 报到错的车 |
| 8 | **NTP 密钥 `chrony.keys`** | 车上 `/etc/chrony/chrony.keys`（**未入库**） | — | 本车做 NTP 服务端时用 | 无需（默认不用 NTS key） | 无 |
| 9 | **`iscc.conf` 真本** | `~/.config/iscc/iscc.conf`（**不在仓库**） | — | 主机侧配置 | 自己填（含 #1） | 同 #1 |
| 10 | 任何 token / API key | **本仓库不需要** | — | — | — | — |

> 说明：**没有 SSH 私钥需要入库**。主机侧用密码认证（`sshpass` + `ROBOT_PASS`）；
> 车上仓库（Gitea）的 deploy key 在车上 `~/.ssh/`，与本仓库无关。

---

## 2. 占位符对照表（看到这些就说明要填真值）

| 占位符 | 出现位置 | 替换成 |
|---|---|---|
| `PUT_PASSWORD_HERE` | `tools/host-iscc/iscc.conf.example` | 车的 SSH 密码 |
| `WIFI_PASSWORD_HERE` | `cars/car22/rootfs/etc/netplan/*.yaml`、`cars/car21/rootfs/usr/local/bin/iscc-wifi-client.sh` | 热点密码 |
| `AP_PASSWORD_HERE` | `cars/car21/rootfs/etc/hostapd/iscc-ap.conf` | 热点密码（AP 模式） |
| `<REDACTED>` | 文档里的示例（`docs/竞赛笔记.md` §11.2） | **不要替换**，那是示意 |

**一次找全**：
```bash
git grep -nE '(PUT_PASSWORD_HERE|WIFI_PASSWORD_HERE|AP_PASSWORD_HERE)'
```

---

## 3. 本地怎么安全存放

### 3.1 最低要求（够用）

1. `iscc.conf` 放 `~/.config/iscc/iscc.conf`，权限 **600**：
   ```bash
   chmod 600 ~/.config/iscc/iscc.conf
   ```
2. **绝不把填好的 `iscc.conf` 复制进仓库目录**（`.gitignore` 已挡 `iscc.conf`，但别赌）。
3. 需要分享时，**只发表单/口述**，不要发文件。

### 3.2 推荐：用 git-crypt 管"需要版本化的配置"

适合：想把"填好密码的 netplan"也纳入版本控制，但只在队内可见。

```bash
# 一次性（在仓库根）
sudo apt install -y git-crypt
git-crypt init                    # 生成对称密钥
cat > .gitattributes <<'EOF'
# 加密这些文件（其余保持明文）
cars/car22/rootfs/etc/netplan/01-wlan0.yaml filter=git-crypt diff=git-crypt
cars/car22/rootfs/etc/netplan/50-cloud-init.yaml filter=git-crypt diff=git-crypt
cars/car21/rootfs/etc/hostapd/iscc-ap.conf filter=git-crypt diff=git-crypt
EOF
git add .gitattributes && git commit -m "chore: 用 git-crypt 保护含凭据的配置"

# 导出密钥，交给队友（离线传，别走群聊）
git-crypt export-key ../car22-gitcrypt.key

# 队友拿到仓库后
git-crypt unlock ../car22-gitcrypt.key
```

> ⚠️ 注意：一旦某文件在**历史提交里是明文**，加密只对**之后的提交**有效——历史仍可读。
> 所以本仓库的策略是**从一开始就只放占位符**，不做事后加密。

### 3.3 备选：用 sops（适合多环境、多人）

```bash
# 一次性
sudo apt install -y age
age-keygen -o ~/.config/sops/age/keys.txt      # 保管好这行私钥
cat > .sops.yaml <<'EOF'
creation_rules:
  - path_regex: secrets/.*\.yaml$
    age: <你的 age 公钥>
EOF

# 加密 / 解密
sops -e secrets/car22.yaml > secrets/car22.enc.yaml
sops -d secrets/car22.enc.yaml
```

### 3.4 不推荐但常见

| 做法 | 问题 |
|---|---|
| 密码写在 `~/.bashrc` 的 `export` | 会**覆盖** `iscc` 配置且易被 `env` 泄露（见笔记 §11.2 坑 1） |
| 密码写进 git commit message | 永久留在历史里 |
| 用同一个密码给两台车 + 热点 + sudo | 丢一个等于全丢 |

---

## 4. 泄露了怎么办

| 场景 | 处理 |
|---|---|
| 只在本机泄露（截图/日志） | 改密码 → 更新 `iscc.conf` 与 netplan → `netplan apply` |
| 提交进了 git（**还没 push**） | `git reset --soft HEAD~1`，改文件，重新提交 |
| **已经 push 到公开仓库** | ① 立刻改密码（最优先，历史清不干净也必须改）② `git filter-branch`/`filter-repo` 重写历史 ③ `push --force` ④ 提醒所有人重新 clone（旧 clone 仍含旧 blob） |
| 不确定 | 按"已泄露"处理：**先改密码**，再排查 |

> 本仓库 2026-11-13 曾把 `.24` 车的默认密码写进 `nav_tune_web.py`，
> 发现后用 `filter-branch` 重写了全部提交并 force push（记录见 `docs/仓库结构与维护.md` §7）。
> **教训：文档和脚本里的"默认密码"最容易漏。**

---

## 5. 交接时怎么给

| 给什么 | 怎么给 |
|---|---|
| WiFi 密码 | 口述 / 纸条，**不要**写进交接文档 |
| SSH 密码 | 同上；或改成密钥登录后给对方公钥 |
| `iscc.conf` | 让对方照 `iscc.conf.example` 自己填 |
| 裁判机 IP | 可以写进文档（现场值，非机密） |

**推荐在交接时直接改成"密钥登录 + 免密 sudo"**，这样上面 1/2/3/4 项都不再需要传递。

---

## 6. 维护这份文档

- 新增任何"需要真值"的字段 → **加一行到 §1**，同时把仓库里的值换成占位符 + 加进 §2。
- 占位符命名统一：`<用途>_PASSWORD_HERE`（例：`WIFI_PASSWORD_HERE`）。
- `tools/selfcheck.sh` 第 4 项会检查 `.gitignore` 是否仍覆盖关键模式、仓库里是否混入真本。
