"""Make or repoint the links compose owns; never touch a real file, never write a shell rc file."""
import os
from pathlib import Path
import fc_checks
import fc_harness


def ensure_link(link, target):
    """(state, line): state is linked, repointed, ok, or refused (a real file or directory is there)."""
    link, target = Path(link), Path(target)
    if link.is_symlink():
        if os.readlink(link) == str(target):
            return "ok", f"ok {link} -> {target}"
        was = os.readlink(link)
        link.unlink()
        link.symlink_to(target)
        return "repointed", f"repointed {link} -> {target} (was {was})"
    if link.exists():
        kind = "directory" if link.is_dir() else "file"
        return "refused", f"refused {link}: a real {kind} is there, not touching it"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return "linked", f"linked {link} -> {target}"

def write_commands(key, checkout):
    """Write each missing or stale command copy (fc_checks.command_copies) with its source's bytes, making its folder; a
    symlink or directory in a copy's place is refused untouched. One line per copy: wrote, ok, or refused."""
    lines = []
    for copy, source in fc_checks.command_copies(key, checkout):
        if copy.is_symlink() or copy.is_dir():
            lines.append(f"refused {copy}: a real {'symlink' if copy.is_symlink() else 'directory'} is there, not touching it")
        elif copy.is_file() and copy.read_bytes() == source.read_bytes():
            lines.append(f"ok {copy}")
        else:
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(source.read_bytes())
            lines.append(f"wrote {copy}")
    return lines

def write_hooks(key, checkout):
    raise NotImplementedError

def trust_hooks(key, checkout):
    raise NotImplementedError

def relink_owned(checkout):
    """ensure_link for each fc_checks.owned_links(checkout), then the command copies of each installed harness row; one line
    per link naming it and its state, then one <name> commands line per copy."""
    lines = []
    for name, link, target in fc_checks.owned_links(checkout):
        lines.append(f"{name}: {ensure_link(link, target)[1]}")
    for key in fc_harness.installed():
        for line in write_commands(key, checkout):
            lines.append(f"{fc_harness.HARNESSES[key]['name']} commands: {line}")
    return lines

def path_line():
    """The PATH line for the shell profile when ~/.local/bin is not on PATH, else None."""
    local = str(Path.home() / ".local" / "bin")
    if any(os.path.expanduser(p) == local for p in os.environ.get("PATH", "").split(os.pathsep)):
        return None
    return 'export PATH="$HOME/.local/bin:$PATH"'
