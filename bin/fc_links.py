"""Make or repoint the links compose owns; never touch a real file, never write a shell rc file."""
import json
import os
from pathlib import Path
import fc_checks
import fc_core
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
    """Write compose's hook groups (fc_harness.hook_groups) into the row's hooks file, merged into what is there, never replaced:
    a missing file is written as {"hooks": {<event>: [groups]}}; per event a wanted group matches the first existing group with the
    same matcher (both absent counts as the same) whose first handler's command ends in /bin/compose" <sub> for the same sub, so the
    two PreToolUse guard groups are told apart by matcher, is replaced in place when it differs and kept when equal, and a wanted
    group with no match is appended after the event's other groups, so groups that are not compose's keep their content and index.
    Other events and keys are kept. Written with fc_core.atomic_write, indent=2, only when the content changed; returns the written
    paths, [] when nothing changed. A file that is not valid JSON exits naming it, and nothing is written."""
    want = fc_harness.hook_groups(key, checkout)
    if not want:
        return []
    path = fc_harness.home_dir(key) / fc_harness.HARNESSES[key]["hooks_file"]
    if path.exists():
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}: {e}")
    else:
        doc = {}
    hooks = doc.setdefault("hooks", {})
    changed = False
    for ev, groups in want.items():
        existing = list(hooks.get(ev, ()))
        for g in groups:
            sub = g["hooks"][0]["command"].rsplit('" ', 1)[1]
            i = next((j for j, e in enumerate(existing) if e.get("matcher") == g.get("matcher")
                      and e["hooks"][0]["command"].endswith(f'/bin/compose" {sub}')), None)
            if i is None:
                existing.append(g)
                changed = True
            elif existing[i] != g:
                existing[i] = g
                changed = True
        hooks[ev] = existing
    if not changed:
        return []
    fc_core.atomic_write(path, json.dumps(doc, indent=2) + "\n")
    return [path]

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
