#!/usr/bin/env bash
# ===========================================================================
#  RIC Console HDMI kiosk launcher — run as the DESKTOP USER, never as root.
#
#  Called by ~/.config/autostart/ric-console-kiosk.desktop after login, or by
#  hand: ./scripts/pi-kiosk.sh
#
#  It waits for the backend to answer /api/health (so the screen never shows a
#  white error page while systemd is still starting uvicorn), then opens
#  Chromium full-screen with no address bar.
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="/etc/ric-console/ric-console.env"
WAIT_TIMEOUT_S="${RIC_KIOSK_WAIT_S:-60}"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "[错误] 不要用 root 运行 Kiosk：Chromium 会以 root 身份浏览网页。" >&2
  echo "       请以桌面用户身份执行：$0" >&2
  exit 1
fi

RIC_HOST="127.0.0.1"
RIC_PORT="8000"
if [[ -r "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
fi
URL="http://${RIC_HOST:-127.0.0.1}:${RIC_PORT:-8000}"
HEALTH_URL="${URL}/api/health"

echo "[信息] 等待 RIC 后端：${HEALTH_URL}（最多 ${WAIT_TIMEOUT_S}s）"
deadline=$((SECONDS + WAIT_TIMEOUT_S))
until curl -fsS --max-time 3 "${HEALTH_URL}" >/dev/null 2>&1; do
  if ((SECONDS > deadline)); then
    echo "[错误] 后端在 ${WAIT_TIMEOUT_S}s 内没有就绪，Kiosk 暂不启动。" >&2
    echo "       检查：systemctl status ric-console   或   journalctl -u ric-console -n 40" >&2
    exit 1
  fi
  sleep 2
done
echo "[成功] 后端已就绪，启动全屏中控"

# Keep the panel awake while the console is on show. Missing xset (Wayland, no
# X tools, headless) is only a warning: it must never abort the kiosk.
if command -v xset >/dev/null 2>&1 && [[ -n "${DISPLAY:-}" ]]; then
  xset s off         2>/dev/null || echo "[警告] xset s off 失败，屏幕仍可能休眠"
  xset s noblank     2>/dev/null || true
  xset -dpms         2>/dev/null || echo "[警告] xset -dpms 失败，显示器可能自动熄屏"
else
  echo "[警告] 没有 xset 或 DISPLAY，跳过休眠抑制（不影响 Kiosk 启动）"
fi

BROWSER=""
for candidate in chromium-browser chromium; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    BROWSER="${candidate}"
    break
  fi
done
if [[ -z "${BROWSER}" ]]; then
  echo "[错误] 未找到 chromium-browser 或 chromium。" >&2
  echo "       安装：sudo apt-get install -y chromium-browser" >&2
  exit 1
fi

# No --no-sandbox (a normal user does not need it) and no --incognito.
exec "${BROWSER}" \
  --kiosk \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --no-first-run \
  "${URL}"
