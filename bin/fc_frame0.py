import hashlib, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path
import fc_core, fc_herdr


# ---------- frame0: one wireframing app per project ----------

# Frame0 sends every API command to its newest window, so sessions sharing one app draw over each other. Each project gets
# its own app process instead: its own user-data dir (which holds the API port), one window on .compose/<project>/design.f0,
# and a local-scope `frame0` MCP server pointed at that port in every directory the project's sessions run in. The MCP server
# only reaches the app when a tool is called, so registering costs nothing until something draws.
FRAME0_APP = Path("/Applications/Frame0.app")
FRAME0_PORTS = range(58400, 59000)
FRAME0_CLIENT = "Frame0 MCP Server"  # the app name frame0-mcp-server asks with; once allowed, Frame0 gives it the token again without asking

def frame0_port(proj):
    """The project's API port: stable, so registering the MCP server never waits for the app."""
    h = int(hashlib.sha1(str(proj.resolve()).encode()).hexdigest(), 16)
    return FRAME0_PORTS[h % len(FRAME0_PORTS)]

def frame0_pid(proj):
    """Pid of the project's Frame0 main process, or None. Its helper processes carry the same flag, so only the app binary counts."""
    flag = f"--user-data-dir={proj.resolve() / 'frame0'}"
    for line in fc_core.sh(["ps", "-axo", "pid=,command="], ".", check=False).stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if command.startswith(str(FRAME0_APP / "Contents" / "MacOS" / "Frame0") + " ") and command.endswith(flag):
            return int(pid)
    return None

def frame0_register(cwd, port):
    """Point the `frame0` MCP server of sessions started in `cwd` at `port` (local scope: ~/.claude.json, nothing in the repo).
    Sessions read it at start, so this runs before a teammate starts."""
    cwd = Path(cwd).resolve()
    args = ["-y", "frame0-mcp-server", f"--api-port={port}"]
    try:
        projects = json.loads((Path.home() / ".claude.json").read_text()).get("projects") or {}
    except (OSError, json.JSONDecodeError):
        projects = {}
    # claude keys a linked worktree's local config under the main checkout, so that is where the entry sits
    current = ((projects.get(str(fc_core.worktrees(cwd)[0])) or {}).get("mcpServers") or {}).get("frame0")
    if current and current.get("args") == args:
        return
    if current:
        fc_core.sh(["claude", "mcp", "remove", "frame0", "-s", "local"], cwd, check=False)
    fc_core.sh(["claude", "mcp", "add", "-s", "local", "frame0", "--", "npx", *args], cwd)

def frame0_command(port, command, args=None):
    """Run one Frame0 command over its API, as the MCP server does."""
    def post(path, body, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            out = json.loads(e.read() or b"{}")
        if not out.get("success"):
            raise RuntimeError(f"frame0 {path}: {out.get('error', out)}")
        return out.get("data")
    return post("/execute_command", {"command": command, "args": args or {}}, post("/request_api_token", {"appName": FRAME0_CLIENT}))

def frame0_empty_doc():
    doc, page = os.urandom(8).hex(), os.urandom(8).hex()
    return {"id": doc, "type": "Doc", "parent": None,
            "children": [{"id": page, "type": "Page", "parent": doc, "name": "Page 1", "enable": False, "pageOrigin": [0, 0], "children": []}]}

def frame0_up(proj):
    if not FRAME0_APP.exists():
        sys.exit(f"Frame0 is not installed at {FRAME0_APP}; install it from https://frame0.app")
    port, data, design = frame0_port(proj), proj / "frame0", proj / "design.f0"
    data.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write((data / "config.json"), json.dumps({"api-server": True, "api-server-port": port}))
    if not design.exists():
        fc_core.atomic_write(design, json.dumps(frame0_empty_doc()))
    try:
        frame0_register(fc_herdr.project_worktree(proj), port)
    except RuntimeError as e:  # the app still starts; only the MCP tools are missing
        print(f"frame0 MCP server not registered: {e}")
    if frame0_pid(proj):
        return port, False
    if fc_core.port_listening(port):
        sys.exit(f"port {port}, {proj.name}'s Frame0 port, is taken by another process; stop it and run `frame0 up` again")
    fc_core.sh(["open", "-n", "-a", str(FRAME0_APP), str(design.resolve()), "--args", f"--user-data-dir={data.resolve()}"], ".")
    for _ in range(60):
        if fc_core.port_listening(port):
            return port, True
        time.sleep(0.5)
    sys.exit(f"Frame0 started but its API never listened on port {port}")

def frame0_save(proj):
    """Write the drawing to design.f0. Returns False when the project's Frame0 is not running."""
    if not frame0_pid(proj):
        return False
    frame0_command(frame0_port(proj), "file:save", {"allowSaveAs": False})
    return True

def frame0_down(proj):
    """Save, then quit the project's Frame0. Returns whether one was running."""
    pid = frame0_pid(proj)
    if not pid:
        return False
    frame0_save(proj)  # a window with unsaved changes would stop the quit at a Save Changes dialog
    os.kill(pid, 15)
    for _ in range(20):
        if not frame0_pid(proj):
            break
        time.sleep(0.5)
    return True


def cmd_frame0(a):
    """`frame0 up` starts the project's own Frame0 on design.f0, `save` writes the drawing to it, `down` saves and quits."""
    proj = fc_core.project_dir(a)
    design = proj / "design.f0"
    if a.action == "up":
        port, started = frame0_up(proj)
        print(f"frame0 for {proj.name} {'started' if started else 'already running'} on port {port}, file {design}")
        if started:
            print(f"Frame0 asks once to allow \"{FRAME0_CLIENT}\" when the first tool call reaches it: the product owner clicks Allow")
    elif a.action == "save":
        print(f"saved {design}" if frame0_save(proj) else f"{proj.name}'s Frame0 is not running; `frame0 up` starts it")
    else:
        print(f"frame0 for {proj.name} saved to {design} and stopped" if frame0_down(proj) else f"{proj.name}'s Frame0 is not running")
