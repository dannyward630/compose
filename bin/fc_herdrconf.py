"""herdr's config: a fresh herdr gets the shipped setup/herdr.toml; an existing one gets only the two lines compose needs."""
import os
import re
import shutil
from pathlib import Path
import fc_init

# (section, key, the line to set, herdr's default when the key is absent): the two values compose needs quiet, NEB-754 C4.
QUIET = (
    ("ui.sound", "enabled", "enabled = false", "false", "true"),
    ("ui.toast", "delivery", 'delivery = "off"', "off", "off"),
)


def apply_herdr_config(path, shipped):
    """(state, lines): state is written, ok, manual, or edited; lines say what was done or what to set by hand.
    written: path was missing, so shipped is copied there (parent created). ok: both values already quiet. manual: path is a
    symlink or unwritable while a value is loud, so the lines tell the user the two lines to set and where. edited: a plain
    writable file gets only the loud lines replaced in their section, a missing section or key added, every other line kept."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(shipped, path)
        return "written", [f"copied {shipped} to {path}"]
    cfg = fc_init.herdr_toml(path)
    loud = [(s, k, line) for s, k, line, quiet, default in QUIET if cfg.get(f"{s}.{k}", default) != quiet]
    if not loud:
        return "ok", []
    if path.is_symlink() or not os.access(path, os.W_OK):
        lines = [f"{path} is a symlink or not writable, so compose left it alone; set these lines by hand:"]
        for s, k, line, _, _ in QUIET:
            lines += [f"[{s}]", line]
        return "manual", lines
    return "edited", _edited(path, loud)


def _edited(path, loud):
    """Rewrite path with only the loud lines changed and return the lines describing it. A loud key's line in its section is
    replaced, a missing key is inserted after its section header, a missing section is appended at the end."""
    lines = path.read_text().splitlines(keepends=True)
    key_line, header_line, section = {}, {}, ""
    for i, line in enumerate(lines):  # the same parsing fc_init.herdr_toml does
        s = re.sub(r"(^|\s)#.*$", "", line).strip()
        if m := re.fullmatch(r"\[([\w.-]+)\]", s):
            header_line.setdefault(m.group(1), i)
            section = m.group(1)
        elif m := re.match(r"([\w.-]+)\s*=\s*(.+)$", s):
            key_line[(section, m.group(1))] = i
    replaces, inserts, appends = {}, {}, []
    for s, k, line in loud:
        if (n := key_line.get((s, k))) is not None:
            replaces[n] = line + ("\n" if lines[n].endswith("\n") else "")
        elif s in header_line:
            inserts.setdefault(header_line[s], []).append(line + "\n")
        else:
            appends += [f"[{s}]", line]
    out = []
    for i, line in enumerate(lines):
        out.append(replaces.get(i, line))
        out += inserts.get(i, [])
    if appends:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out += [a + "\n" for a in appends]
    path.write_text("".join(out))
    return [f"edited {path}:"] + [f"  [{s}] {line}" for s, k, line in loud]
