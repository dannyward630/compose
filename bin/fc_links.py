"""Make or repoint the links compose owns; never touch a real file, never write a shell rc file."""
import os
from pathlib import Path
import fc_checks


def ensure_link(link, target):
    """(state, line): state is linked, repointed, ok, or refused (a real file or directory is there)."""
    raise NotImplementedError("not implemented: task 013")

def relink_owned(checkout):
    """ensure_link for each fc_checks.owned_links(checkout); one line per link naming it and its state."""
    raise NotImplementedError("not implemented: task 013")

def path_line():
    """The PATH line for the shell profile when ~/.local/bin is not on PATH, else None."""
    raise NotImplementedError("not implemented: task 013")
