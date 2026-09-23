# Raspberry Pi 4 一体化部署（HDMI 本机中控）

适用：Raspberry Pi 4 Model B（armv7l / 32 位）+ Raspbian GNU/Linux 10 (Buster) +
DHJ-9 接触网激光检测仪（CP2102 USB 转串口）。

**最终形态**：Pi 自己接 HDMI 显示器，通电开机后自动全屏显示 RIC Console。
不需要笔记本、不需要终端、不需要 `npm run dev`、不需要手工输入网址。

```
Pi 通电 → Linux 启动 → ric-console.service（FastAPI）自动启动
       → 桌面登录后 autostart 启动 pi-kiosk.sh
       → 等健康检查通过 → Chromium 全屏打开 http://127.0.0.1:8000
       → 显示轨道检测中控台
```

Pi 上**不运行 Vite、不依赖 Node/npm**。生产运行时只有：FastAPI + SQLite + pyserial
+ 预先构建好的 React 静态文件 + Chromium。

---

## 目录

1. [一次性准备（Windows 开发机）](#1-一次性准备windows-开发机)
2. [Pi 上安装](#2-pi-上安装)
3. [开机后应看到什么](#3-开机后应看到什么)
4. [安装脚本做了什么](#4-安装脚本做了什么)
5. [Python 3.11 策略](#5-python-311-策略)
6. [apt 故障的两类真实问题与处理](#6-apt-故障的两类真实问题与处理)
7. [服务与端口配置](#7-服务与端口配置)
8. [USB 摄像头环境预检](#8-usb-摄像头环境预检)
9. [日常维护命令](#9-日常维护命令)
10. [更新代码](#10-更新代码)
11. [故障排查](#11-故障排查)
12. [本文件的验证状态](#12-本文件的验证状态)

---

## 1. 一次性准备（Windows 开发机）

前端产物是**在开发机上构建好、提交进仓库**的，Pi 端不碰 Node。

```bat
cd C:\rail-inspection-console
scripts\package-pi-web.bat
git add deploy/pi/web frontend/.env.production
git commit -m "build: update pi web bundle"
git push
```

`package-pi-web.bat` 会：

1. 缺依赖时按 `package-lock.json` 用 `npm ci`（没有锁文件才用 `npm install`）；
2. 检查 `frontend/.env.production` 里确实是 `VITE_USE_MOCK=false`；
3. `npm run build`（= `tsc -b` + `vite build`）；
4. 把 `frontend/dist` 复制到 `deploy/pi/web/`；
5. 校验 `deploy/pi/web/index.html` 存在并给出下一步命令。

产物里 API/WS 都是**同源相对地址**（`/api`、`/ws/live`），不会写死
`localhost:5173` 或开发机 IP，所以换任何 Pi 都能直接用。

## 2. Pi 上安装

```bash
git clone <PRIVATE_REPO_URL>
cd rail-inspection-console
sudo bash ./scripts/pi-install.sh
sudo reboot
```

> **为什么写 `sudo bash ./scripts/pi-install.sh` 而不是 `sudo ./scripts/pi-install.sh`**：
> 仓库是在 Windows 上提交的，git 可能没有记录可执行位，直接执行会报
> `Permission denied`。用 `bash` 调用不受影响；安装脚本第一步自己会
> `chmod +x scripts/*.sh`，之后的 Kiosk 自启动就能正常直接执行。
> 如果希望仓库里长期保留可执行位，在开发机提交后执行一次：
>
> ```bash
> git update-index --chmod=+x scripts/pi-install.sh scripts/pi-kiosk.sh \
>     scripts/pi-status.sh scripts/pi-start.sh scripts/pi-stop.sh scripts/pi-update.sh
> git commit -m "chore: mark pi shell scripts executable"
> ```

脚本可重复执行（幂等）：已有 venv 只刷新依赖，已有 Python 不重新编译，
已有 `/etc/ric-console/ric-console.env` 不会被覆盖，数据库不会被删除或覆盖。

编译 Python 需要 20–60 分钟；之后每次重跑只需几十秒。

## 3. 开机后应看到什么

1. 桌面自动登录（Raspberry Pi 默认配置）；
2. 数秒后 Chromium 全屏打开中控台，无地址栏、无标签栏；
3. 侧栏底部显示 **未连接**；
4. 系统设置 → 串口参数 → 下拉里应有
   `/dev/ttyUSB0 · 推荐 CP2102 USB to UART Bridge Controller`；
5. 点 **建立链路** → **等待仪器导出**；
6. 在 DHJ-9 上点 **导出记录** → **正在接收** → 收到 `OVER` →
   **本批接收完成 · 共 N 条 · 等待下一次导出**，串口保持连接。

页面不会白屏：Kiosk 会先等 `/api/health` 通过（最多 60 秒）再开浏览器。

## 4. 安装脚本做了什么

| 步骤 | 内容 | 失败时 |
| --- | --- | --- |
| 1 | 检测发行版/架构/内存/磁盘；`chmod +x scripts/*.sh`；先做磁盘保护 | 可用 < 1500 MB 直接停 |
| 2 | `apt-get update`，失败时**按错误特征分类**（见第 6 节），再安装编译依赖 | 见第 6 节；分类为 unknown 时直接停止 |
| 3 | `modprobe cp210x`、`lsusb` 找 `10c4:ea60`、检查 `/dev/ttyUSB*`、把用户加入 `dialout` | 找不到设备只警告，安装继续 |
| 4 | `modprobe uvcvideo`、`/dev/video*`、`video` 组、按需装 `v4l-utils` | 只警告，见第 8 节 |
| 5 | 找现成 Python ≥ 3.10；没有则编译到 `/opt/ric-python311` | 编译失败即停 |
| 6 | `backend/.venv` + `pip install -r backend/requirements.txt` | 失败即停 |
| 7 | 校验 `deploy/pi/web/index.html` | 缺失即停并提示回开发机重跑打包脚本 |
| 8 | 创建 `/etc/ric-console/ric-console.env`（已存在则保留） | — |
| 9 | 以普通用户身份初始化 SQLite（建表，不覆盖数据） | 失败即停 |
| 10 | 渲染并启用 `ric-console.service`，`systemctl restart` | 失败即停 |
| 11 | 写入 autostart 桌面项（属主为普通用户）+ **只读**图形桌面前提检测 | 任何一项缺失只 WARN，不影响后端安装 |
| 12 | 轮询 `/api/health` 最多 60 秒 + 检查根路径返回 React 页面 | 超时打印 journalctl 命令并退出 1 |

## 5. Python 3.11 策略

系统 `/usr/bin/python3`（3.7.3）**保持不变**：不替换、不改符号链接、
不用 `update-alternatives`、不卸载。

选择顺序：

1. 已存在的 `/opt/ric-python311/bin/python3.11`；
2. PATH 上的 `python3.12 / 3.11 / 3.10`（必须 ≥ 3.10，因为
   fastapi / uvicorn / starlette 声明 `Requires-Python >=3.10`）；
3. 都没有 → 从 python.org 官方源码编译到 `/opt/ric-python311`。

编译要点：

* `./configure --prefix=/opt/ric-python311`，**不加** `--enable-optimizations`/PGO
  （ARMv7 上会慢到不可接受）；
* `make -j$(nproc)` + `make install`（私有前缀，不写入系统目录）；
* 源码与构建树放在磁盘-backed 的 `/var/tmp`（可用 `RIC_BUILD_TMP` 覆盖），
  不用 `/tmp`，避免某些镜像把 `/tmp` 挂成 tmpfs 反而吃内存；
* 编译**前**再次检查剩余空间（要求 ≥ 3000 MB），空间不足只报告并建议
  `sudo du -xh --max-depth=1 / | sort -h | tail`、`sudo apt clean`，
  脚本自身**不删除任何文件**；
* **只有编译成功才删构建目录**；失败时保留并打印路径供排查，
  清理动作永远只针对脚本自己创建的那个目录；
* 下载后用官方同目录的 `.sha256` 做完整性校验（防传输损坏/篡改，
  但不等同于信任锚：真正的信任锚需要你自己核对指纹）；
* 装完立刻验证 `ssl` / `sqlite3` / `ctypes` 可用，缺了就停下让你补 `-dev` 包。

`backend/.venv` 用这个解释器创建，systemd 直接调用
`backend/.venv/bin/python -m uvicorn ...`。

## 6. apt 故障的两类真实问题与处理

这台比赛用 Pi（Raspbian 10 Buster）上 `sudo apt-get update` **现场确认了两个互不相干的问题**：

| 编号 | 现场输出摘要 | 性质 | installer 的处理 |
| --- | --- | --- | --- |
| A | `http://raspbian.raspberrypi.org/raspbian buster Release` → **404 Not Found**；`E: 仓库不再含有 Release 文件` | 主源真的没了 | **只有**显式 `--repair-buster-sources` 才修，改写为 `http://legacy.raspbian.org/raspbian`，改前备份 |
| B | `http://archive.raspberrypi.org/debian buster InRelease` → Suite 值变化，APT 要求显式接受 | **已签名仓库的 release 元数据变更**，不是不安全仓库 | 一次性 `apt-get update --allow-releaseinfo-change`，**不修改任何源文件** |

分类由 `scripts/lib/apt-classify.sh` 完成（纯函数，已用真实日志文本做单测），
按错误特征而不是返回码判断，因此**不会**因为 `apt update` 非 0 就乱修：

| 现场情况 | 分类 | 计划动作 |
| --- | --- | --- |
| update 成功 | 不分类 | 什么都不做（即使带了 `--repair-buster-sources` 也只报告"无需修复"） |
| 只有 A，无参数 | `dead-raspbian` | **停止**，提示 `sudo bash ./scripts/pi-install.sh --repair-buster-sources` |
| 只有 A，带参数 | `dead-raspbian` | 备份 → 改写 → 重试 |
| 只有 B | `release-info` | 一次性 `--allow-releaseinfo-change`，成功后继续 |
| **A + B（真实现场组合）**，带参数 | `both` | 先修 Raspbian 源 → 再一次性接受 release-info → 成功后继续 |
| DNS / 代理 / 超时 / 时钟偏移 / 未签名第三方源 | `unknown` | **停止**，不改源、不使用任何 allow 参数 |

真实输出示例：

```
[警告] Raspberry Pi repository release metadata changed.
[信息] This is an APT release-info confirmation, not an unsigned repository.
[信息] Accepting this one-time metadata change with:
[信息]        apt-get update --allow-releaseinfo-change
[成功] release-info 变更已一次性确认，apt 可用（未修改任何源文件）
```

安全边界（明确不做的事）：

* **不写**永久 apt 配置：不创建 `/etc/apt/apt.conf.d/*`，不设
  `Acquire::AllowReleaseInfoChange=true`；
* 不用 `trusted=yes`、`--allow-unauthenticated`、`--allow-insecure-repositories`；
* 不删除第三方仓库、不改签名相关配置；
* 每次失败都保留完整日志 `/tmp/ric-apt-update.log`（重试时是**追加**，
  第一次的失败原因不会被覆盖掉），最终失败即停止，不会继续 `apt install`。

`apt-get` 一律以 `LC_ALL=C` 运行，保证分类不受中文语言环境影响。

### 6.1 修源具体改了什么

只有带 `--repair-buster-sources` 且确实判定为 A 类故障时才进入这段逻辑：

1. 先给 `/etc/apt/sources.list` 与 `/etc/apt/sources.list.d/*.list|*.sources`
   各做带时间戳的备份（如 `/etc/apt/sources.list.ric-backup-20260923-1630.list`），
   并把全部备份路径打印出来；
2. **只**改写同时满足「deb/deb-src 行 + 主机名含 raspbian + 发行号为 buster」的条目，
   目标为 `http://legacy.raspbian.org/raspbian`；
3. 不删除任何第三方仓库、不改签名配置、不加 `[trusted=yes]`、不禁用任何校验、
   不碰 `sources.list.d` 里无关文件；
4. 若没匹配到可识别条目 → 明确报告"未做任何修改"，要求人工看日志后停止；
5. 修复后重试 `apt-get update`；若此时暴露出 B 类（Suite 变更），再一次性接受；
   仍失败就停止并保留备份位置与完整日志。

## 7. 服务与端口配置

`deploy/systemd/ric-console.service.in` 由安装脚本替换
`@RIC_USER@ / @RIC_DIR@ / @RIC_PYTHON@` 后写到
`/etc/systemd/system/ric-console.service`。要点：

* `User=@RIC_USER@`：**绝不以 root 运行**（来自 `SUDO_USER`）；
* `WorkingDirectory=@RIC_DIR@/backend`：安装时的**绝对路径**，不写死 `/home/pi/...`；
* `Environment=RIC_HOST=127.0.0.1` + `Environment=RIC_PORT=8000` 写在前面，
  随后 `EnvironmentFile=-/etc/ric-console/ric-console.env` 才覆盖它
  （Buster 的 systemd 240 不支持 `${VAR:-默认值}`，所以兜底必须是真实的
  `Environment=` 行；前缀 `-` 保证文件不存在也能启动）；
* `ExecStart=<venv>/bin/python -m uvicorn app.main:app --app-dir <项目>/backend
  --host ${RIC_HOST} --port ${RIC_PORT}`：地址不写死；`WorkingDirectory` 已经是
  `<项目>/backend`，再显式给 `--app-dir`，这样即使以后有人改 `WorkingDirectory`
  也不会出现 `ModuleNotFoundError: app`；
* `ExecStart` 里没有 `&&`、`;`、管道或反引号：`${VAR}` 由 systemd 自己展开，
  不需要 bash；
* **只有一个 uvicorn 进程**（默认 1 worker）。`SerialService` 独占串口与写库线程，
  多 worker 会互相抢端口；
* `Restart=on-failure` + `RestartSec=3`，`TimeoutStopSec=20` 让未结束的批次能收尾。

改监听地址：

```bash
sudoedit /etc/ric-console/ric-console.env      # RIC_HOST=0.0.0.0 仅用于调试
sudo systemctl restart ric-console
```

> **安全提醒**：`RIC_HOST=0.0.0.0` 会把中控开放到局域网，而本系统**没有任何登录鉴权**。
> 正式比赛与实验室默认保持 `127.0.0.1`，页面就在 Pi 自己的 HDMI 上显示。

## 7.1 图形桌面前提（只读检测，不修改登录方式）

安装最后一步会打印一张只读体检表，**不会**替你改 LightDM / raspi-config：

```
[图形桌面 / Kiosk 前提（只读检测）]
  Desktop environment:   OK（默认启动目标 graphical.target）
  Chromium:              OK（chromium-browser）
  xset（熄屏抑制）:      OK
  Desktop autologin:     detected（LightDM autologin-user=pi）
```

可能出现的结论与含义：

| 结论 | 含义 |
| --- | --- |
| `Desktop environment: WARN` | 系统可能没有桌面环境（lite 版），Kiosk 无法显示，但后端照常工作 |
| `Chromium: WARN` | 后端已装好，只是无法自动显示中控；脚本会列出**当前 apt 源里真实存在**的 chromium 包名让你自己决定，不硬编码未验证的包名 |
| `xset: WARN` | 缺 `x11-xserver-utils`，中控仍会启动，只是屏幕可能自动休眠 |
| `Desktop autologin: not confirmed` | **后端仍会开机自启**（systemd 与桌面无关），但 Chromium 需要有人登录图形桌面后才自动打开 |

需要全自动显示时，请自行用 `raspi-config`（Boot Options → Desktop Autologin）
或 LightDM 配置开启自动登录；本脚本刻意不碰这些设置。

## 8. USB 摄像头环境预检

本轮**只预检环境，不实现任何识别**，也**不安装 OpenCV**
（ARMv7/Buster 的 wheel 兼容性未确认，留到 M2-1 拿到真实摄像头型号后再定）。

脚本检查/准备：

* `modprobe uvcvideo`（标准 UVC 摄像头所需内核模块）；
* 用户是否在 `video` 组，不在则加入；
* `lsusb` 列出非 hub 设备；
* `/dev/video*` 是否存在；
* 有则装 `v4l-utils` 并执行 `v4l2-ctl --list-devices` 显示设备。

如果总线上有 USB 设备但没有 `/dev/video*`，输出固定为：

```
[警告] 检测到 USB 设备但未发现 V4L2 摄像头，需要进一步确认驱动
```

此时**不要**去下载未知厂商驱动，先确认摄像头是否为标准 UVC。

## 9. 日常维护命令

```bash
sudo systemctl status  ric-console
sudo systemctl restart ric-console
journalctl -u ric-console -f              # 实时日志
./scripts/pi-status.sh                    # 只读状态板：服务/健康/DHJ-9/串口/摄像头/Chromium
./scripts/pi-start.sh                     # 启动后端并等健康检查
./scripts/pi-stop.sh                      # 只停后端，不会杀 Chromium
./scripts/pi-kiosk.sh                     # 手动打开全屏中控
backend/.venv/bin/python scripts/inspect-db.py   # 只读查看批次数据
```

串口编码诊断：`journalctl -u ric-console | grep "encoding detected"`
（首条非 ASCII 行会打印实际解码到的编码，例如 `gb18030`）。

## 10. 更新代码

```bash
./scripts/pi-update.sh
```

流程是刻意保守的：

1. `git status --porcelain` 非空 → **立即停止**，列出改动，不覆盖现场修改；
2. `git fetch` + `git pull --ff-only` → 本地与远端分叉时停止，交给人工；
3. 只有 `backend/requirements.txt` 变化时才 `pip install`；
4. 校验 `deploy/pi/web/index.html`；
5. `systemctl restart ric-console` + 健康检查；
6. 失败时打印**回退到旧提交**的具体命令。

全程不执行 `git reset --hard`、`git clean`，不删除 `data/`，不覆盖 SQLite。
前端有更新时仍需回开发机跑 `scripts\package-pi-web.bat` 并提交产物。

## 11. 故障排查

| 现象 | 处理 |
| --- | --- |
| 开机没有自动进入中控 | `ls -l ~/.config/autostart/ric-console-kiosk.desktop`；`echo $DISPLAY`；先手动 `./scripts/pi-kiosk.sh` 看报什么 |
| 浏览器 "无法访问" | `systemctl status ric-console`；`curl -i http://127.0.0.1:8000/api/health` |
| Kiosk 60 秒超时退出 | 后端没起来，看 `journalctl -u ric-console -n 80` |
| 页面白屏但服务正常 | `deploy/pi/web/index.html` 是否完整；重新在开发机打包并 `git pull` |
| 下拉框没有 `/dev/ttyUSB0` | 逐条检查：`lsusb`、`dmesg \| tail`、`sudo modprobe cp210x` |
| 建立链路提示被占用 | 关掉 `cat /dev/ttyUSB0`、minicom、screen 等占用进程 |
| 加入 dialout 后仍无权限 | 必须**注销重登**或 `sudo reboot`；`id -nG` 确认 |
| 收到数据但表头是乱码 | 看 `encoding detected` 日志；若为 `gb18030(replace)` 说明设备用了第三种编码，需要采集样例 |
| apt 一直失败 | 见第 6 节；不要手工改源，把 `/tmp/ric-apt-update.log` 留存 |
| 想临时从笔记本访问页面 | `RIC_HOST=0.0.0.0` + 重启服务；**记得改回 127.0.0.1**（无鉴权） |

## 12. 本文件的验证状态

**已在 Windows 开发机验证**：FastAPI 托管 `deploy/pi/web` 的全部路由行为
（`/`、`/history`、`/settings`、`/analytics`、`/anomalies` → React 页面；
`/api/health` → JSON；`/api/does-not-exist` → JSON 404；`/ws/live` WebSocket 正常；
静态资源正常；无构建时根路径仍返回 JSON，开发模式不受影响），
以及生产构建确实关闭了 mock（浏览器实测无"演示数据"标记、请求打到同源 `/api`）。

**已在真实 Pi 上现场确认**（M2-0B.2 的输入）：`sudo apt-get update` 同时出现
A 类（`raspbian.raspberrypi.org` buster Release **404**、`仓库不再含有 Release 文件`）
与 B 类（`archive.raspberrypi.org` buster InRelease **Suite 值变化**、要求显式接受）；
图形环境本身没问题：`get-default` 为 `graphical.target`、
`/usr/bin/chromium-browser` 与 `/usr/bin/xset` 均存在、lightdm/lxde/raspberrypi-ui-mods 已装。

**已加自动化测试**：
`backend/tests/test_pi_deployment.py` — unit 渲染后的
`WorkingDirectory`/`--app-dir`/`User`/环境顺序/无 shell 语法、Kiosk 参数集合与
禁止项、磁盘检查顺序、构建目录清理范围、修源调用点唯一、健康检查不依赖 curl、
生产包存在且构建期关闭 mock、更新脚本不使用 `reset --hard`/`clean`/`rm -rf`。
`backend/tests/test_apt_classifier.py` — 用上面两类**真实日志文本**（含中文 locale）
在 bash 里实际执行 `scripts/lib/apt-classify.sh`，覆盖第 6 节表格的 6 种组合，
并断言不使用任何永久 apt 配置或不安全选项。

**尚未在真实 Pi 上执行**：`pi-install.sh` 全流程、Python 源码编译耗时与依赖完整性、
systemd 单元在该机上的实际拉起、autostart 生效、Chromium Kiosk 显示效果、
`v4l-utils` 安装、Buster 源修复路径。所有 shell 脚本已通过 `bash -n` 语法检查，
但**没有**在 Raspberry Pi 上运行过，第一次执行请留足时间并盯着输出。

架构与后续视觉链路见 [VISION_AGENT_PROTOCOL.md](VISION_AGENT_PROTOCOL.md)。
