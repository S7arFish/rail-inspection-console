#!/usr/bin/env bash
# ===========================================================================
#  APT failure classifier, shared by scripts/pi-install.sh.
#
#  Why this is a separate file: the decision "should I touch a source file, or
#  should I accept a metadata change, or should I just stop" is the one place in
#  the installer that can damage a machine, so it is pure functions over a log
#  file and is unit-tested instead of being tested by breaking a Pi.
#
#  Two unrelated real-world failures are on Raspbian Buster today:
#    A. http://raspbian.raspberrypi.org/raspbian buster -> 404, no Release file
#       => the repository is gone; only an explicit --repair-buster-sources may
#          rewrite it.
#    B. http://archive.raspberrypi.org/debian buster    -> the Suite value
#       changed and APT refuses to accept it silently
#       => this is a metadata confirmation, NOT an unsigned/insecure repo. It is
#          cleared with a one-off `apt-get update --allow-releaseinfo-change`,
#          never with trusted=yes, --allow-unauthenticated,
#          --allow-insecure-repositories or a permanent apt.conf.
# ===========================================================================

# shellcheck disable=SC2034
RIC_APT_DEAD_RE='404 [Nn]ot [Ff]ound|does not have a Release file|no Release file in Release|仓库不再含有|没有 Release 文件|Release file .* is not available'

# shellcheck disable=SC2034
RIC_APT_REL_RE="changed its 'Suite' value|must be accepted explicitly|release information changed|changed its 'Codename' value|Suite 值发生变化|必须显式接受|已变更.*Suite"

# apt_log_dead_repo <logfile>  - true when a repository is genuinely gone.
apt_log_dead_repo() {
  [[ -r "${1}" ]] || return 1
  grep -qiE "${RIC_APT_DEAD_RE}" "${1}"
}

# apt_log_releaseinfo_change <logfile> - true on a release-metadata change only.
apt_log_releaseinfo_change() {
  [[ -r "${1}" ]] || return 1
  grep -qiE "${RIC_APT_REL_RE}" "${1}"
}

# apt_classify <logfile> -> dead-raspbian | release-info | both | unknown
#
# "unknown" deliberately covers DNS failures, timeouts, proxies and clock skew:
# none of them may cause a source rewrite or a release-info acceptance.
apt_classify() {
  local log="${1:-}" dead=0 rel=0
  if [[ ! -r "${log}" ]]; then
    echo unknown
    return 0
  fi
  if apt_log_dead_repo "${log}"; then dead=1; fi
  if apt_log_releaseinfo_change "${log}"; then rel=1; fi
  if ((dead && rel)); then
    echo both
  elif ((dead)); then
    echo dead-raspbian
  elif ((rel)); then
    echo release-info
  else
    echo unknown
  fi
  return 0
}

# apt_plan_action <classification> <repair_flag>
#   -> none | accept-releaseinfo | require-repair-flag | repair-then-retry | abort
apt_plan_action() {
  local kind="${1:-unknown}" flag="${2:-0}"
  case "${kind}/${flag}" in
    # A metadata change is not a source edit: it is accepted once, on its own.
    release-info/*)    echo accept-releaseinfo ;;
    # Gone repositories need the operator's explicit opt-in first.
    dead-raspbian/1)   echo repair-then-retry ;;
    both/1)            echo repair-then-retry ;;
    dead-raspbian/0)   echo require-repair-flag ;;
    both/0)            echo require-repair-flag ;;
    # Anything else: stop, change nothing.
    none/*)            echo none ;;
    *)                 echo abort ;;
  esac
  return 0
}
