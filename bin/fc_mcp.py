"""Per-role MCP server policy."""
import re
import subprocess

DESIGNER = ("linear", "graft", "figma", "framelink-figma")

ROLE_MCP = {
    "toolsmith": ("graft",),
    "implementer": ("graft",),
    "designer": DESIGNER,
    "design-review": DESIGNER,
}

COVERS = {
    "linear": ("claude_ai_Linear",),
    "graft": ("graft",),
    "figma": ("claude_ai_Figma",),
    "framelink-figma": ("framelink-figma",),
}


def servers_for(role):
    if re.fullmatch(r"design-\d+", role) or role in ("designer", "design-review"):
        return DESIGNER
    return ROLE_MCP.get(role, ("linear", "graft"))


def keeps_skills(role):
    return bool(re.fullmatch(r"design-\d+", role)) or role in ("designer", "design-review")


def installed_servers(cwd):
    try:
        p = subprocess.run(["claude", "mcp", "list"], cwd=str(cwd), capture_output=True, text=True, check=False)
    except OSError:
        return []
    if p.returncode != 0:
        return []
    out = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            if out:
                break
            continue
        if ":" not in line:
            continue
        name = line.split(": ", 1)[0]
        out.append(re.sub(r"[^A-Za-z0-9_-]", "_", name))
    return out


def disallowed(role, servers, frame0=False):
    allowed = set()
    for s in servers_for(role):
        allowed.update(COVERS.get(s, (s,)))
    patterns = ["mcp__%s__*" % s for s in servers if s not in allowed]
    if frame0:
        patterns = [p for p in patterns if "frame0" not in p]
    return patterns
