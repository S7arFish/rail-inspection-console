#!/usr/bin/env bash
# ===========================================================================
#  Start the RIC Console backend service on the Raspberry Pi.
#  Only touches systemd: it never launches or kills Chromium.
# ===========================================================================
set -euo pipefail

SERVICE_NAME="ric-console"
ENV_FILE="/etc/ric-console/ric-console.env"
WAIT_S="${RIC_START_WAIT_S:-30}"

if [[ "$(id -u)" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
  echo "[提示] 需要 sudo 权限控制系统服务，正在重新以 sudo 运行"
  exec sudo -E bash "$0" "$@"
fi

run() {
  if [[ "$(id -u)" -eq 0 ]]; then systemctl "$@"; else sudo systemctl "$@"; fi
}

RIC_HOST="127.0.0.1"
RIC_PORT="8000"
if [[ -r "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
fi

echo "[信息] 启动 ${SERVICE_NAME}..."
run start "${SERVICE_NAME}.service"

URL="http://${RIC_HOST}:${RIC_PORT}/api/health"
echo "[信息] 等待健康检查：${URL}"
deadline=$((SECONDS + WAIT_S))
until curl -fsS --max-time 3 "${URL}" >/dev/null 2>&1; do
  if ((SECONDS > deadline)); then
    echo "[错误] ${WAIT_S}s 内没有就绪。日志：journalctl -u ${SERVICE_NAME} -n 60 --no-pager" >&2
    exit 1
  fi
  sleep 1
done
echo "[成功] RIC 后端已运行：$(curl -fsS --max-time 3 "${URL}")"
echo "       中控页面：http://${RIC_HOST}:${RIC_PORT}"
