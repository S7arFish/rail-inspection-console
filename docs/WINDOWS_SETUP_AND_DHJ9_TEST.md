# 全新 Windows 电脑部署与 DHJ-9 真机测试指南

适用对象：**第一次拿到这个项目的人**，不是原来的开发机，需要从零开始——
从 GitHub 私人仓库克隆、装环境、跑测试、启动前后端，最后在实验室连接真实 DHJ-9
接触网激光检测仪完成一次真机测试。

项目：轨道检测车综合检测中控平台（RIC Console）
目标系统：Windows 11 64 位（Windows 10 64 位同样可用）
文档版本：M1.5

> 本文只讲部署与测试操作，不涉及业务功能开发。
> 数据链路、字段含义与批次规则以 `backend/config/parser.yaml` 和 `README.md` 为准。

---

## 目录

1. [准备工作](#1-准备工作)
2. [GitHub 私人仓库克隆](#2-github-私人仓库克隆)
3. [Windows 软件环境检查](#3-windows-软件环境检查)
4. [CP210x 驱动检查](#4-cp210x-驱动检查)
5. [第一次安装项目](#5-第一次安装项目)
6. [先运行自动测试](#6-先运行自动测试)
7. [Mock 模式自检](#7-mock-模式自检)
8. [切换真实模式](#8-切换真实模式)
9. [DHJ-9 真机连接](#9-dhj-9-真机连接)
10. [第一次真实导出](#10-第一次真实导出)
11. [第二次导出验证 session 分离](#11-第二次导出验证-session-分离)
12. [SQLite 数据验证](#12-sqlite-数据验证)
13. [常见故障排查](#13-常见故障排查)
14. [测试结果记录模板](#14-测试结果记录模板)
15. [测试完成后如何安全关闭](#15-测试完成后如何安全关闭)

---

## 1. 准备工作

需要准备的硬件与账号：

| 项目 | 说明 |
| --- | --- |
| 实验室电脑 | Windows 11 64 位，本地管理员权限（装驱动需要） |
| USB 数据线 | 连接 DHJ-9 与电脑（不是只能充电的线） |
| DHJ-9 接触网激光检测仪 | 电量充足，能进入"导出记录"功能 |
| GitHub 账号 | 对该私人仓库有读取权限 |
| 网络 | 首次装依赖要访问 npm 与 PyPI；离线机器需提前准备缓存（见 13.4 / 13.5） |

需要知道的三件事：

1. **DHJ-9 不是连续实时设备。** 流程是：程序打开串口 → 等 → 人在仪器上按"导出记录"
   → 仪器一次性吐出一批历史记录 → 最后发 `OVER` → 一批结束。
2. **一次导出 = 一个批次会话（session）。** 刚连上串口时不会产生任何会话记录，
   收到第一条数据才会创建。
3. **本程序不使用 SSCOM。** 串口被 SSCOM 占用时本程序打不开端口；
   SSCOM 只在排障时作为备用工具，用之前必须先关掉本程序。

---

## 2. GitHub 私人仓库克隆

打开 **PowerShell** 或 **命令提示符**（建议放在一个路径不含中文和空格的目录，
例如 `D:\lab`）：

```powershell
cd D:\lab
git clone <PRIVATE_REPO_URL>
cd rail-inspection-console
```

`<PRIVATE_REPO_URL>` 用仓库页面上 **Code → HTTPS** 给出的地址，形如
`https://github.com/<组织或用户>/<仓库名>.git`（SSH 方式需先配好本机 SSH key）。

私人仓库第一次克隆会弹浏览器授权：

- 弹出 **Git Credential Manager** 的 GitHub 登录窗口 → 用浏览器登录并授权即可；
- 之后凭证由 Windows 凭据管理器保存，不必每次输入。

**安全要求：**

- 不要把 Personal Access Token 拼进 clone URL（例如
  `https://user:token@github.com/...`）。这种写法会留在 shell 历史、
  脚本和 `.git/config` 里，等于泄露凭证。
- 也不要把 token 写进项目内任何文件（包括 `.env`）。本项目运行不需要任何密钥。
- 仓库里不应包含 `.env`、数据库文件、`node_modules`、`.venv`；
  克隆下来后如果看到这些，说明上传方误传了，需要由上传方处理。

图形界面备选：不想用命令行时，可安装 **GitHub Desktop**，
`File → Clone repository → URL` 粘贴同一个地址，选一个本地路径。
后续步骤中的命令行操作仍需在项目目录下打开终端执行。

克隆完成后先确认目录结构：

```powershell
dir
```

应当看到 `backend`、`frontend`、`scripts`、`data`、`docs`、`README.md`。

---

## 3. Windows 软件环境检查

**先检查，再安装。** 在项目根目录执行：

```bat
scripts\check-env.bat
```

它会检查 `git / python / node / npm` 是否存在并打印版本，检查
`backend / frontend / scripts / data` 目录与关键文件是否齐全，最后给出
**环境检查通过** 或 **环境检查失败**。它不会修改 PATH，也不会替你下载安装任何东西。

本项目对软件版本的要求（依据依赖包元数据，不是猜的）：

| 软件 | 要求 | 本项目实际验证版本 | 依据 |
| --- | --- | --- | --- |
| Git | 较新版本均可 | 2.54.0 | — |
| Python | **3.10 及以上** | 3.11.15 | fastapi 0.141 / uvicorn 0.53 / starlette 1.6 的 `Requires-Python >=3.10` |
| Node.js | **20.19+ 或 22.12+** | 22.23.2 | vite 8.3 与 @vitejs/plugin-react 6.1 的 `engines` |
| npm | 随 Node.js 安装 | 12.0.2 | — |
| 操作系统 | Windows 11 64 位为主 | Windows 10/11 64 位 | — |

> 表里的"要求"是依赖包声明的硬下限；"实际验证版本"是本项目真正跑通过的版本。
> 建议新电脑直接装验证版本或更高的稳定版（Python 3.11/3.12，Node 22 LTS）。

安装方式（用官方安装包，**不要用** 非官方绿色版）：

- Python：<https://www.python.org/downloads/windows/>
  安装时勾选 **Add python.exe to PATH**。
- Node.js：选 **22.x LTS**，<https://nodejs.org/en/download>
- Git：<https://git-scm.com/download/win>

装完 **重新开一个终端窗口**（PATH 变更不会进老窗口），再跑一次
`scripts\check-env.bat`，直到显示"环境检查通过"。

---

## 4. CP210x 驱动检查

DHJ-9 通过 **Silicon Labs CP210x USB to UART Bridge** 与电脑通信。
没有驱动，Windows 只会看到一个未知 USB 设备，本程序也无法枚举到串口。

检查步骤：

1. 用 USB 线连接 DHJ-9 并开机（仪器需要供电才能被识别）。
2. 右键开始菜单 → **设备管理器** → 展开 **端口 (COM 和 LPT)**。
3. 正常应看到类似条目：

   ```
   Silicon Labs CP210x USB to UART Bridge (COM7)
   ```

   **COM 编号只是示例**，不同电脑、不同 USB 口可能是 COM3、COM8 等，
   一切以实验室这台电脑实际显示的为准。程序不硬编码 COM7。

4. 如果看不到上面这一条：

   - 在 **设备管理器** 里找有没有带 **黄色感叹号** 的"未知设备 / CP210x / USB to UART"；
   - 有感叹号 → 驱动未装好，去
     <https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers>
     下载 **CP210x VCP Driver（Windows 10/11 64 位）** 安装，装完重新插拔；
   - 完全没有任何新设备出现 → 先换数据线 / 换 USB 口再判断，不要先启动本程序；
   - 也可能被识别成其他芯片（CH340、PL2303 等）。这属于硬件信息待确认，
     需要向仪器提供方核对，不要凭猜测装驱动。

5. 记下设备管理器里显示的 **COM 号**，后面第 9 节要用。

**驱动没确认好之前，不要开始跑串口程序。** 本程序在没有 CP210x 的机器上不会崩溃，
但也不会有任何数据，容易把驱动问题和仪器问题混在一起。

---

## 5. 第一次安装项目

在项目根目录执行：

```bat
scripts\dev.bat install
```

这条命令会：

- `backend\.venv` 不存在时自动创建虚拟环境（用系统 `python`）；
- 安装 `backend\requirements.txt` 与测试所需依赖；
- `frontend\node_modules` 不存在时执行 `npm install`；
- 如果 `frontend\.env` 不存在，从 `frontend\.env.example` 复制一份并**明确提示已创建**
  （已存在的 `.env` 绝不覆盖）；
- **不会启动任何服务**，装完就退出。

数据库不需要手动创建：后端第一次启动时会自动在 `data\rail_inspection.db`
建库建表（目录不存在也会自动创建）。仓库里不携带任何数据库文件，
`data\` 只有一个占位文件 `.gitkeep`。

如果 `dev.bat install` 报错，先回到第 3 节确认 `check-env.bat` 是通过的，
再看 13.4 / 13.5 两条排障。

---

## 6. 先运行自动测试

装完环境先做一次性全量检查：

```bat
scripts\test-all.bat
```

依次执行：后端 pytest → 前端 TypeScript 类型检查 → 前端 vite 构建。
任何一步失败会**立即停止并返回非 0**，失败输出原样打印，不会被隐藏。

全部通过时结尾是：

```
================================
 RIC Console 全部检查通过
 Backend tests: PASS
 TypeScript: PASS
 Vite build: PASS
================================
```

**三项没有全部 PASS，就不要去接仪器。** 否则现场分不清是环境问题还是设备问题。

参考：开发机上后端为 27 项测试全部通过。若新电脑上测试失败，请把完整输出
记到第 14 节的表格里再排查。

---

## 7. Mock 模式自检

`frontend\.env` 默认是 `VITE_USE_MOCK=true`（演示数据），先在这个状态下自检界面。

```bat
scripts\dev.bat
```

会打开两个终端窗口：**RIC Backend**（`http://127.0.0.1:8000`）和
**RIC Frontend**（`http://localhost:5173`）。

浏览器访问 **http://localhost:5173**，逐项确认：

| 检查点 | 预期 |
| --- | --- |
| 左侧导航 | 实时监测 / 异常检测 / 历史任务 / 数据分析 / 系统设置 五项都能点开 |
| 实时监测页 | 有数值在跳动，右上角有橙色 **演示数据** 标记 |
| 后端健康 | 浏览器打开 <http://127.0.0.1:8000/api/health> 返回 `"status":"ok"` |
| 接口文档 | <http://127.0.0.1:8000/docs> 能打开 |
| 系统设置 → 字段映射 | 12 行：0–10 显示"已确认"，11 是 `metric_extra_1` 显示"暂定" |

五个页面都能打开、演示数据标记存在，说明前后端与代理链路正常，
剩下的问题只会出在真实数据源上。

自检完 **关掉两个服务窗口**（下一步要改配置并重启）。

---

## 8. 切换真实模式

用编辑器打开 `frontend\.env`，把这一行：

```
VITE_USE_MOCK=true
```

改成：

```
VITE_USE_MOCK=false
```

保存后重新启动：

```bat
scripts\dev.bat
```

打开 **http://localhost:5173**，确认：

- 页面右上角的 **演示数据** 标记**已经消失**（还在说明没生效，见 13.17 / 13.18）；
- 侧栏底部链路状态显示 **未连接**；
- 实时监测页各项显示 `—`、点位条显示"暂无点位数据"、
  异常面板显示 **检测标准未配置，暂无判定结果**。

> 真实模式下界面不会出现"正常/异常"判定，因为系统里还没有任何阈值与规则。
> 看到"检测标准未配置"是**正确**的状态，不是故障。

---

## 9. DHJ-9 真机连接

前置：第 4 节的驱动已确认；**SSCOM 必须完全关闭**（不是最小化，是退出程序）。

1. 保持 `scripts\dev.bat` 两个窗口在运行。
2. 浏览器进入 **系统设置**（左侧最后一项）。
3. "串口参数"里点右上角 **重新枚举端口**，下拉框应出现设备管理器里那一项，
   形如：

   ```
   COM7 · 推荐 Silicon Labs CP210x USB to UART Br...
   ```

   带 **推荐** 的即程序自动识别到的 CP210x / Silicon Labs 端口。
   若下拉框显示"当前系统无可用串口"，回到第 4 节处理驱动。
4. 确认参数为：

   | 参数 | 值 |
   | --- | --- |
   | 波特率 | 115200 |
   | 数据位 | 8 |
   | 校验 | 无 (None) |
   | 停止位 | 1 |
   | 流控 | 无流控 |

5. 点 **建立链路**。

预期结果：

- 侧栏与设置页显示 **等待仪器导出**（内部状态 `connected_waiting`）；
- 显示实际端口与 `115200 8N1`；
- **历史任务页此时不应新增任何会话**——连上串口不等于开始一个批次；
- 若提示"串口 COMx 正被其他程序占用（例如 SSCOM）…"，说明 SSCOM 没关干净，
  关掉后重新点建立链路。

---

## 10. 第一次真实导出

在 DHJ-9 上选择 **导出记录**。

预期观察顺序（网页不用刷新，WebSocket 会自动推送）：

1. 状态从 **等待仪器导出** 变为 **正在接收**（`receiving`）；
2. 设置页与侧栏的 **本批已接收 N 条** 随每条记录递增；
3. 实时监测页四个指标出现真实数值：
   `height`（当前高度）、`pull_out`（当前拉出值）、`gauge`（当前轨距）、
   `metric_extra_1`；
4. 趋势图追加数据点；
5. "串口原始数据保留"面板出现与仪器一致的原始行，末尾一行是
   `OVER — 批次 1 结束，共 N 条`；
6. 收到 `OVER` 后：
   - 显示 **本批接收完成 · 共 N 条 · 等待下一次导出**（瞬态 `batch_complete`
     之后回到 `connected_waiting`）；
   - **串口保持连接**，不需要重新建立链路；
   - 历史任务页出现这一条会话，状态 `completed`，记录数 = N。

`N` 应当与仪器本次导出的记录条数一致。不一致请记录在 14 节表格里，
并保留原始行截图（原始行都存进了数据库，可事后核对）。

---

## 11. 第二次导出验证 session 分离

保持链路连接，**再按一次"导出记录"**。

预期：

- 状态再次 `connected_waiting → receiving → 本批接收完成`；
- 历史任务页出现**第二条**会话（新的 session id），
  第一条会话的记录数**不再变化**；
- 两次导出不会被合并进同一个会话。

这是本阶段最关键的一条验收标准：`OVER` 结束的是批次，不是串口连接。

---

## 12. SQLite 数据验证

不需要安装任何数据库 GUI。项目自带只读查看脚本（标准库实现，以**只读**方式打开，
不可能改坏数据）。

在**后端窗口**（或新开一个终端，路径在项目根目录）执行：

```bat
backend\.venv\Scripts\python.exe scripts\inspect-db.py
```

输出包含：

- 最近若干个批次会话：会话号、状态、记录数、结束时间、端口；
- 最近一个会话的 `measurements` 行数与 `raw_lines` 行数、原始行分类统计；
- 该会话最近几条记录：原始时间串 `ts_raw`、解析后的 `ts`、
  **原始行全文**、以及解析出的字段 JSON；
- 该会话内解析失败的原始行（最多 5 条）。

指定会话与条数：

```bat
backend\.venv\Scripts\python.exe scripts\inspect-db.py --limit 10
backend\.venv\Scripts\python.exe scripts\inspect-db.py --session SES-20260922T091952-1a2b3c4d --samples 8
```

核对要点：

| 核对项 | 预期 |
| --- | --- |
| `raw_lines` 行数 | ≥ `measurements` 行数（`OVER`、表头、畸形行也在里面） |
| `status` | 正常结束为 `completed`；断开时未结束为 `interrupted` |
| 原始行最后一列 | 与解析值里的 `metric_extra_1` 完全一致 |
| `ts_raw` | 与原始行第 8 列一致，例如 `260922-091952` |
| `ts` | 对应 `2026-09-22T09:19:52`；若为"解析失败"说明仪器时间格式与预期不同，记录下来 |

数据库文件位置：`data\rail_inspection.db`（不在 Git 里）。测试完成后如需归档，
直接复制这个文件即可（复制前先按第 15 节关闭后端）。

---

## 13. 常见故障排查

按现象查，不确定的地方明确写了"需要进一步诊断"，不要凭猜测改代码。

### 13.1 `git clone` 私人仓库认证失败

- 报 `Password authentication is not supported`：GitHub 已不支持账号密码，
  用 **Git Credential Manager 弹出的浏览器登录**，或用 Personal Access Token
  作为密码（**不要**写进 URL 或任何项目文件）。
- 报 404 / repository not found：账号没有该私人仓库的读取权限，
  让仓库所有者加为 collaborator；或地址抄错。
- 公司网络拦截：换网络或改用 SSH 方式。

### 13.2 `'python' 不是内部或外部命令`

Python 未安装或未勾选 Add to PATH。重装并勾选，然后**新开终端**再跑
`scripts\check-env.bat`。若机器上装了多个 Python，可用 `py -3.11 --version` 确认，
但 `dev.bat` 依赖的是 `python` 命令，建议把需要的版本加入 PATH。

### 13.3 `node` / `npm` 找不到

同 13.2：Node 安装时会自动加 PATH，需要**新开终端**验证。
若已安装但 `npm` 报"无法加载文件 npm.ps1"，是 PowerShell 执行策略限制，
改用 **命令提示符 cmd**（本项目的 `.bat` 脚本都是给 cmd 用的）。

### 13.4 `npm install` 失败

- `ETIMEDOUT` / 网络错误：换网络，或按实验室要求配置 npm registry 镜像；
- `EPERM` / 文件被占用：关闭杀毒软件的实时扫描、关闭正在运行的前端窗口后重试；
- `node_modules` 半残（上次装失败）：删掉 `frontend\node_modules` 目录后重跑
  `scripts\dev.bat install`；
- 版本不符：`node --version` 必须满足第 3 节的 Node 版本要求。

### 13.5 `pip install` 失败

- 网络超时：`backend\.venv\Scripts\python.exe -m pip install -r requirements.txt`
  重试，或按实验室要求配置 pip 镜像源；
- 报 `No module named venv` 或创建虚拟环境失败：用的是 Windows Store 版 Python，
  改装 python.org 的官方安装包；
- 杀毒软件拦截 `.venv` 创建：把项目目录加入白名单。

### 13.6 页面打不开（浏览器显示无法访问）

- 确认 **RIC Frontend** 窗口还在运行且没有报错退出；
- 地址是 `http://localhost:5173`（不是 8000）；
- 前端窗口里若显示端口被改（例如 `5174`），用窗口里打印的那个地址；
- 防火墙/代理：浏览器代理插件可能劫持 localhost，临时关闭代理插件。

### 13.7 后端 8000 端口被占用

前端窗口会一直显示接口请求失败，后端窗口有 `[Errno 10048]` 之类的提示。
处理方式：关掉占用 8000 的程序，或用环境变量改端口后再启动
（PowerShell 示例）：

```powershell
$env:RIC_DEV_PORT_API="8010"
scripts\dev.bat
```

前端代理会自动指向同一个端口（`dev.bat` 会带上 `VITE_API_PROXY_TARGET`）。

### 13.8 前端 5173 端口被占用

```powershell
$env:RIC_DEV_PORT_WEB="5180"
scripts\dev.bat
```

浏览器改用新端口访问。

### 13.9 找不到 CP210x（枚举结果为空）

下拉框显示"当前系统无可用串口"：设备管理器里没有该端口。
按第 4 节处理驱动 / 换数据线 / 换 USB 口。**这一步没通过时不要继续往下测。**

### 13.10 CP210x 有黄色感叹号

驱动未正确安装或版本不匹配：设备管理器里右键 → 卸载设备（勾选删除驱动）→
重新安装 CP210x VCP 驱动 → 重新插拔。仍失败需要进一步诊断
（可能是 USB 供电或线材问题，也可能仪器端串口板异常）。

### 13.11 COM 口被 SSCOM 占用

程序会明确提示"串口 COMx 正被其他程序占用（例如 SSCOM），请先关闭该程序再连接"。
完全退出 SSCOM（确认托盘里没有残留进程）后重新建立链路。
反过来也一样：本程序连着串口时，SSCOM 也打不开同一个端口。

### 13.12 COM 编号不是 COM7

正常情况。**COM 号以实验室电脑为准**，在系统设置的下拉框里选实际那一个即可。
默认值 COM7 只在"没指定端口且没识别到 CP210x"时才作为兜底，
程序优先自动选择描述含 CP210x / Silicon Labs 的端口。

### 13.13 建立链路成功但没有数据

按顺序确认：

1. 状态是不是 **等待仪器导出**（`connected_waiting`）——这是正常待命状态，
   没人按导出就不会有数据；
2. 仪器是否真的执行了"导出记录"（有些型号需要菜单里确认）；
3. 数据线是否为能传数据的线（部分线只有电源芯）；
4. 仪器端波特率是否 115200（若仪器侧不是这个值，属于参数不一致，需要核对，
   **不要**擅自改程序默认值）；
5. 若以上都确认仍无数据 → 需要进一步诊断：把设备管理器端口号、仪器设置截图留存。

### 13.14 DHJ-9 点导出后网页无变化

- 先确认没在 Mock 模式（页面有"演示数据"标记就是还没切真实模式，见 13.17）；
- 看 **RIC Backend** 窗口有没有收到数据/报错日志；
- 状态若一直是 **等待仪器导出** 且后端也没有任何行计数增加 → 串口没读到字节，
  回到 13.13；
- 状态变了但页面不动 → 按 Ctrl+F5 强刷（见 13.18），并检查 WebSocket 是否连上
  （浏览器开发者工具 Network → WS → `/ws/live`）。

### 13.15 一直 receiving，没有收到 OVER

- 先等足够久：仪器导出速度取决于它自身，批次未结束前状态会保持 `receiving`；
- 若仪器确实已停止输出而程序一直等：这批数据仍会在**断开链路或关闭后端时**
  被写入数据库（会话状态记为 `interrupted`），不会丢；
- 需要进一步诊断：记录仪器型号/固件、导出条数、等待时长。
  `OVER` 丢失的超时收尾机制目前**尚未实现**（属于后续阶段），现场请以
  "重新导出一次"作为恢复手段。

### 13.16 数据出现但字段异常

- 先看"串口原始数据保留"面板里的**原始行**：如果原始行本身就与样例格式不同，
  是仪器输出格式问题，把原始行完整记录下来；
- 如果原始行正确但解析值不对（例如某列变成空或解析失败），
  核对 `backend\config\parser.yaml` 的字段定义是否被改动过；
- `metric_extra_1` 的含义**尚未确认**，不要把它当水平、超高或倾角来解释，
  也不要在报告里给它编一个名字；
- 时间列解析失败（`ts` 为空、`ts_raw` 有值）说明仪器时间格式与
  `yyMMdd-HHmmss` 不同，需要记录实际样例后确认，不要自行改格式串。

### 13.17 Mock 数据没有关闭

页面仍有 **演示数据** 标记即仍在 Mock：

- 确认改的是 `frontend\.env`（不是 `.env.example`），且值为 `VITE_USE_MOCK=false`；
- 改完必须**重启前端**（`.env` 只在启动时读取）；
- 若 `frontend\.env` 不存在，`dev.bat` 会从 `.env.example` 生成一份，注意别改错文件。

### 13.18 浏览器缓存旧前端

用 **Ctrl+F5** 强制刷新，或开一个无痕窗口访问 `http://localhost:5173`。
判断依据：页面显示的数值格式/字段名与代码里不一致时，多半是旧包，
清缓存或重启前端即可。

---

## 14. 测试结果记录模板

现场逐项填写（复制到纸质记录或单独文件里都可以）。

```
实验日期：
电脑（编号/名称）：
Windows 版本：
Git / Python / Node 版本：
CP210x COM 号：
驱动状态（正常 / 有感叹号 / 未识别）：
check-env.bat 结果：
后端测试（pytest）：
前端 TypeScript：
Vite build：
test-all.bat 结果：
Mock 模式五页可打开：
演示数据标记已消失（切换真实模式后）：
建立链路后状态：
第一次导出条数：
第一次 session id：
第一次 OVER 正常（是/否）：
第二次导出条数：
第二次 session id：
两次 session 是否分离：
SQLite 验证（inspect-db.py 输出是否正常）：
原始行是否完整保留（含 OVER）：
WebSocket 实时推送是否正常：
metric_extra_1 数值范围（仅记录，不作判定）：
问题记录（现象 + 原始行 + 后端窗口日志）：
处理结果 / 待跟进：
测试人：
```

---

## 15. 测试完成后如何安全关闭

按顺序：

1. 浏览器关掉页面（不影响服务，但避免误操作）。
2. 在 **系统设置** 页点 **断开链路**（或 **断开**）：
   会话会收尾，未结束的批次记为 `interrupted`，数据不丢。
3. 关闭 **RIC Frontend** 终端窗口（Ctrl+C 后关窗）。
4. 关闭 **RIC Backend** 终端窗口（Ctrl+C 后关窗）。
   等窗口打印关闭日志后再关，让 SQLite 正常 checkpoint。
5. 需要归档数据：复制 `data\rail_inspection.db` 一份带走
   （该文件不在 Git 里，不会被误提交）。
6. 拔 USB 线。
7. **不要**把 `data\rail_inspection.db`、`frontend\.env`、
   `backend\.venv`、`frontend\node_modules` 提交进 Git；
   它们已在 `.gitignore` 中。若确实要交接数据，单独传数据库文件。

---

## 附：本指南用到的命令速查

```bat
scripts\check-env.bat        :: 只读环境检查，通过/失败
scripts\dev.bat install      :: 首次安装依赖（venv + pip + npm），不启动服务
scripts\test-all.bat         :: pytest + tsc + vite build，全 PASS 才继续
scripts\dev.bat              :: 启动后端(8000) + 前端(5173)，两个窗口
scripts\dev.bat backend      :: 只启动后端
scripts\dev.bat frontend     :: 只启动前端
```

```bat
backend\.venv\Scripts\python.exe scripts\inspect-db.py     :: 只读查看批次数据
```

地址：前端 <http://localhost:5173>，后端 <http://127.0.0.1:8000>，
接口文档 <http://127.0.0.1:8000/docs>，健康检查 <http://127.0.0.1:8000/api/health>。

> `scripts\*.bat` 以 **GBK** 保存以适配中文版 Windows 控制台。
> 如果用 UTF-8 编辑器改这些脚本，中文会变乱码、脚本也可能解析失败；
> 需要改动时请用 GBK/ANSI 编码保存，或只改 ASCII 部分。
