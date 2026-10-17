"""Read-only machine checks the setup steps table and doctor use. No network, no writes."""
import os, shutil
from pathlib import Path
import fc_core


def owned_links(checkout):
    """[(name, link, target)] for the three links compose owns: compose CLI link, compose skill link, bp link."""
    raise NotImplementedError("not implemented: task 006")

def link_state(path):
    """("ok", target) when path resolves to something that exists, ("dangling", raw link text), or ("missing", None)."""
    raise NotImplementedError("not implemented: task 006")

def local_bin_on_path():
    """True when ~/.local/bin is one of the PATH entries."""
    raise NotImplementedError("not implemented: task 006")

def gh_authed():
    """True when `gh auth status` exits 0; False when it does not or gh is absent."""
    raise NotImplementedError("not implemented: task 006")

def rerere_set():
    """True when `git config --global --get rerere.enabled` prints true."""
    raise NotImplementedError("not implemented: task 006")

def jev_synced(checkout):
    """True when <checkout>/jev/.venv exists."""
    raise NotImplementedError("not implemented: task 006")

def chromium_installed():
    """True when the newest Playwright chromium-<n> has its Chrome for Testing binary (as bp/bin/bp.mjs:11-12 finds it)."""
    raise NotImplementedError("not implemented: task 006")
