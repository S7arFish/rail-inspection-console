# 轨道检测车综合检测中控平台 (RIC Console)

Windows 11 本地运行的轨道检测车综合检测中控平台。当前进度为 **M1：DHJ-9 真机数据闭环**
——串口采集、批次会话、SQLite 落库、WebSocket 推送与五个前端页面的数据绑定已打通。

> **边界（重要）**
> 1. 字段名以 DHJ-9 仪器表头为准（0–10 已确认），解析规则完全由
>    `backend/config/parser.yaml` 驱动，代码中不出现任何字段名常量。
> 2. **不存在任何检测阈值**。后端没有阈值表、没有异常规则引擎；真实模式前端只显示
>    “检测标准未配置”，不显示“正常/异常”。
> 3. 表头只有 11 个列名、每条记录却有 12 个字段，因此第 12 列保持中性名
>    `metric_extra_1`，**不得**改名为水平、超高、倾角等任何猜测。
> 4. DHJ-9 按需导出，不是连续实时流：一次“导出记录”= 一个批次 = 一个会话。

---

## 目录结构

```
rail-inspection-console/
├─ backend/                  Python FastAPI 采集与数据服务
│  ├─ app/
│  │  ├─ main.py             应用工厂 + lifespan（建库、绑定事件循环、停机）
│  │  ├─ settings.py         环境变量配置（含 .env 读取，无第三方 dotenv）
│  │  ├─ schemas.py          HTTP/WS 数据契约模型
│  │  ├─ deps.py             依赖容器 + 线程外派发 helper
│  │  ├─ api/                薄路由：serial / sessions / live / system
│  │  ├─ parser/             可配置行解析器（由 parser.yaml 驱动）
│  │  ├─ db/                 标准库 sqlite3：database.py（连接/建表） + repository.py（读写）
│  │  └─ services/
│  │     ├─ serial_service.py  SerialService：全部串口逻辑
│  │     └─ realtime.py        WebSocket 连接管理与跨线程事件桥
│  ├─ config/parser.yaml     ★ 字段映射唯一真源
│  ├─ tests/                 pytest：解析映射 / 批次状态机 / WS 契约
│  ├─ pytest.ini
│  ├─ requirements.txt       运行时依赖
│  ├─ requirements-dev.txt   仅测试依赖（pytest）
│  └─ .env.example
├─ frontend/                 React + Vite + TypeScript + shadcn/ui
│  └─ src/
│     ├─ routes/             TanStack Router 文件路由（_layout 下 5 个页面）
│     ├─ features/           dashboard / anomalies / history / analytics / settings
│     ├─ components/         ui（shadcn 原语）· data-table（表格套件）· layout · console · charts
│     ├─ context/            theme / layout / font / direction / search / live-feed
│     ├─ hooks/              use-live-feed（WS 或 mock 心跳）· use-parser-fields
│     ├─ lib/                api-client · data-source（mock/真实切换）· echarts · format
│     ├─ mock/fixtures.ts    演示数据（确定性随机，锚定在真实样例数值上）
│     ├─ types/              domain.ts（后端契约）· console.ts（后端尚未提供的形态）
│     └─ styles/             index.css · theme.css（工业深色主题）
├─ data/                     SQLite 数据库目录（.db 不入库，首次启动自动建库）
├─ scripts/
│  ├─ dev.bat                一键启动/安装前后端开发环境
│  ├─ check-env.bat          新电脑环境检查（git/python/node/npm + 目录文件）
│  ├─ test-all.bat           全项目检查（pytest + tsc + vite build）
│  └─ inspect-db.py          只读查看批次数据（标准库，不改数据库）
├─ docs/WINDOWS_SETUP_AND_DHJ9_TEST.md   新电脑部署与真机测试指南
└─ README.md
```

前端基于 [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin) v2.2.1
（React 19 + Vite + TS + Tailwind v4 + shadcn/ui + TanStack Router/Query/Table）搭建，
已删除认证、Clerk、用户管理、Tasks/Apps/Chats 等无关业务页面，保留 Sidebar、Theme、
Table 套件、命令面板、布局与主题上下文。

---

## 运行

### 一键（推荐）

```bat
scripts\check-env.bat        :: 只读检查环境（git/python/node/npm + 目录），不改系统
scripts\dev.bat install      :: 只装依赖（自动建 venv、npm install、生成 frontend\.env）
scripts\test-all.bat         :: 后端测试 + 前端类型检查 + 前端构建，失败即停
scripts\dev.bat              :: 首次会自动建 venv、装依赖，然后开两个窗口
scripts\dev.bat backend      :: 只起后端
scripts\dev.bat frontend     :: 只起前端
```

后端 `http://127.0.0.1:8000`（文档 `/docs`），前端 `http://localhost:5173`。

**全新 Windows 电脑部署、以及连接真实 DHJ-9 做完整测试，详见：
[docs/WINDOWS_SETUP_AND_DHJ9_TEST.md](docs/WINDOWS_SETUP_AND_DHJ9_TEST.md)。**
那份文档从零开始（克隆 → 装环境 → 驱动 → 测试 → Mock 自检 → 切真实模式 →
两次导出验证 → SQLite 核对 → 故障排查 → 记录模板）。

`scripts\*.bat` 以 GBK 保存以适配中文版 Windows 控制台；用 UTF-8 编辑器改动会破坏中文，
需要修改时请用 ANSI/GBK 编码保存。

### 手动

```bat
:: 后端
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

:: 前端
cd frontend
npm install
npm run dev
```

### 前后端联通

`vite.config.ts` 把 `/api` 与 `/ws`（含 WebSocket 升级）代理到
`VITE_API_PROXY_TARGET`（默认 `http://127.0.0.1:8000`），因此开发期浏览器只与
5173 通信，后端无需处理 CORS。生产部署时改为直接设置
`VITE_API_BASE_URL` / `VITE_WS_URL`。

**Mock 开关**：`frontend/.env` 中 `VITE_USE_MOCK`（默认 `true`）。
设为 `false` 后所有读取走真实后端，界面不再显示“演示数据”标记。

---

## 数据流

```
DHJ-9 接触网激光检测仪  （按需导出，不是连续实时流）
   │  Silicon Labs CP210x USB-to-UART，115200 8N1 无流控（通常 COM7，不硬编码）
   ▼
Windows 串口 (pyserial 直读，不依赖 SSCOM)
   └─ SerialService 读线程（逐行文本）
        ├─ LineParser（parser.yaml：位置→字段名/类型；表头行=header；OVER=批次结束）
        ├─ SQLite：raw_lines 逐行原样存档（data|control|invalid）
        │          measurements 解析结果（fields 为 JSON，键来自配置；ts_raw 保留原始时间串）
        │          sessions   **一次导出 = 一个 session**
        └─ WebSocket /ws/live → laser.measurement / session.complete / laser.status / laser.parse_error
```

每条合法数据都做到：**① 解析 ② raw 行原样入库 ③ 解析结果写 SQLite ④ WebSocket 推送**。

## 批次状态机

```
disconnected ──connect──> connecting ──
                                       v
                              connected_waiting   ← 串口已打开，等待用户点“导出记录”
                                       │  收到第一条 header 或数据记录（此时才创建 session）
                                       v
                                  receiving       ← 每收到一条合法数据 records_in_batch += 1
                                       │  收到 OVER
                                       v
                              batch_complete      ← 瞬态：flush + 写 ended_at + status=completed
                                       │            + 推送 session.complete
                                       v
                              connected_waiting   ← 串口保持打开，等待下一次导出（新建 session）
```

要点：`connect` **不**创建 session；`OVER` 结束的是批次，不是串口连接；断开时若仍有未结束的
批次，该批次记为 `interrupted`；读线程故障则记为 `failed`。
`GET /api/serial/status` 的 `port` 只在链路为活时返回，失败尝试不会把端口号泄漏给界面。

## WebSocket 事件

每一帧都是 `{ type, source, timestamp, payload }`。`source` 标明数据来源，
DHJ-9 固定为 `dhj9`，传输层回复（`pong` / `error`）为 `console`；
以后接入第二数据源（如 Raspberry Pi 视觉）可复用同一 socket 而不歧义。

| type | 时机 | payload |
| --- | --- | --- |
| `laser.snapshot` | 连接建立后立即 | `status` / `session` / `measurements` / `parser` |
| `laser.measurement` | 每条合法数据 | 一条 measurement（`fields`、`raw_line`、`ts`、`ts_raw`、`session_id`） |
| `session.complete` | 收到 `OVER` | `session_id` / `record_count` / `batch_seq` / `started_at` / `ended_at` / `status` |
| `laser.status` | 状态变化 | 同 `/api/serial/status` |
| `laser.parse_error` | 畸形行 | `line` / `reason` |

客户端可发送 `{"type":"ping"}`，服务端回 `{"type":"pong","source":"console",...}`。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/serial/ports` | 枚举串口，`suggested_port` 优先匹配 CP210x / Silicon Labs |
| POST | `/api/serial/connect` | 打开串口并等待导出，缺省即 COM7/115200/8/N/1/none |
| POST | `/api/serial/disconnect` | 停止读取、收尾未完成批次、关闭串口 |
| GET | `/api/serial/status` | 链路状态、参数、`records_in_batch`、样本/批次/错误计数 |
| GET | `/api/sessions` | 会话（=批次）分页列表 |
| GET | `/api/sessions/{id}` | 会话详情 + 样本 |
| WS | `/ws/live` | 见上表 |
| GET | `/api/parser/fields` | 当前字段映射（前端据此绑定标签与图表） |
| GET | `/api/health` | 版本、库路径、串口状态 |

串口逻辑全部在 `SerialService` 内，`app/api/*` 只做参数校验与委派。
端口被其他程序（例如 SSCOM）占用时返回中文提示，不抛 traceback、不使服务崩溃。

## 数据契约现状

仪器表头给出 11 个列名，而每条记录实际有 12 个字段——第 12 列在表头中没有对应项。
样例行 `0,0,0,0,0,1,1,260922-091952,2121.5,582.2,1434.6,-9.8`：

| 位置 | 字段名 | 表头 | 已确认 |
| --- | --- | --- | --- |
| 0 | `record_type` | 记录类型 | 是 |
| 1 | `measure_direction` | 测量方向 | 是 |
| 2 | `record_no` | 记录号 | 是 |
| 3 | `line_no` | 线号 | 是 |
| 4 | `work_area` | 工区 | 是 |
| 5 | `pole_no` | 杆号 | 是 |
| 6 | `measure_position` | 测量位置 | 是 |
| 7 | `timestamp` | 时间（`yyMMdd-HHmmss`） | 是 |
| 8 | `height` | 高度 | 是 |
| 9 | `pull_out` | 拉出 | 是 |
| 10 | `gauge` | 轨距 | 是 |
| 11 | `metric_extra_1` | 无对应表头 | **否，保持中性名，禁止猜测** |

单位一律留空（`unit: null`）：表头只给了名字，没给单位。
SSCOM 截图里的 `[16:41:05.296]收←◆` 是 SSCOM 自己的显示前缀，不属于 DHJ-9 协议，
parser 既不依赖也不剥离它。

字段含义再变更时**只需改 `parser.yaml`**：前端标签、图表序列、设置页字段表都从
`/api/parser/fields` 读取，不写死。原始行已入库，可离线重解析而无需重采。

## 测试

```bat
scripts\test-all.bat    :: 后端测试 + 前端类型检查 + 前端构建（推荐）
```

```bat
cd backend
.venv\Scripts\python.exe -m pytest
```

`backend/tests/` 覆盖：真实记录到 12 个字段的映射、时间戳原始串与归一化、表头行、
`OVER` 批次状态机（一个批次一个 session、结束后回到 `connected_waiting`、第二次导出生成
第二个 session）、畸形/空/未知文本不崩溃、端口占用与端口不存在的中文提示、
以及 WebSocket 帧的 `{type, source, timestamp, payload}` 结构与 `source == "dhj9"`。

## 真机测试步骤（DHJ-9）

1. 关闭 SSCOM（否则串口被占用，会得到中文提示）。
2. `scripts\dev.bat` 启动前后端。
3. 系统设置 → 串口参数：下拉应出现 `COM7 · 推荐 Silicon Labs CP210x …`，确认 115200 / 8 / N / 1 / 无流控。
4. 点“建立链路”：侧栏与设置页应显示 **等待仪器导出**（`connected_waiting`），此时还没有会话。
5. 在 DHJ-9 上点“导出记录”：状态转为 **正在接收**，`已接收 N 条` 递增，Dashboard 数值与趋势随之追加。
6. 仪器发完 `OVER`：显示 **本批接收完成 · 共 N 条 · 等待下一次导出**，串口保持连接。
7. 历史任务页应出现刚结束的那个批次（第二条记录是新的 session，不会写进第一条）。
8. 关掉设备或拔线：状态进入 `error` 并给出中文原因，重新“建立链路”即可。

## 当前哪些是 mock

| 位置 | 状态 |
| --- | --- |
| Dashboard 数值/趋势/点位条/最近异常 | `VITE_USE_MOCK=true` 时为演示数据；真实模式全部来自后端 |
| 异常检测列表 | 演示数据；后端**没有**异常表与阈值，真实模式返回空 |
| 历史任务 | 演示数据；真实模式走 `/api/sessions`（=批次列表） |
| 数据分析 | 演示样本；统计量由前端计算，真实模式取该会话样本 |
| 系统设置 → 串口参数 | 演示模式仅展示；真实模式读写 `/api/serial/*` |
| 系统设置 → 字段映射 | 真实模式来自 `/api/parser/fields`（只读） |
| 点位条的“判定”着色 | 仅演示模式出现；真实模式统一中性色并显示“检测标准未配置” |

演示数据锚定在上面那条真实样例的数值量级上，用确定性随机（mulberry32）生成，
因此刷新后版面稳定，便于评审。

## 已验证 / 未验证

已验证：`pytest` 27 项全通过（真实 parser.yaml + 真实 SQLite + 假串口）；`tsc -b` 与
`vite build` 通过；`eslint` 0 error；`/api/parser/fields` 返回 0–10 已确认、11 为
`metric_extra_1` 未确认；`/api/serial/status` 含 `records_in_batch` 且失败时 `port` 为
`null`；端口不存在/被占用返回中文提示；`/ws/live` 首帧 `laser.snapshot` 与 `pong` 的
`{type, source, timestamp, payload}` 结构与 `source` 取值；mock 与真实两种模式下五个页面
在浏览器中实际渲染（真实模式无演示标记、无“正常/异常”判定）。

未验证：**真实 DHJ-9 与真实 CP210x 端口上的导出流程**——本机没有任何 COM 设备，
`connected_waiting → receiving → batch_complete` 的推进目前只由假串口与直接喂行验证过；
半行残留（一次导出的最后一段没有 `
`）、仪器实际波特率漂移、表头行是否真的会发送、
以及 1920 宽桌面栅格同样未验证。

## 下一步建议

1. **真机跑一次**：按上面「真机测试步骤」验证状态机与 `record_count`，确认仪器是否真的会发表头行。
2. **单位与枚举**：向硬件方要 0–6 列的取值范围与 8–11 列的单位，回填 `parser.yaml`（名字已确认，单位仍缺）。
3. **重解析脚本**：字段/单位再有变更时，按新配置重放 `raw_lines` 重建 `measurements`。
4. **阈值与判定**：先定义规则数据结构（字段、上下限、迟滞、生效范围、来源），再建 `anomalies`
   表与引擎；前端异常页改为读接口，届时才恢复“正常/注意/报警”着色。
5. **串口健壮性**：自动重连、半行超时、`OVER` 丢失时的批次超时收尾。
6. **数据量**：样本表保留策略与 CSV 导出。
7. **界面**：趋势图小图分面（每指标独立纵轴）与 1920 宽栅格评审。
