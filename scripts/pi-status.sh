#!/usr/bin/env bash
# ===========================================================================
#  RIC Console status board for the Raspberry Pi. Read-only: it never starts,
#  stops or restarts anything, and it never touches the database.
#
#  ./scripts/pi-status.sh
# ===========================================================================
set -uo pipefail   # deliberately no -e: every probe must still be reported

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="ric-console"
ENV_FILE="/etc/ric-console/ric-console.env"
DHJ9_VID_PID="10c4:ea60"

RIC_HOST="127.0.0.1"
RIC_PORT="8000"
if [[ -r "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
fi
URL="http://${RIC_HOST}:${RIC_PORT}"

line() { printf -- '----------------------------------------\n'; }
field() { printf '  %-22s %s\n' "$1" "$2"; }

echo "RIC Console 状态  $(date '+%F %T')"
line

echo "[后端服务]"
if command -v systemctl >/dev/null 2>&1; then
  STATE="$(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"
  ENABLED="$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
  case "${STATE}" in
    active)   field "systemd" "运行中 (enabled=${ENABLED:-?})" ;;
    "")       field "systemd" "未安装该服务" ;;
    *)        field "systemd" "${STATE} (enabled=${ENABLED:-?})" ;;
  esac
else
  field "systemd" "不可用（不是 systemd 系统？）"
fi

HEALTH="$(curl -fsS --max-time 3 "${URL}/api/health" 2>/dev/null || true)"
if [[ -n "${HEALTH}" ]]; then
  field "health" "OK"
  printf '    %s\n' "${HEALTH}"
else
  field "health" "无响应（${URL}/api/health）"
fi

if curl -fsS --max-time 3 "${URL}/" >/dev/null 2>&1; then
  field "本机页面" "${URL}"
else
  field "本机页面" "不可访问"
fi

line
echo "[DHJ-9 采集链路]"
if command -v lsusb >/dev/null 2>&1; then
  if lsusb 2>/dev/null | grep -qi "${DHJ9_VID_PID}"; then
    field "USB ${DHJ9_VID_PID}" "已插入（CP2102）"
  elif lsusb 2>/dev/null | grep -qiE 'silicon labs|cp210'; then
    field "USB ${DHJ9_VID_PID}" "已插入（按厂商名匹配）"
  else
    field "USB ${DHJ9_VID_PID}" "未找到"
  fi
else
  field "lsusb" "未安装（sudo apt-get install usbutils）"
fi

if lsmod 2>/dev/null | awk '{print $1}' | grep -qx cp210x; then
  field "内核模块 cp210x" "已加载"
else
  field "内核模块 cp210x" "未加载"
fi

if compgen -G '/dev/ttyUSB*' >/dev/null; then
  DEVICES="$(ls /dev/ttyUSB* | tr '\n' ' ')"
  field "串口设备" "${DEVICES}"
  for d in ${DEVICES}; do
    OWNER="$(stat -c '%U:%G %a' "${d}" 2>/dev/null || echo '?')"
    field "  ${d}" "${OWNER}"
  done
else
  field "串口设备" "无 /dev/ttyUSB*"
fi

if id -nG "$(id -un)" 2>/dev/null | tr ' ' '\n' | grep -qx dialout; then
  field "当前用户 dialout" "是"
else
  field "当前用户 dialout" "否（需重新登录或 usermod -aG dialout）"
fi

line
echo "[USB 摄像头（预检，不含识别）]"
if compgen -G '/dev/video*' >/dev/null; then
  field "V4L2 设备" "$(ls /dev/video* | tr '\n' ' ')"
else
  field "V4L2 设备" "无 /dev/video*"
fi
if lsmod 2>/dev/null | awk '{print $1}' | grep -qx uvcvideo; then
  field "内核模块 uvcvideo" "已加载"
else
  field "内核模块 uvcvideo" "未加载"
fi
if command -v v4l2-ctl >/dev/null 2>&1; then
  field "v4l-utils" "已安装"
else
  field "v4l-utils" "未安装"
fi
if id -nG "$(id -un)" 2>/dev/null | tr ' ' '\n' | grep -qx video; then
  field "当前用户 video" "是"
else
  field "当前用户 video" "否"
fi

line
echo "[显示与浏览器]"
if pgrep -x chromium-browser >/dev/null 2>&1 || pgrep -x chromium >/dev/null 2>&1; then
  field "Chromium" "正在运行"
else
  field "Chromium" "未运行（Kiosk 由桌面自启动，或执行 scripts/pi-kiosk.sh）"
fi
field "DISPLAY" "${DISPLAY:-<未设置>}"
field "wayland" "${WAYLAND_DISPLAY:-<无>}"

line
echo "[本机地址（仅诊断用；中控默认只监听 ${RIC_HOST}:${RIC_PORT}）]"
if command -v hostname >/dev/null 2>&1; then
  field "IP" "$(hostname -I 2>/dev/null | tr -s ' ' || echo '?')"
fi
field "项目目录" "${REPO_DIR}"
if [[ -f "${REPO_DIR}/deploy/pi/web/index.html" ]]; then
  field "前端产物" "存在"
else
  field "前端产物" "缺失（在开发机运行 scripts\\package-pi-web.bat）"
fi
if [[ -f "${REPO_DIR}/data/rail_inspection.db" ]]; then
  field "数据库" "$(du -h "${REPO_DIR}/data/rail_inspection.db" 2>/dev/null | cut -f1) ${REPO_DIR}/data/rail_inspection.db"
else
  field "数据库" "尚未创建（后端首次启动时自动建库）"
fi
line
echo "日志：journalctl -u ${SERVICE_NAME} -f"
