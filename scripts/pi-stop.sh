#!/usr/bin/env bash
# ===========================================================================
#  Stop the RIC Console backend service on the Raspberry Pi.
#
#  Deliberately narrow: it stops only ${SERVICE_NAME}. It never kills Chromium,
#  because the operator may have other browser windows open on the same Pi, and
#  the kiosk is a desktop-session concern, not a backend one.
# ===========================================================================
set -euo pipefail

SERVICE_NAME="ric-console"

if [[ "$(id -u)" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
  echo "[提示] 需要 sudo 权限控制系统服务，正在重新以 sudo 运行"
  exec sudo -E bash "$0" "$@"
fi

run() {
  if [[ "$(id -u)" -eq 0 ]]; then systemctl "$@"; else sudo systemctl "$@"; fi
}

echo "[信息] 停止 ${SERVICE_NAME}（串口链路会被收尾：未结束的批次记为 interrupted）"
run stop "${SERVICE_NAME}.service"

if run is-active --quiet "${SERVICE_NAME}.service"; then
  echo "[错误] 服务仍在运行，请查看：journalctl -u ${SERVICE_NAME} -n 40" >&2
  exit 1
fi
echo "[成功] ${SERVICE_NAME} 已停止"
echo "       Kiosk 页面会显示连接失败；重启服务：scripts/pi-start.sh"
