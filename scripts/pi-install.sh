#!/usr/bin/env bash
# ===========================================================================
#  RIC Console installer for Raspberry Pi 4 (Buster / armv7l).
#
#  sudo bash ./scripts/pi-install.sh
#  sudo bash ./scripts/pi-install.sh --repair-buster-sources   # only if apt is dead
#
#  Prepares a private Python >= 3.10 (the system python3 is never touched),
#  installs backend/.venv, checks the DHJ-9 CP2102 and the USB camera
#  prerequisites, installs the systemd backend service plus the desktop kiosk
#  autostart entry, then health-checks the console.
#
#  Idempotent: a second run will not rebuild Python or wipe the database.
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

# APT failure classification lives in its own file so it can be unit-tested
# without touching a machine.
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/lib/apt-classify.sh"

# --- constants --------------------------------------------------------------
PYTHON_VERSION="3.11.9"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
PYTHON_PREFIX="/opt/ric-python311"
SERVICE_NAME="ric-console"
KIOSK_DESKTOP_ID="ric-console-kiosk"
ENV_FILE="/etc/ric-console/ric-console.env"
DHJ9_VID_PID="10c4:ea60"                 # Silicon Labs CP2102 in the DHJ-9
HEALTH_TIMEOUT_S=60
LEGACY_RASPBIAN_HOST="legacy.raspbian.org"
VENV_DIR="${REPO_DIR}/backend/.venv"
VENV_PY="${VENV_DIR}/bin/python"
WEB_DIR="${REPO_DIR}/deploy/pi/web"
RUN_GROUP=""
GROUP_CHANGED=0

# Disk guardrails. A source build of CPython needs the tarball, the extracted
# tree and the object files at the same time; on a 15 GB root partition with
# ~5.4 GB free that leaves room, but it must be checked before starting.
MIN_FREE_BASE_MB=1500        # apt packages + venv + pip wheels
MIN_FREE_PYTHON_BUILD_MB=3000  # CPython source build, checked again right before
# /tmp may be a tmpfs on some images; /var/tmp is disk-backed and never costs RAM.
PYTHON_BUILD_ROOT="${RIC_BUILD_TMP:-/var/tmp}"

# --- privileges -------------------------------------------------------------
RUN_USER="${SUDO_USER:-}"
if [[ -z "${RUN_USER}" || "${RUN_USER}" == "root" ]]; then
  echo "[错误] 请用 sudo 以普通用户身份运行：sudo bash ./scripts/pi-install.sh" >&2
  echo "       当前 SUDO_USER='${RUN_USER:-<空>}'；中控服务不能以 root 运行。" >&2
  exit 1
fi
RUN_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"
RUN_GROUP="$(id -gn "${RUN_USER}" 2>/dev/null || echo "${RUN_USER}")"

# --- output helpers ---------------------------------------------------------
if [[ -t 1 ]]; then
  C_I=$'\033[0;36m'; C_W=$'\033[0;33m'; C_E=$'\033[0;31m'; C_S=$'\033[0;32m'; C_0=$'\033[0m'
else
  C_I=''; C_W=''; C_E=''; C_S=''; C_0=''
fi
info() { printf '%s[信息]%s %s\n' "${C_I}" "${C_0}" "$*"; }
ok()   { printf '%s[成功]%s %s\n' "${C_S}" "${C_0}" "$*"; }
warn() { printf '%s[警告]%s %s\n' "${C_W}" "${C_0}" "$*" >&2; }
die()  { printf '%s[错误]%s %s\n' "${C_E}" "${C_0}" "$*" >&2; exit 1; }
step() { printf '\n%s=== %s ===%s\n' "${C_I}" "$*" "${C_0}"; }

# --- arguments --------------------------------------------------------------
REPAIR_SOURCES=0
SKIP_PYTHON_BUILD=0
for arg in "$@"; do
  case "${arg}" in
    --repair-buster-sources) REPAIR_SOURCES=1 ;;
    --skip-python-build)     SKIP_PYTHON_BUILD=1 ;;
    -h|--help)
      sed -n '2,16p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *) die "未知参数：${arg}（可用：--repair-buster-sources --skip-python-build --help）" ;;
  esac
done

# --- helpers ----------------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

# Health probes must not depend on curl being installed: the venv's Python is
# guaranteed to exist by the time we health-check, and urllib is stdlib.
# Otherwise a missing curl would be misreported as "the install failed".
http_ok() {
  local url="$1"
  if have curl; then
    curl -fsS --max-time "${HTTP_TIMEOUT_S:-3}" "${url}" >/dev/null 2>&1 && return 0
    return 1
  fi
  http_body "${url}" >/dev/null 2>&1
}

http_body() {
  local url="$1"
  if have curl; then
    curl -fsS --max-time "${HTTP_TIMEOUT_S:-3}" "${url}"
    return $?
  fi
  if [[ -x "${VENV_PY:-}" ]]; then
    "${VENV_PY}" -c 'import sys, urllib.request; sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=5).read().decode("utf-8", "replace"))' "${url}"
    return $?
  fi
  have wget || { echo "neither curl, wget nor the venv python is available" >&2; return 1; }
  wget -q -O - --timeout=5 "${url}"
}

# Fetch a file with whichever downloader this image actually has.
download() {
  local url="$1" dest="$2"
  if have curl; then
    curl -fsSL --retry 3 -o "${dest}" "${url}" && return 0
  fi
  if have wget; then
    wget -q -T 30 -O "${dest}" "${url}" && return 0
  fi
  die "系统里没有 curl 也没有 wget，无法下载：${url}"
}

free_mb() {
  local path="$1" value=""
  value="$(df -m --output=avail "${path}" 2>/dev/null | tail -1 | tr -d ' ' || true)"
  if [[ -z "${value}" ]]; then
    value="$(df -m "${path}" | awk 'NR==2 {print $4}')"
  fi
  printf '%s' "${value}"
}

require_free_mb() {
  # Reports and refuses; never deletes anything to make room.
  local need="$1" path="$2" why="$3" free
  free="$(free_mb "${path}")"
  if [[ ! "${free}" =~ ^[0-9]+$ ]]; then
    warn "无法读取 ${path} 的剩余空间，跳过该项检查（${why}）"
    return 0
  fi
  if ((free < need)); then
    printf '%s[错误]%s 磁盘空间不足：%s 当前可用 %s MB，%s 需要至少 %s MB\n' \
      "${C_E}" "${C_0}" "${path}" "${free}" "${why}" "${need}" >&2
    printf '     本脚本不会自动删除任何文件。可以自行确认后清理：\n' >&2
    printf '       sudo du -xh --max-depth=1 / | sort -h | tail -15\n' >&2
    printf '       sudo apt clean            # 只清 apt 下载缓存，通常能放出几百 MB\n' >&2
    printf '     清理后重新运行本脚本即可（安装是幂等的）。\n' >&2
    exit 1
  fi
  return 0
}

py_is_new_enough() {
  local candidate="$1"
  [[ -n "${candidate}" && -x "${candidate}" ]] || return 1
  "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

group_has_user() {
  local group="$1" user="$2"
  getent group "${group}" >/dev/null 2>&1 || return 1
  id -nG "${user}" 2>/dev/null | tr ' ' '\n' | grep -qx "${group}"
}

ensure_group() {
  local group="$1"
  if ! getent group "${group}" >/dev/null 2>&1; then
    warn "系统里没有 ${group} 组，跳过"
    return 0
  fi
  if group_has_user "${group}" "${RUN_USER}"; then
    ok "用户 ${RUN_USER} 已在 ${group} 组"
  else
    usermod -aG "${group}" "${RUN_USER}"
    ok "已将 ${RUN_USER} 加入 ${group} 组（需重新登录生效）"
    GROUP_CHANGED=1
  fi
}

ensure_module() {
  local module="$1"
  if lsmod 2>/dev/null | awk '{print $1}' | grep -qx "${module}"; then
    ok "内核模块 ${module} 已加载"
    return 0
  fi
  if modprobe "${module}" 2>/dev/null; then
    ok "已加载内核模块 ${module}"
  else
    warn "无法加载内核模块 ${module}（可能已内建，也可能不可用）"
  fi
}

# LC_ALL=C keeps apt's wording stable so the classifier matches on any locale.
# APT_LOG_MODE=append keeps the first failure visible when a retry follows.
apt_update() {
  local extra="${1:-}" mode="overwrite"
  [[ -n "${APT_LOG:-}" ]] || return 1
  if [[ "${APT_LOG_MODE:-overwrite}" == "append" ]]; then mode="append"; fi
  # shellcheck disable=SC2086
  LC_ALL=C apt-get update ${extra} -o Acquire::Retries=2 2>&1 | tee -"${mode}" "${APT_LOG}"
  return "${PIPESTATUS[0]}"
}

# Only rewrites Raspbian Buster lines that point at a recognised Raspbian
# mirror. Third-party repositories, signing keys and every other distribution
# are left untouched, and nothing disables signature verification.
repair_buster_sources() {
  local stamp targets=() f
  stamp="$(date +%Y%m%d-%H%M%S)"
  [[ -f /etc/apt/sources.list ]] && targets+=(/etc/apt/sources.list)
  if [[ -d /etc/apt/sources.list.d ]]; then
    while IFS= read -r -d '' f; do targets+=("${f}"); done < <(
      find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0
    )
  fi
  if ((${#targets[@]} == 0)); then
    warn "没有找到任何 apt 源文件，不做修改"
    return 1
  fi

  local backups=() changed=0
  for f in "${targets[@]}"; do
    local bak
    if [[ "${f}" == "/etc/apt/sources.list" ]]; then
      bak="/etc/apt/sources.list.ric-backup-${stamp}"
    else
      bak="${f}.ric-backup-${stamp}"
    fi
    cp -a "${f}" "${bak}"
    backups+=("${bak}")
    if grep -qiE '^[[:space:]]*(deb|deb-src)[[:space:]]+https?://[^[:space:]]*raspbian[^[:space:]]*[[:space:]]+buster' "${f}"; then
      sed -E -i "s#^([[:space:]]*(deb|deb-src)[[:space:]]+)https?://[^[:space:]]+([[:space:]]+buster)#\1http://${LEGACY_RASPBIAN_HOST}/raspbian\3#" "${f}"
      changed=1
    fi
  done

  warn "原软件源已备份到："
  printf '    %s\n' "${backups[@]}"
  if ((changed == 0)); then
    warn "文件里没有可识别的 Raspbian Buster 官方源条目，未做任何修改。"
    warn "请把 /tmp/ric-apt-update.log 交给人工排查，不要继续猜测改源。"
    return 1
  fi
  ok "已将失效的 Raspbian Buster 条目指向 ${LEGACY_RASPBIAN_HOST}"
  return 0
}

# Read-only survey of the graphics side. The backend does not need any of this,
# so nothing here is fatal and nothing here is changed - in particular this
# script never edits LightDM / raspi-config autologin settings.
report_desktop_readiness() {
  local default_target="" has_graphical=0 browser="" pkg_suggestion="?"

  if have systemctl; then
    default_target="$(systemctl get-default 2>/dev/null || true)"
    [[ -d /lib/systemd/system/graphical.target || -d /etc/systemd/system/graphical.target ]] && has_graphical=1
  fi

  if have chromium-browser; then browser="chromium-browser"
  elif have chromium; then browser="chromium"; fi

  printf '\n[图形桌面 / Kiosk 前提（只读检测）]\n'
  if [[ "${default_target}" == "graphical.target" && "${has_graphical}" -eq 1 ]]; then
    printf '  %-22s OK（默认启动目标 %s）\n' "Desktop environment:" "${default_target}"
  elif [[ "${has_graphical}" -eq 1 ]]; then
    printf '  %-22s WARN（存在 graphical.target，但默认目标是 %s）\n' "Desktop environment:" "${default_target:-未知}"
  else
    printf '  %-22s WARN（看起来是无桌面系统，Kiosk 无法显示）\n' "Desktop environment:"
  fi

  if [[ -n "${browser}" ]]; then
    printf '  %-22s OK（%s）\n' "Chromium:" "${browser}"
  else
    pkg_suggestion="$(apt-cache search --names-only '^(chromium|chromium-browser)$' 2>/dev/null | awk '{print $1}' | tr '\n' ' ' | sed 's/ *$//')"
    [[ -n "${pkg_suggestion}" ]] || pkg_suggestion="当前 apt 仓库里没有可用的 chromium 包"
    printf '  %-22s WARN\n' "Chromium:"
    printf '  %s\n' "RIC 后端已安装，但未找到 Chromium，无法自动显示本地中控。"
    printf '  本仓库 apt 源里可用的候选包：%s\n' "${pkg_suggestion}"
    printf '  确认后自行安装（本脚本不会替你装）：sudo apt-get install -y <上面的包名>\n'
  fi

  if have xset; then
    printf '  %-22s OK\n' "xset（熄屏抑制）:"
  else
    printf '  %-22s WARN（缺 x11-xserver-utils，Kiosk 仍会启动，只是可能自动熄屏）\n' "xset:"
  fi

  local autologin="not confirmed"
  if [[ -r /etc/lightdm/lightdm.conf ]]; then
    if grep -qE '^[[:space:]]*autologin-user=.+' /etc/lightdm/lightdm.conf 2>/dev/null; then
      autologin="detected（LightDM autologin-user=$(grep -oE '^[[:space:]]*autologin-user=.+' /etc/lightdm/lightdm.conf | head -1 | cut -d= -f2 | tr -d ' ')）"
    else
      autologin="not confirmed（lightdm.conf 里没有 autologin-user）"
    fi
  elif [[ -r /etc/lightdm/lightdm.conf.d ]] || have raspi-config; then
    autologin="not confirmed（未直接读取到 lightdm 配置；raspi-config 可查，本脚本不修改）"
  else
    autologin="not confirmed（没有 LightDM，桌面自启动方式需人工确认）"
  fi
  printf '  %-22s %s\n' "Desktop autologin:" "${autologin}"

  if [[ "${autologin}" != detected* ]]; then
    printf '\n  说明：后端服务由 systemd 开机自启，与桌面无关，可正常使用。\n'
    printf '        Chromium Kiosk 属于桌面会话自启动，需要有人登录图形桌面后才会打开。\n'
    printf '        需要全自动显示时，请自行用 raspi-config 或 LightDM 配置自动登录；\n'
    printf '        本脚本不会修改任何登录配置。\n'
  fi
  printf '  手动验证 Kiosk：%s/scripts/pi-kiosk.sh\n' "${REPO_DIR}"
}

# --- 1. system --------------------------------------------------------------
step "1/12 系统检测"
# Windows checkouts can lose the executable bit on shell scripts; make the
# helper scripts runnable before anything tries to exec them.
chmod +x scripts/*.sh 2>/dev/null || warn "无法 chmod scripts/*.sh，请手工确认执行权限"
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  info "发行版：${PRETTY_NAME:-unknown}"
fi
ARCH="$(uname -m)"
info "架构：${ARCH}"
case "${ARCH}" in
  armv7l | aarch64) : ;;
  *) warn "非 ARM 设备（${ARCH}）：本脚本是为 Raspberry Pi 写的，仍会继续" ;;
esac
if [[ -r /proc/device-tree/model ]]; then
  info "机型：$(tr -d '\0' < /proc/device-tree/model)"
fi
RAM_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
info "内存：${RAM_MB} MB"
((RAM_MB >= 900)) || warn "内存偏小，编译 Python 时请关闭其它程序"
ROOT_FREE_MB="$(free_mb /)"
info "根分区可用：${ROOT_FREE_MB} MB"
# Checked before apt, before the download and before the compile. The script
# never frees space itself - it only refuses and suggests.
require_free_mb "${MIN_FREE_BASE_MB}" / "apt 依赖 + venv + pip 缓存"

# --- 2. apt -----------------------------------------------------------------
step "2/12 apt 软件源"
have apt-get || die "找不到 apt-get：本脚本只支持 Debian / Raspbian"

APT_LOG="/tmp/ric-apt-update.log"
APT_WAS_BROKEN=0
APT_KIND="ok"
APT_RELEASEINFO_SEEN=0

if apt_update; then
  ok "apt 软件源可用"
  if [[ "${REPAIR_SOURCES}" -eq 1 ]]; then
    ok "apt 正常，无需修复软件源（未修改任何源文件）"
  fi
else
  APT_WAS_BROKEN=1
  APT_KIND="$(apt_classify "${APT_LOG}")"
  if [[ "${APT_KIND}" == "release-info" || "${APT_KIND}" == "both" ]]; then
    APT_RELEASEINFO_SEEN=1
  fi
  APT_ACTION="$(apt_plan_action "${APT_KIND}" "${REPAIR_SOURCES}")"
  info "apt-get update 失败：分类=${APT_KIND}，计划动作=${APT_ACTION}"

  case "${APT_ACTION}" in
    # Not a security decision: the archive is still signed, only its release
    # metadata moved. Confirm once; never write a permanent apt.conf.
    accept-releaseinfo)
      warn "Raspberry Pi repository release metadata changed."
      info "This is an APT release-info confirmation, not an unsigned repository."
      info "Accepting this one-time metadata change with:"
      info "       apt-get update --allow-releaseinfo-change"
      APT_LOG_MODE=append
      apt_update --allow-releaseinfo-change \
        || die "接受 release-info 变更后 apt update 仍失败，完整日志：${APT_LOG}"
      APT_LOG_MODE=overwrite
      ok "release-info 变更已一次性确认，apt 可用（未修改任何源文件）"
      ;;

    require-repair-flag)
      printf '\n'
      warn "检测到 Raspbian Buster 主源已失效（404 / 无 Release 文件）。本脚本不会擅自修改系统软件源。"
      printf '\n请重新执行：\n    sudo bash ./scripts/pi-install.sh --repair-buster-sources\n\n'
      printf '该选项只会把指向失效 Raspbian Buster 官方源的条目改写为 http://%s/raspbian，\n' "${LEGACY_RASPBIAN_HOST}"
      printf '并在修改前创建带时间戳的备份。\n'
      printf '完整日志已保留：%s\n' "${APT_LOG}"
      exit 1
      ;;

    repair-then-retry)
      warn "已确认失效软件源（分类 ${APT_KIND}），进入修复模式"
      repair_buster_sources || die "软件源修复未完成；备份文件位置见上方警告，请人工确认后再继续"
      APT_LOG_MODE=append
      if [[ "${APT_RELEASEINFO_SEEN}" -eq 1 ]]; then
        info "修复后重试，并一次性接受 release-info 变更"
        apt_update --allow-releaseinfo-change \
          || die "修复软件源后 apt update 仍失败，完整日志：${APT_LOG}"
      elif apt_update; then
        :
      else
        # The Suite change can only surface once the dead mirror is gone.
        APT_KIND="$(apt_classify "${APT_LOG}")"
        if [[ "${APT_KIND}" == "release-info" || "${APT_KIND}" == "both" ]]; then
          APT_RELEASEINFO_SEEN=1
          info "修复后检测到 release metadata 变更，一次性接受"
          apt_update --allow-releaseinfo-change \
            || die "修复软件源后 apt update 仍失败，完整日志：${APT_LOG}"
        else
          die "修复软件源后 apt update 仍失败，完整日志：${APT_LOG}"
        fi
      fi
      APT_LOG_MODE=overwrite
      ok "软件源修复后 apt update 成功"
      ;;

    *)
      # DNS, proxy, timeout, clock skew, unsigned repo, ... : classified unknown,
      # so nothing is changed and no special flag is used.
      die "apt-get update 失败（分类 ${APT_KIND}）。既不是 Raspbian 主源 404，也不是 release-info 变更：不修改任何源文件，也不使用 --allow-releaseinfo-change。完整日志：${APT_LOG}"
      ;;
  esac
fi

BUILD_PACKAGES=(
  ca-certificates curl wget gnupg
  build-essential
  libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev
  liblzma-dev xz-utils tk-dev libncurses5-dev libncursesw5-dev uuid-dev
  usbutils kmod
)
MISSING=()
for pkg in "${BUILD_PACKAGES[@]}"; do
  dpkg -s "${pkg}" >/dev/null 2>&1 || MISSING+=("${pkg}")
done
if ((${#MISSING[@]})); then
  info "安装编译依赖：${MISSING[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${MISSING[@]}" \
    || warn "部分依赖安装失败，Python 编译可能不完整"
else
  ok "编译依赖已齐"
fi

# --- 3. DHJ-9 serial --------------------------------------------------------
step "3/12 DHJ-9 串口链路"
ensure_module cp210x
if lsusb 2>/dev/null | grep -qi "${DHJ9_VID_PID}"; then
  ok "DHJ-9 detected（USB ${DHJ9_VID_PID} / CP2102）"
elif lsusb 2>/dev/null | grep -qiE 'silicon labs|cp210'; then
  ok "DHJ-9 detected（按厂商名匹配到 CP210x）"
else
  warn "DHJ-9 not detected：USB 总线上没有 ${DHJ9_VID_PID}。插好设备后重新运行本脚本即可。"
fi
if compgen -G '/dev/ttyUSB*' >/dev/null; then
  ok "串口设备：$(ls /dev/ttyUSB* | tr '\n' ' ')"
else
  info "当前没有 /dev/ttyUSB*（设备未插或未被识别），安装继续"
fi
ensure_group dialout

# --- 4. USB camera preflight ------------------------------------------------
step "4/12 USB 摄像头环境预检（本轮不含识别算法，也不安装 OpenCV）"
ensure_module uvcvideo
ensure_group video

USB_LINES=0
if have lsusb; then
  USB_LINES="$(lsusb 2>/dev/null | grep -vcE 'linux foundation|root hub|[[:space:]]hub[[:space:]]' || true)"
  info "lsusb 非 hub 设备条目：${USB_LINES}"
  lsusb 2>/dev/null | grep -viE 'linux foundation|root hub|[[:space:]]hub[[:space:]]' | sed 's/^/    /' || true
fi

HAVE_V4L=0
if compgen -G '/dev/video*' >/dev/null; then
  HAVE_V4L=1
  ok "检测到 V4L2 摄像头设备：$(ls /dev/video* | tr '\n' ' ')"
elif ((USB_LINES > 0)); then
  warn "检测到 USB 设备但未发现 V4L2 摄像头，需要进一步确认驱动"
else
  info "未检测到 USB 摄像头（未插入或未被识别）"
fi

if apt-cache show v4l-utils >/dev/null 2>&1; then
  if ! dpkg -s v4l-utils >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends v4l-utils \
      && ok "已安装 v4l-utils" || warn "v4l-utils 安装失败（不影响 DHJ-9 采集）"
  fi
  if have v4l2-ctl; then
    if ((HAVE_V4L)); then
      info "v4l2-ctl --list-devices："
      v4l2-ctl --list-devices 2>/dev/null | sed 's/^/    /' || true
    else
      info "v4l2-ctl 已就绪；插入摄像头后执行 v4l2-ctl --list-devices 复核"
    fi
  fi
else
  warn "软件源中没有 v4l-utils，跳过（不影响 DHJ-9 采集）"
fi

# --- 5. Python --------------------------------------------------------------
step "5/12 Python 运行环境（系统 python3 保持不变）"
info "系统 python3：$(/usr/bin/python3 --version 2>&1 || echo '未安装')  <- 不会被替换"

PYTHON_BIN=""
for candidate in "${PYTHON_PREFIX}/bin/python3.11" \
                 "$(have python3.12 && command -v python3.12 || true)" \
                 "$(have python3.11 && command -v python3.11 || true)" \
                 "$(have python3.10 && command -v python3.10 || true)"; do
  if py_is_new_enough "${candidate}"; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [[ -n "${PYTHON_BIN}" ]]; then
  ok "使用现成的 Python >= 3.10：${PYTHON_BIN}（$("${PYTHON_BIN}" --version 2>&1)）"
elif [[ "${SKIP_PYTHON_BUILD}" -eq 1 ]]; then
  die "没有 Python >= 3.10，且指定了 --skip-python-build"
else
  require_free_mb "${MIN_FREE_PYTHON_BUILD_MB}" "${PYTHON_BUILD_ROOT}" "编译 CPython ${PYTHON_VERSION}"
  info "将在 ${PYTHON_PREFIX} 下从官方源码编译 Python ${PYTHON_VERSION}（Pi 上约 20-60 分钟）"
  info "不加 --enable-optimizations / PGO，避免 ARMv7 上超慢编译"
  # Only this directory is ever removed, and only after a successful install.
  mkdir -p "${PYTHON_BUILD_ROOT}"
  BUILD_DIR="$(mktemp -d "${PYTHON_BUILD_ROOT}/ric-python-build.XXXXXX")"
  info "构建目录：${BUILD_DIR}（磁盘-backed，不用 /tmp 以免占用内存盘）"
  if ! (
    set -e
    cd "${BUILD_DIR}"
    download "${PYTHON_URL}" "Python-${PYTHON_VERSION}.tgz"
    # Integrity check against the checksum published next to the tarball:
    # detects corruption/truncation in transit, it is not a trust anchor.
    if download "${PYTHON_URL}.sha256" sum.sha256; then
      EXPECTED="$(awk '{print $1}' sum.sha256 | tr 'A-Z' 'a-z')"
      ACTUAL="$(sha256sum "Python-${PYTHON_VERSION}.tgz" | awk '{print $1}')"
      if [[ "${EXPECTED}" != "${ACTUAL}" ]]; then
        echo "sha256 校验不通过：${ACTUAL} != ${EXPECTED}" >&2
        exit 1
      fi
      echo "Python 源码包 sha256 校验通过"
    else
      echo "无法获取 .sha256，跳过完整性校验" >&2
    fi
    tar -xzf "Python-${PYTHON_VERSION}.tgz"
    cd "Python-${PYTHON_VERSION}"
    ./configure --prefix="${PYTHON_PREFIX}" >/dev/null
    make -j"$(nproc)" >/dev/null
    make install >/dev/null   # private prefix: /usr/bin/python3 is never touched
  ); then
    # Keep the tree: the only useful evidence is in there. Nothing else is
    # touched - not the repo, not data/, not the user's files.
    printf '%s[错误]%s Python 编译失败，构建目录已保留以便排查：%s
' "${C_E}" "${C_0}" "${BUILD_DIR}" >&2
    printf '     确认后可手工删除：rm -rf %s
' "${BUILD_DIR}" >&2
    exit 1
  fi
  rm -rf "${BUILD_DIR}"
  ok "已清理 Python 构建目录（只删本脚本自己创建的 ${BUILD_DIR}）"
  PYTHON_BIN="${PYTHON_PREFIX}/bin/python3.11"
  py_is_new_enough "${PYTHON_BIN}" || die "${PYTHON_BIN} 安装后仍不可用"
  ok "Python ${PYTHON_VERSION} 已装到 ${PYTHON_PREFIX}（系统 python3 未改动）"
fi

"${PYTHON_BIN}" -c 'import ctypes, sqlite3, ssl; print("  ssl:", ssl.OPENSSL_VERSION); print("  sqlite3:", sqlite3.sqlite_version)' \
  || die "私有 Python 缺少 ssl/sqlite3/ctypes，请安装对应 -dev 包后重跑本脚本"

# --- 6. backend venv --------------------------------------------------------
step "6/12 后端虚拟环境与依赖"
if [[ -x "${VENV_DIR}/bin/python" ]] && "${VENV_DIR}/bin/python" -c 'import fastapi' 2>/dev/null; then
  ok "backend/.venv 已存在且可用，刷新依赖"
else
  "${PYTHON_BIN}" -m venv "${VENV_DIR}" || die "创建 venv 失败：${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
"${VENV_DIR}/bin/python" -m pip install -r backend/requirements.txt || die "pip 安装后端依赖失败"
chown -R "${RUN_USER}:${RUN_GROUP}" "${VENV_DIR}" || warn "venv 属主修改失败，请手工 chown"
ok "后端依赖完成：$("${VENV_DIR}/bin/python" --version)"

# --- 7. web build -----------------------------------------------------------
step "7/12 生产前端产物"
[[ -f "${WEB_DIR}/index.html" ]] || die "缺少 ${WEB_DIR}/index.html：请在 Windows 开发机运行 scripts\\package-pi-web.bat，提交并推送后在 Pi 上 git pull"
ok "前端产物就绪：${WEB_DIR}（$(find "${WEB_DIR}" -type f | wc -l | tr -d ' ') 个文件）"

# --- 8. runtime config ------------------------------------------------------
step "8/12 运行配置（RIC_HOST / RIC_PORT）"
if [[ -f "${ENV_FILE}" ]]; then
  ok "保留已存在的 ${ENV_FILE}，不覆盖现场改过的配置"
else
  install -d -m 0755 "$(dirname "${ENV_FILE}")"
  printf '%s\n' \
    '# RIC Console 运行参数。默认只监听回环地址：页面就在 Pi 本机 HDMI 上显示。' \
    '# 改成 0.0.0.0 会把中控暴露到局域网（无鉴权），仅用于调试。见 README。' \
    'RIC_HOST=127.0.0.1' \
    'RIC_PORT=8000' \
    > "${ENV_FILE}"
  ok "已创建 ${ENV_FILE}"
fi
# shellcheck disable=SC1090
. "${ENV_FILE}"
RIC_HOST="${RIC_HOST:-127.0.0.1}"
RIC_PORT="${RIC_PORT:-8000}"
HEALTH_URL="http://${RIC_HOST}:${RIC_PORT}/api/health"
CONSOLE_URL="http://${RIC_HOST}:${RIC_PORT}"

# --- 9. database ------------------------------------------------------------
step "9/12 SQLite 初始化"
sudo -u "${RUN_USER}" env RIC_DATABASE_PATH="${REPO_DIR}/data/rail_inspection.db" \
  "${VENV_DIR}/bin/python" - <<'PY' || die "数据库初始化失败"
import sys
sys.path.insert(0, "backend")
from app.db.database import Database

db = Database("data/rail_inspection.db")
db.init_schema()
print("  schema:", db.scalar("select value from schema_meta where key='schema_version'"))
print("  sessions:", db.scalar("select count(*) from sessions"))
PY
ok "数据库就绪：${REPO_DIR}/data/rail_inspection.db（已有数据不会被覆盖）"

# --- 10. systemd ------------------------------------------------------------
step "10/12 systemd 后端服务"
UNIT_SRC="deploy/systemd/ric-console.service.in"
[[ -f "${UNIT_SRC}" ]] || die "缺少服务模板 ${UNIT_SRC}"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
sed -e "s|@RIC_USER@|${RUN_USER}|" -e "s|@RIC_DIR@|${REPO_DIR}|" -e "s|@RIC_PYTHON@|${VENV_DIR}/bin/python|" \
  "${UNIT_SRC}" >"${UNIT_DST}"
chmod 0644 "${UNIT_DST}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service" >/dev/null 2>&1 || true
systemctl restart "${SERVICE_NAME}.service"
ok "已安装并启动 ${SERVICE_NAME}.service（用户 ${RUN_USER}，非 root）"

# --- 11. kiosk autostart ----------------------------------------------------
step "11/12 HDMI 本机 Kiosk 自启动"
DESKTOP_SRC="deploy/desktop/ric-console-kiosk.desktop.in"
[[ -f "${DESKTOP_SRC}" ]] || die "缺少 ${DESKTOP_SRC}"
AUTOSTART_DIR="${RUN_HOME}/.config/autostart"
install -d -m 0755 "${AUTOSTART_DIR}"
sed -e "s|@RIC_DIR@|${REPO_DIR}|" "${DESKTOP_SRC}" >"${AUTOSTART_DIR}/${KIOSK_DESKTOP_ID}.desktop"
chmod 0644 "${AUTOSTART_DIR}/${KIOSK_DESKTOP_ID}.desktop"
chown "${RUN_USER}:${RUN_GROUP}" "${AUTOSTART_DIR}" "${AUTOSTART_DIR}/${KIOSK_DESKTOP_ID}.desktop" \
  || warn "自启动文件属主修改失败，请用 chown 手工确认"
ok "已写入用户级自启动：${AUTOSTART_DIR}/${KIOSK_DESKTOP_ID}.desktop"
info "未修改 /etc/xdg/lxsession/LXDE-pi/autostart，桌面其它自启动项保持原样"

report_desktop_readiness

# --- 12. health + summary ---------------------------------------------------
step "12/12 健康检查"
DEADLINE=$((SECONDS + HEALTH_TIMEOUT_S))
until http_ok "${HEALTH_URL}"; do
  if ((SECONDS > DEADLINE)); then
    printf '%s[错误]%s %s 在 %ds 内没有响应\n' "${C_E}" "${C_0}" "${HEALTH_URL}" "${HEALTH_TIMEOUT_S}" >&2
    printf '     查看日志：journalctl -u %s -n 80 --no-pager\n' "${SERVICE_NAME}" >&2
    exit 1
  fi
  sleep 2
done
ok "后端健康：$(http_body "${HEALTH_URL}" || true)"
if http_body "${CONSOLE_URL}/" | grep -qi '<div id="root"'; then
  ok "本机页面可访问：${CONSOLE_URL}"
else
  warn "根路径没有返回 React 页面，请检查 deploy/pi/web 是否完整"
fi

GROUP_NOTE=""
if ((GROUP_CHANGED)); then
  GROUP_NOTE="  0) 本次修改过用户组：请先注销并重新登录（或 sudo reboot）。\n"
fi

printf '%s\n' \
  "" \
  "=========================================" \
  " RIC Console 已部署到 Raspberry Pi" \
  "=========================================" \
  "  运行用户      : ${RUN_USER}（非 root）" \
  "  项目目录      : ${REPO_DIR}" \
  "  Python        : ${PYTHON_BIN}" \
  "  虚拟环境      : ${VENV_DIR}" \
  "  前端产物      : ${WEB_DIR}" \
  "  运行配置      : ${ENV_FILE}（RIC_HOST=${RIC_HOST} RIC_PORT=${RIC_PORT}）" \
  "  systemd 服务  : systemctl status ${SERVICE_NAME}" \
  "  中控地址      : ${CONSOLE_URL}" \
  "" \
  "下一步："
printf "${GROUP_NOTE}"
printf '  1) sudo reboot  ->  HDMI 显示器自动进入 RIC Console 全屏\n'
printf '  2) 想立刻看效果：%s/scripts/pi-kiosk.sh\n' "${REPO_DIR}"
printf '  3) 状态检查    ：%s/scripts/pi-status.sh\n' "${REPO_DIR}"
printf '  4) 实时日志    ：journalctl -u %s -f\n' "${SERVICE_NAME}"
printf '\n注意：默认只监听 127.0.0.1。改成 0.0.0.0 会暴露到局域网且没有鉴权。\n'
ok "安装完成"
