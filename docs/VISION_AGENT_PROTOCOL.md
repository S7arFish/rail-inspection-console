# Vision Agent 协议与进程边界（设计说明）

状态：**架构预定义，尚未实现**。M2-0B 只完成 USB 摄像头环境预检，
没有 OpenCV、没有识别算法、没有 vision agent 进程。
本文的作用是把边界先固定下来，避免以后把视觉主循环塞进 Web 后端。

---

## 1. 目标拓扑

```
USB-A 摄像头（型号待定，按标准 UVC 假设）
        │  V4L2  /dev/video*
        ▼
vision agent（独立进程，Raspberry Pi 本机）
        │  HTTP / WebSocket 到 127.0.0.1
        ▼
RIC backend（FastAPI, ric-console.service）
        │  /ws/live 广播
        ▼
Chromium Kiosk（HDMI 本机显示）

DHJ-9 接触网激光检测仪
        │  CP2102 /dev/ttyUSB0
        ▼
SerialService（与 vision agent 完全无关的另一条链路）
```

摄像头**不是**网络摄像头，也不通过 RTSP/HTTP 拉流；就是 Pi 上的 USB 设备。

## 2. 为什么 vision agent 必须分进程

| 理由 | 说明 |
| --- | --- |
| 故障隔离 | OpenCV / 驱动崩溃、内存增长、句柄泄漏都只杀掉 agent，不会让中控页面失去后端 |
| DHJ-9 优先 | 采集激光检测数据是比赛主链路；串口读线程不能被逐帧图像处理抢占 CPU 或 GIL |
| 不阻塞事件循环 | FastAPI 的 event loop 必须保持轻量；把 `cap.read()` 循环放进去会拖慢 WebSocket 与 REST |
| 独立生命周期 | agent 可以单独 restart / 升级 / 关闭，中控与串口不受影响 |
| 独立调参 | FPS、分辨率、色彩空间、模型可单独调整与回滚 |
| 资源可控 | 可以单独用 `Nice`/`CPUQuota`/cgroup 限制视觉进程，不挤占采集 |

因此明确禁止：

* 把 OpenCV 主循环写进 FastAPI 的 handler 或 lifespan；
* 在 `SerialService` 的读线程里做任何图像工作；
* 让摄像头异常导致 `ric-console.service` 退出。

## 3. 事件契约（沿用 M2-0A 的 envelope）

所有 `/ws/live` 帧统一为 `{ type, source, timestamp, payload }`。
DHJ-9 的 `source` 固定为 `dhj9`；视觉侧预留 `rpi_vision`：

```json
{
  "type": "vision.detection",
  "source": "rpi_vision",
  "timestamp": "2026-09-23T09:15:04.221+00:00",
  "payload": {
    "frame_id": 18422,
    "camera": "/dev/video0",
    "ts_capture": "…",
    "result": { "…": "由 M2-1 的真实摄像头与算法定义，本轮不猜字段" }
  }
}
```

约束：

* `type` 用 `<域>.<事件>` 命名，域与 `source` 一致，便于前端按来源分流；
* `payload` 内部结构由各来源自己负责，**不共享** DHJ-9 的 `fields` 语义；
* 新增来源不得修改已有事件的字段含义；
* 本轮不新增任何 API 端点，也不修改现有 WebSocket 事件。

## 4. 与数据库的关系

`measurements` / `raw_lines` 属于 DHJ-9 采集链路，视觉结果**不写入**这两张表。
等 M2-1 明确要存什么之后，再单独设计视觉结果表与保留策略
（帧图默认不入库，只存结论 + 关联的 `session_id` / 时间戳，避免 SD 卡被写满）。

## 5. 本轮已完成的准备（M2-0B）

`scripts/pi-install.sh` 的第 4 步只做环境预检：

* `modprobe uvcvideo`；
* 用户加入 `video` 组；
* `lsusb` 与 `/dev/video*` 探测；
* 可用时安装 `v4l-utils`，并用 `v4l2-ctl --list-devices` 列出设备；
* 有 USB 设备但没有 V4L2 节点时，只报告
  「检测到 USB 设备但未发现 V4L2 摄像头，需要进一步确认驱动」，
  **不下载未知厂商驱动**。

手工复核命令：

```bash
lsusb
ls -l /dev/video*
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext     # 确认分辨率/像素格式
id -nG                                          # 确认在 video 组
```

## 6. 留给 M2-1 的未决事项

1. **摄像头型号与像素格式**：未知，决定是否需要额外驱动；
2. **OpenCV 安装路径**：现在刻意不做决定。两条候选：
   * 系统 Python 3.7 + `apt install python3-opencv`（Buster 有包，但版本旧）；
   * 项目 Python 3.11 + pip wheel / 自行编译（ARMv7 wheel 可用性需实测）；
   在拿到真实摄像头和一次成功的帧读取之前，任何选择都只是猜测；
3. **抽帧策略**：FPS 上限、是否需要与 DHJ-9 的 `record_no` / 时间戳对齐；
4. **agent 的部署形态**：独立 venv + 独立 systemd unit（建议
   `ric-vision.service`，`Restart=on-failure`，与后端解耦）；
5. **结果如何进前端**：走同一个 `/ws/live`（推荐，复用现有 envelope）
   还是单独 `/ws/vision`；
6. **SD 卡寿命**：是否需要日志限流与图片落盘策略。

## 7. 相关文档

* [RASPBERRY_PI_DEPLOYMENT.md](RASPBERRY_PI_DEPLOYMENT.md) — 部署与 Kiosk
* [WINDOWS_SETUP_AND_DHJ9_TEST.md](WINDOWS_SETUP_AND_DHJ9_TEST.md) — DHJ-9 真机测试流程
* 仓库根 `README.md` — 数据契约与 `metric_extra_1` 的未确认状态
