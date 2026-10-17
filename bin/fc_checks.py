"""Read-only machine checks the setup steps table and doctor use. No network, no writes."""
import os, re
from pathlib import Path
import platform
import fc_core


def owned_links(checkout):
    """[(name, link, target)] for the three links compose owns: compose CLI link, compose skill link, bp link."""
    checkout, home = Path(checkout), Path.home()
    return [("compose CLI link", home / ".local/bin/compose", checkout / "bin/compose"),
            ("compose skill link", home / ".claude/skills/compose", checkout),
            ("bp link", home / ".local/bin/bp", checkout / "bp/bin/bp.mjs")]

def link_state(path):
    """("ok", target) when path resolves to something that exists, ("dangling", raw link text), or ("missing", None)."""
    path = Path(path)
    if path.exists():
        return ("ok", str(path.resolve()))
    if path.is_symlink():
        return ("dangling", os.readlink(path))
    return ("missing", None)

def local_bin_on_path():
    """True when ~/.local/bin is one of the PATH entries."""
    return str(Path.home() / ".local/bin") in os.environ.get("PATH", "").split(os.pathsep)

def gh_authed():
    """True when `gh auth status` exits 0; False when it does not or gh is absent."""
    try:
        return fc_core.sh(["gh", "auth", "status"], Path.home(), check=False).returncode == 0
    except FileNotFoundError:
        return False

def rerere_set():
    """True when `git config --global --get rerere.enabled` prints true."""
    try:
        return fc_core.sh(["git", "config", "--global", "--get", "rerere.enabled"], Path.home(), check=False).stdout.strip() == "true"
    except FileNotFoundError:
        return False

def jev_synced(checkout):
    """True when <checkout>/jev/.venv exists."""
    return (Path(checkout) / "jev/.venv").exists()

def chromium_installed():
    """True when the newest Playwright chromium-<n> has its Chrome for Testing binary (as bp/bin/bp.mjs:11-12 finds it)."""
    cache = Path.home() / "Library/Caches/ms-playwright"
    versions = sorted((d for d in os.listdir(cache) if re.fullmatch(r"chromium-\d+", d)), key=lambda d: -int(d[9:])) if cache.is_dir() else []
    if not versions:
        return False
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    return (cache / versions[0] / f"chrome-mac-{arch}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing").exists()
