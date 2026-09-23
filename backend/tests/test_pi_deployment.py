"""Static audit of the Raspberry Pi deployment assets.

These are the guards for mistakes that only show up on the Pi - a unit whose
`WorkingDirectory` no longer makes `app.main` importable, a Chromium flag that
silently needs root, an apt-source repair that fires when apt was fine, a build
directory cleanup that reached into the repo. The dev machine cannot run systemd
or LXDE, so the invariants are asserted against the files instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UNIT_TEMPLATE = REPO / "deploy" / "systemd" / "ric-console.service.in"
DESKTOP_TEMPLATE = REPO / "deploy" / "desktop" / "ric-console-kiosk.desktop.in"
INSTALL_SH = REPO / "scripts" / "pi-install.sh"
KIOSK_SH = REPO / "scripts" / "pi-kiosk.sh"
UPDATE_SH = REPO / "scripts" / "pi-update.sh"
STATUS_SH = REPO / "scripts" / "pi-status.sh"
WEB_INDEX = REPO / "deploy" / "pi" / "web" / "index.html"
ENV_PROD = REPO / "frontend" / ".env.production"

SAMPLE = {
    "@RIC_USER@": "pi",
    "@RIC_DIR@": "/home/pi/rail-inspection-console",
    "@RIC_PYTHON@": "/home/pi/rail-inspection-console/backend/.venv/bin/python",
}


def code(text: str) -> str:
    """Drop comment lines: a script may *document* a flag it refuses to use."""
    kept = [line for line in text.split(chr(10)) if not line.strip().startswith("#")]
    return chr(10).join(kept)



def render(text: str) -> str:
    """Mirror the installer's `sed` substitution."""
    for key, value in SAMPLE.items():
        text = text.replace(key, value)
    return text


def sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            out.setdefault(current, [])
        elif current:
            out[current].append(stripped)
    return out


def setting(lines: list[str], key: str) -> str | None:
    for line in lines:
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


@pytest.fixture(scope="module")
def unit() -> str:
    return render(UNIT_TEMPLATE.read_text(encoding="utf-8"))


# ------------------------------------------------------- import path (item 1)
def test_working_directory_makes_app_importable(unit):
    """Either WorkingDirectory=<repo>/backend, or an explicit --app-dir."""
    service = sections(unit)["Service"]
    working_dir = setting(service, "WorkingDirectory")
    exec_start = setting(service, "ExecStart") or ""

    assert working_dir, "the unit must pin its working directory"
    assert working_dir.startswith("/"), "WorkingDirectory must be absolute"
    assert working_dir == f"{SAMPLE['@RIC_DIR@']}/backend"

    # The requirement's option A, plus option B as belt and braces: a later edit
    # to WorkingDirectory must not be able to break `import app.main`.
    assert "app.main:app" in exec_start
    assert f"--app-dir {SAMPLE['@RIC_DIR@']}/backend" in exec_start


def test_no_placeholder_survives_rendering(unit):
    assert "@RIC_" not in unit, "a template placeholder was not substituted"


def test_exec_start_uses_the_venv_interpreter(unit):
    service = sections(unit)["Service"]
    exec_start = setting(service, "ExecStart") or ""
    assert exec_start.startswith(SAMPLE["@RIC_PYTHON@"])
    assert "-m uvicorn" in exec_start


def test_unit_never_runs_as_root(unit):
    service = sections(unit)["Service"]
    assert setting(service, "User") == "pi"
    assert setting(service, "Group") is None, "let the user's primary group apply"
    assert "User=root" not in unit


def test_environment_defaults_precede_the_override_file(unit):
    """systemd applies these in order; the file must be able to win."""
    service = sections(unit)["Service"]
    joined = "\n".join(service)
    host_at = joined.index("Environment=RIC_HOST=127.0.0.1")
    port_at = joined.index("Environment=RIC_PORT=8000")
    file_at = joined.index("EnvironmentFile=-/etc/ric-console/ric-console.env")
    assert host_at < file_at and port_at < file_at


def test_env_file_is_optional_so_the_service_still_starts(unit):
    service = sections(unit)["Service"]
    value = setting(service, "EnvironmentFile")
    assert value and value.startswith("-"), "a missing env file must not fail the unit"


def test_exec_start_has_no_shell_only_syntax(unit):
    """systemd expands ${VAR} itself; anything needing bash must not appear."""
    service = sections(unit)["Service"]
    exec_start = setting(service, "ExecStart") or ""
    for forbidden in ("&&", "||", ";", "|", "`", "$(", ">", "<"):
        assert forbidden not in exec_start, f"ExecStart uses shell syntax: {forbidden}"
    assert re.search(r"--host \$\{RIC_HOST\}", exec_start)
    assert re.search(r"--port \$\{RIC_PORT\}", exec_start)


def test_service_restarts_and_is_single_worker(unit):
    service = sections(unit)["Service"]
    assert setting(service, "Restart") == "on-failure"
    assert setting(service, "RestartSec") == "3"
    assert setting(service, "TimeoutStopSec") == "20"
    assert "--workers" not in "\n".join(service), "multiple workers fight over the port"


def test_install_wants_multi_user_target(unit):
    assert setting(sections(unit)["Install"], "WantedBy") == "multi-user.target"


# ------------------------------------------------------------- kiosk (3, 4)
def test_kiosk_flags_are_the_agreed_set():
    text = code(KIOSK_SH.read_text(encoding="utf-8"))
    for flag in ("--kiosk", "--noerrdialogs", "--disable-session-crashed-bubble", "--no-first-run"):
        assert flag in text, flag
    # explicitly forbidden: they either need root, weaken the sandbox, or hide state
    for forbidden in ("--no-sandbox", "--incognito", "--disable-gpu"):
        assert forbidden not in text, forbidden


def test_kiosk_refuses_to_run_as_root():
    text = code(KIOSK_SH.read_text(encoding="utf-8"))
    assert re.search(r'\$\(id -u\)"? +(-eq) +0', text)
    assert "exit 1" in text


def test_kiosk_waits_for_health_before_opening_the_browser():
    text = KIOSK_SH.read_text(encoding="utf-8")
    assert "/api/health" in text
    assert text.index("/api/health") < text.index("--kiosk")


def test_kiosk_treats_xset_as_optional():
    text = KIOSK_SH.read_text(encoding="utf-8")
    assert "xset s off" in text and "xset -dpms" in text
    # every xset call is guarded, so a missing tool cannot abort the kiosk
    assert len(re.findall(r"xset [^|]*\|\|", text)) >= 3


def test_desktop_entry_runs_as_user_with_absolute_exec():
    rendered = render(DESKTOP_TEMPLATE.read_text(encoding="utf-8"))
    entries = [line for line in rendered.splitlines() if "=" in line and not line.startswith("#")]
    values = dict(line.split("=", 1) for line in entries)
    assert values["Type"] == "Application"
    assert values["Exec"] == f"{SAMPLE['@RIC_DIR@']}/scripts/pi-kiosk.sh"
    assert values["Exec"].startswith("/")
    assert values["Terminal"] == "false"
    assert "sudo" not in rendered


def test_installer_does_not_touch_login_configuration():
    """Reading LightDM to report autologin status is fine; writing is not."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    for forbidden in (
        "> /etc/lightdm", ">>/etc/lightdm", "tee /etc/lightdm",
        "sed -i /etc/lightdm", "raspi-config --", "systemctl set-default",
    ):
        assert forbidden not in text, f"the installer must not change login settings: {forbidden}"


def test_installer_reports_desktop_prerequisites_read_only():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "report_desktop_readiness" in text
    for label in ("Desktop environment:", "Chromium:", "Desktop autologin:"):
        assert label in text, label
    assert "systemctl get-default" in text
    assert "graphical.target" in text
    assert "detected" in text and "not confirmed" in text


def test_missing_chromium_is_a_warning_not_a_failed_install():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "RIC 后端已安装，但未找到 Chromium" in text
    # the package name is discovered from the live apt index, not hard-coded
    assert "apt-cache search --names-only" in text
    block = text[text.index("report_desktop_readiness()"):text.index("# --- 1. system")]
    assert "die" not in block, "the desktop survey must never abort the install"


# ------------------------------------------------------------- disk (5, 6)
def test_disk_is_checked_before_apt_and_before_the_python_build():
    text = INSTALL_SH.read_text(encoding="utf-8")
    first_check = text.index("require_free_mb \"${MIN_FREE_BASE_MB}\"")
    apt_install = text.index("apt-get install -y --no-install-recommends")
    build_check = text.index("require_free_mb \"${MIN_FREE_PYTHON_BUILD_MB}\"")
    configure = text.index("./configure --prefix=")
    assert first_check < apt_install
    assert build_check < configure
    assert "MIN_FREE_PYTHON_BUILD_MB=3000" in text


def test_disk_shortage_only_suggests_cleanup():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "sudo apt clean" in text
    assert re.search(r'exit 1\n  fi\n  return 0', text) or "exit 1" in text
    for destructive in ("apt-get autoremove -y", "rm -rf /var", "journalctl --vacuum"):
        assert destructive not in text


def test_python_build_dir_is_explicit_and_only_it_is_cleaned():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'mktemp -d "${PYTHON_BUILD_ROOT}/ric-python-build.XXXXXX"' in text
    assert 'PYTHON_BUILD_ROOT="${RIC_BUILD_TMP:-/var/tmp}"' in text
    removals = re.findall(r'rm -rf "([^"]+)"', text)
    assert removals and all(entry == "${BUILD_DIR}" for entry in removals), removals
    # on failure the tree is kept for diagnosis instead of being destroyed
    assert "构建目录已保留以便排查" in text


def test_installer_never_deletes_project_or_data():
    text = INSTALL_SH.read_text(encoding="utf-8")
    for forbidden in ("rm -rf \"${REPO_DIR}", "rm -rf data", "rm -f data/", "git clean", "git reset --hard"):
        assert forbidden not in text, forbidden


# ----------------------------------------------------------------- apt (7)
def test_source_repair_requires_both_the_flag_and_a_real_failure():
    """Sources are only touched via the repair-then-retry branch."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'apt_plan_action "${APT_KIND}" "${REPAIR_SOURCES}"' in text
    # the classifier is consulted in the failure branch, never on success
    assert text.index("if apt_update; then") < text.index('APT_KIND="$(apt_classify')
    # exactly one call site for the repair, inside its own case branch
    assert text.count("repair_buster_sources || die") == 1
    branch = text[text.index("repair-then-retry)"):text.index("    *)" + chr(10))]
    assert "repair_buster_sources" in branch
    head = text[text.index("if apt_update; then"):text.index("  APT_WAS_BROKEN=1")]
    assert "repair_buster_sources" not in head


def test_sources_are_backed_up_before_any_write():
    text = INSTALL_SH.read_text(encoding="utf-8")
    block = text[text.index("repair_buster_sources() {"):text.index("report_desktop_readiness()")]
    assert block.index("cp -a") < block.index("sed -E -i")
    assert "ric-backup-" in block
    assert "printf '    %s\\n' \"${backups[@]}\"" in block


def test_source_repair_stays_narrow():
    text = INSTALL_SH.read_text(encoding="utf-8")
    block = text[text.index("repair_buster_sources() {"):text.index("report_desktop_readiness()")]
    assert "legacy.raspbian.org" in text
    assert "buster" in block
    assert "raspbian" in block
    for forbidden in ("trusted=yes", "allow-insecure", "Acquire::AllowInsecure", "rm -f /etc/apt", "del "):
        assert forbidden not in block, forbidden


def test_without_the_flag_a_dead_repo_stops_before_touching_anything():
    """A dead repo without --repair-buster-sources must stop, not edit."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    branch = text[text.index("require-repair-flag)"):text.index("repair-then-retry)")]
    assert "exit 1" in branch
    assert "--repair-buster-sources" in branch
    assert "repair_buster_sources" not in branch, "the no-flag path must not edit sources"
    assert "完整日志" in branch, "the operator is told where the log is kept"# ------------------------------------------------------------ curl (9), web (10)
def test_health_check_does_not_depend_on_curl_alone():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "until http_ok" in text
    assert "http_body" in text
    # the python fallback uses only the stdlib
    assert "urllib.request" in text
    assert "until curl" not in text


def test_downloads_work_with_curl_or_wget():
    text = INSTALL_SH.read_text(encoding="utf-8")
    body = text[text.index("download() {"):text.index("free_mb() {")]
    assert "curl" in body and "wget" in body
    assert 'download "${PYTHON_URL}"' in text


def test_install_refuses_without_the_web_bundle():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert re.search(r'\[\[ -f "\$\{WEB_DIR\}/index\.html" \]\] \|\| die', text)


def test_web_bundle_is_present_in_the_repository():
    """The Pi does not build the frontend; the artefact has to be committed."""
    assert WEB_INDEX.is_file(), "run scripts\\package-pi-web.bat and commit deploy/pi/web"
    assert '<div id="root">' in WEB_INDEX.read_text(encoding="utf-8")


def test_production_build_disables_mock_at_build_time():
    """VITE_* is baked in at build time; the Pi must not try to change it."""
    assert ENV_PROD.is_file()
    assert "VITE_USE_MOCK=false" in ENV_PROD.read_text(encoding="utf-8")
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "VITE_USE_MOCK" not in text, "the installer must not touch build-time env"


def test_pi_runtime_needs_no_node():
    for script in (INSTALL_SH, KIOSK_SH, UPDATE_SH, STATUS_SH):
        text = script.read_text(encoding="utf-8")
        assert not re.search(r'(?<!\w)(npm|npx)\s', text), f"{script.name} calls npm"


# --------------------------------------------------------------- updates (8)
def test_update_script_is_conservative():
    text = code(UPDATE_SH.read_text(encoding="utf-8"))
    assert "--ff-only" in text
    assert "git status --porcelain" in text
    for forbidden in ("git reset --hard", "git clean", "rm -rf", "--force"):
        assert forbidden not in text, forbidden
    assert "data/rail_inspection.db" in text  # only ever mentioned as untouched
