#!/usr/bin/env bash
# ===========================================================================
#  Update RIC Console on the Raspberry Pi from the git remote.
#
#  Safe by construction:
#    * refuses to run with a dirty working tree (nothing gets overwritten)
#    * git pull --ff-only only - no merge commits, no history rewriting
#    * never runs `git reset --hard`, `git clean`, or deletes data/
#    * the SQLite file is never touched; schema creation is additive (IF NOT
#      EXISTS) so existing batches survive an update
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="ric-console"
VENV_PY="${REPO_DIR}/backend/.venv/bin/python"
ENV_FILE="/etc/ric-console/ric-console.env"

cd "${REPO_DIR}"

info() { printf '[信息] %s\n' "$*"; }
ok()   { printf '[成功] %s\n' "$*"; }
die()  { printf '[错误] %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }
have git || die "没有 git，无法更新"
[[ -d .git ]] || die "${REPO_DIR} 不是 git 工作副本"

# --- 1. refuse a dirty tree --------------------------------------------------
DIRTY="$(git status --porcelain=v1 --untracked-files=no)"
if [[ -n "${DIRTY}" ]]; then
  printf '[错误] 工作区有未提交改动，更新已中止（不会覆盖现场修改）：\n' >&2
  printf '%s\n' "${DIRTY}" | sed 's/^/    /' >&2
  printf '     请先 commit 或 stash，再重新运行本脚本。\n' >&2
  exit 1
fi
ok "工作区干净"

BEFORE="$(git rev-parse HEAD)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
info "当前分支 ${BRANCH}，提交 ${BEFORE:0:8}"

# --- 2. fast-forward only ----------------------------------------------------
git fetch --prune origin || die "git fetch 失败（网络或凭证问题）"
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
if [[ -z "${UPSTREAM}" ]]; then
  die "分支 ${BRANCH} 没有上游分支，无法安全更新"
fi
git pull --ff-only || die "git pull --ff-only 失败：本地与远端已分叉，请人工处理（本脚本不会强制覆盖）"
AFTER="$(git rev-parse HEAD)"

if [[ "${BEFORE}" == "${AFTER}" ]]; then
  ok "已经是最新代码（${AFTER:0:8}），无需重启服务"
  exit 0
fi
ok "已更新 ${BEFORE:0:8} -> ${AFTER:0:8}"

# --- 3. backend dependencies -------------------------------------------------
[[ -x "${VENV_PY}" ]] || die "缺少 ${VENV_PY}，请先运行 sudo bash ./scripts/pi-install.sh"
if git diff --name-only "${BEFORE}" "${AFTER}" -- backend/requirements.txt | grep -q requirements.txt; then
  info "requirements.txt 有变化，更新依赖"
  "${VENV_PY}" -m pip install -r backend/requirements.txt || die "pip 安装依赖失败"
else
  ok "依赖清单未变化，跳过 pip install"
fi

# --- 4. web bundle -----------------------------------------------------------
[[ -f deploy/pi/web/index.html ]] || die "deploy/pi/web/index.html 不存在：请在 Windows 开发机运行 scripts\\package-pi-web.bat 后提交推送"
ok "前端产物存在"

# --- 5. restart + health -----------------------------------------------------
if [[ "$(id -u)" -eq 0 ]]; then RUN_AS=root; else RUN_AS="$(id -un)"; fi
RESTART() {
  if [[ "${RUN_AS}" == "root" ]]; then systemctl "$@"
  elif have sudo; then sudo systemctl "$@"
  else die "需要 root 或 sudo 来重启服务"; fi
}

info "重启 ${SERVICE_NAME}"
RESTART restart "${SERVICE_NAME}.service"

RIC_HOST="127.0.0.1"
RIC_PORT="8000"
if [[ -r "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
fi
URL="http://${RIC_HOST}:${RIC_PORT}/api/health"
DEADLINE=$((SECONDS + 40))
until curl -fsS --max-time 3 "${URL}" >/dev/null 2>&1; do
  if ((SECONDS > DEADLINE)); then
    printf '[错误] 更新后健康检查失败，代码已更新但服务未就绪。\n' >&2
    printf '     日志：journalctl -u %s -n 80 --no-pager\n' "${SERVICE_NAME}" >&2
    printf '     回退：git checkout %s && sudo systemctl restart %s\n' "${BEFORE:0:8}" "${SERVICE_NAME}" >&2
    exit 1
  fi
  sleep 2
done
ok "更新完成，服务健康：$(curl -fsS --max-time 3 "${URL}")"
echo "     数据库未被改动：${REPO_DIR}/data/rail_inspection.db"
