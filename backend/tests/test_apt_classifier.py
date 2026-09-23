"""Functional tests for the APT failure classifier.

These actually run `scripts/lib/apt-classify.sh` under bash against synthetic
apt logs, including the two real messages seen on the competition Pi, because
the decision it makes - rewrite a source file, accept a metadata change, or stop
- is the one thing in the installer that can damage a machine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib" / "apt-classify.sh"

BASH = shutil.which("bash") or shutil.which("sh")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash to exercise the classifier")

# ---------------------------------------------------------------- log bodies
HEALTHY = """
Get:1 http://raspbian.raspberrypi.org/raspbian buster InRelease [15.0 kB]
Get:2 http://archive.raspberrypi.org/debian buster InRelease [32.6 kB]
Fetched 47.6 kB in 2s (21.6 kB/s)
Reading package lists...
"""

# Problem A on the real Pi: the Raspbian mirror is gone.
DEAD_RASPBIAN = """
Err:1 http://raspbian.raspberrypi.org/raspbian buster Release
  404 Not Found [IP: 93.93.128.192 80]
Reading package lists...
E: The repository 'http://raspbian.raspberrypi.org/raspbian buster Release' does not have a Release file.
N: Updating from such a repository can't be done securely, and is therefore disabled by default.
"""

DEAD_RASPBIAN_ZH = """
Err:1 http://raspbian.raspberrypi.org/raspbian buster Release
  404 Not Found
E: 仓库不再含有 Release 文件
"""

# Problem B on the real Pi: signed archive, but the Suite value moved.
RELEASEINFO_CHANGE = """
Get:4 http://archive.raspberrypi.org/debian buster InRelease [32.6 kB]
W: http://archive.raspberrypi.org/debian/dists/buster/InRelease: Key is stored in legacy trusted.gpg keyring
N: Updating from such a repository can't be done securely.
E: The repository 'http://archive.raspberrypi.org/debian buster InRelease' has changed its 'Suite' value from 'buster' to 'oldstable'
N: This must be accepted explicitly before the update for this repository can be updated.
N: See apt-secure(8) manpage for repository creation and user configuration details.
"""

BOTH = DEAD_RASPBIAN + RELEASEINFO_CHANGE

# Everything that must NOT trigger a repair or an acceptance.
NETWORK = """
Err:1 http://raspbian.raspberrypi.org/raspbian buster InRelease
  Could not resolve 'raspbian.raspberrypi.org'
Reading package lists...
W: Failed to fetch http://raspbian.raspberrypi.org/raspbian/dists/buster/InRelease  Could not resolve 'raspbian.raspberrypi.org'
E: Some index files failed to download. They have been ignored, or old ones used instead.
"""

DNS_AND_PROXY = """
Err:1 http://mirror.local/raspbian buster InRelease
  Connection timed out after 30002 milliseconds
E: Failed to fetch http://mirror.local/raspbian/dists/buster/InRelease  Unable to connect to mirror.local:80
"""

UNSIGNED = """
W: GPG error: http://third-party.example/debian buster InRelease: The following signatures couldn't be verified because the public key is not available: NO_PUBKEY 0123456789ABCDEF
E: The repository 'http://third-party.example/debian buster InRelease' is not signed.
"""


def classify(tmp_path: Path, body: str) -> str:
    """Run the real classifier from scripts/lib over a synthetic apt log."""
    import subprocess

    log = tmp_path / "apt.log"
    log.write_text(body, encoding="utf-8")
    out = subprocess.run(  # noqa: S603
        [BASH, "-c", '. "$1"; shift; apt_classify "$1"', "probe", str(Path(LIB).as_posix()), str(log)],
        capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (DEAD_RASPBIAN, "dead-raspbian"),
        (DEAD_RASPBIAN_ZH, "dead-raspbian"),
        (RELEASEINFO_CHANGE, "release-info"),
        (BOTH, "both"),
        (NETWORK, "unknown"),
        (DNS_AND_PROXY, "unknown"),
        (UNSIGNED, "unknown"),
        (HEALTHY, "unknown"),
    ],
)
def test_classification(tmp_path, body, expected):
    assert classify(tmp_path, body) == expected


@pytest.mark.parametrize(
    ("kind", "flag", "action"),
    [
        # Case 4: metadata change alone is accepted once, with or without the flag
        ("release-info", "0", "accept-releaseinfo"),
        ("release-info", "1", "accept-releaseinfo"),
        # Case 2: a dead mirror without the flag stops and asks
        ("dead-raspbian", "0", "require-repair-flag"),
        ("both", "0", "require-repair-flag"),
        # Cases 3 and 5: with the flag, repair first
        ("dead-raspbian", "1", "repair-then-retry"),
        ("both", "1", "repair-then-retry"),
        # Case 6: anything else changes nothing
        ("unknown", "0", "abort"),
        ("unknown", "1", "abort"),
    ],
)
def test_planned_action(kind, flag, action):
    import subprocess

    out = subprocess.run(  # noqa: S603
        [BASH, "-c", f'. "{Path(LIB).as_posix()}"; apt_plan_action {kind} {flag}'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == action


def test_a_healthy_update_is_not_reclassified():
    """The installer must only classify when apt actually returned non-zero."""
    text = (REPO / "scripts" / "pi-install.sh").read_text(encoding="utf-8")
    gate = text[text.index("if apt_update; then"):text.index("BUILD_PACKAGES=(")]
    then_branch = gate[: gate.index("else")]
    assert "apt_classify" not in then_branch
    assert "repair_buster_sources" not in then_branch
    assert "--allow-releaseinfo-change" not in then_branch


def test_releaseinfo_path_never_touches_sources():
    text = (REPO / "scripts" / "pi-install.sh").read_text(encoding="utf-8")
    branch = text[text.index("accept-releaseinfo)"):text.index("require-repair-flag)")]
    assert "repair_buster_sources" not in branch
    assert "--allow-releaseinfo-change" in branch
    assert "Raspberry Pi repository release metadata changed." in branch
    assert "not an unsigned repository" in branch


def test_classifier_is_sourced_by_the_installer():
    text = (REPO / "scripts" / "pi-install.sh").read_text(encoding="utf-8")
    assert 'lib/apt-classify.sh' in text
    assert text.index("lib/apt-classify.sh") < text.index("apt_classify ")


def test_no_permanent_apt_configuration_is_written():
    """One-off acceptance only: no apt.conf, no global Allow* settings."""
    def strip_comments(text: str) -> str:
        # A script may *document* the option it refuses to use.
        nl = chr(10)
        return nl.join(
            line for line in text.split(nl) if not line.strip().startswith("#")
        )

    text = strip_comments((REPO / "scripts" / "pi-install.sh").read_text(encoding="utf-8"))
    lib = strip_comments(LIB.read_text(encoding="utf-8"))
    for blob in (text, lib):
        for forbidden in (
            "Acquire::AllowReleaseInfoChange",
            "etc/apt/apt.conf.d",
            "trusted=yes",
            "--allow-unauthenticated",
            "--allow-insecure-repositories",
            "Acquire::AllowInsecureRepositories",
        ):
            assert forbidden not in blob, forbidden
