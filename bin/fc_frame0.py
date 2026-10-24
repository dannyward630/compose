import argparse, hashlib, http.server, json, os, signal, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path
import fc_core


# ---------- frame0: one wireframing app per project ----------

# Frame0 sends every API command to its newest window, so sessions sharing one app draw over each other. Each project gets
# its own app process instead: its own user-data dir (which holds the API port), one window on .compose/<project>/design.f0,
# and a `frame0` MCP server pointed at that port, given only to the sessions that wireframe (`crew start --frame0`, the designer)
# through `--mcp-config`. Never in ~/.claude.json: a server registered there starts with every session in the directory, tools
# allowed or not, so each teammate of a project ran its own idle copy. The server is
# `compose frame0 mcp`, which runs it behind a proxy that renews its API token: Frame0 keeps tokens in memory, one set per app
# process, and frame0-mcp-server asks for its token once and keeps it for good, so after the app restarts every call it makes
# is refused (403 "Invalid API token", shown as "Failed to execute command(...)") and no Allow prompt ever comes.
FRAME0_APP = Path("/Applications/Frame0.app")
FRAME0_PORTS = range(58400, 59000)
FRAME0_CLIENT = "Frame0 MCP Server"  # the app name frame0-mcp-server asks with; once allowed, Frame0 gives it the token again without asking
FRAME0_WAIT = 300  # seconds the proxy waits on the app: a token request stays open until someone answers the Allow prompt

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

def frame0_mcp_config(port):
    """The `--mcp-config` value that gives one session the `frame0` MCP server, pointed at `port`."""
    return json.dumps({"mcpServers": {"frame0": {"type": "stdio", "command": "compose", "args": ["frame0", "mcp", f"--api-port={port}"]}}})

def frame0_post(port, path, body, token=None, timeout=60):
    """POST a JSON body to the app's API: (http status, reply). An app that refuses or stays silent raises RuntimeError saying what to check."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        with e:  # an HTTPError holds the open response
            return e.code, json.loads(e.read() or b"{}")
    except OSError as e:
        if isinstance(getattr(e, "reason", e), ConnectionRefusedError):
            raise RuntimeError(f"Frame0 is not listening on port {port}; `frame0 up` starts it") from e
        raise RuntimeError(f"Frame0 did not answer on port {port}: a dialog is probably open in its window (the Allow prompt for \"{FRAME0_CLIENT}\", "
                           "or Save Changes) and blocks the app until someone answers it") from e

def frame0_client(port):
    """A function that runs Frame0 commands over its API, as the MCP server does, on one token asked for once."""
    def post(path, body, token=None):
        out = frame0_post(port, path, body, token)[1]
        if not out.get("success"):
            raise RuntimeError(f"frame0 {path}: {out.get('error', out)}")
        return out.get("data")
    token = post("/request_api_token", {"appName": FRAME0_CLIENT})  # an unset argument is left out, as JSON.stringify drops undefined: the app refuses null
    return lambda command, args=None: post("/execute_command", {"command": command, "args": {k: v for k, v in (args or {}).items() if v is not None}}, token)

def frame0_command(port, command, args=None):
    """Run one Frame0 command over its API."""
    return frame0_client(port)(command, args)

def frame0_proxy(port):
    """A local server in front of the app's API on `port`, for frame0-mcp-server. When the app refuses the server's token (the app
    restarted and lost it), the proxy asks for a new one under the same app name (the Allow prompt, once per app process), keeps it,
    and repeats the call, so the server's own stale token stops mattering. Not started: the caller runs serve_forever()."""
    lock, state = threading.Lock(), {"token": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            auth = self.headers.get("Authorization") or ""
            sent = auth[len("Bearer "):] if auth.startswith("Bearer ") else None
            try:
                used = state["token"] or sent
                status, out = frame0_post(port, self.path, body, used, FRAME0_WAIT)
                if status == 403 and self.path == "/execute_command":
                    with lock:  # one Allow prompt for the calls that were refused together
                        if (state["token"] or sent) == used:
                            status, out = frame0_post(port, "/request_api_token", {"appName": FRAME0_CLIENT}, None, FRAME0_WAIT)
                            if out.get("success"):
                                state["token"] = out["data"]
                        if state["token"]:
                            status, out = frame0_post(port, self.path, body, state["token"], FRAME0_WAIT)
            except RuntimeError as e:
                status, out = 502, {"success": False, "error": str(e)}
            data = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # stdout and stderr belong to the MCP session

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server

def frame0_mcp(argv):
    """`compose frame0 mcp --api-port=<port>`: the `frame0` MCP server of a session. Runs frame0-mcp-server behind frame0_proxy and
    hands it this process's stdin and stdout, so the session talks to it directly. Ends with it."""
    ap = argparse.ArgumentParser(prog="compose frame0 mcp")
    ap.add_argument("--api-port", type=int, required=True, help="the project's Frame0 API port")
    proxy = frame0_proxy(ap.parse_args(argv).api_port)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    child = subprocess.Popen(["npx", "-y", "frame0-mcp-server", f"--api-port={proxy.server_address[1]}"], start_new_session=True)
    def stop(sig, _frame):
        os.killpg(child.pid, signal.SIGTERM)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, stop)
    sys.exit(child.wait())

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
    """Write the drawing to design.f0. Returns False when the project's Frame0 is not running. Raises RuntimeError when it does not answer."""
    if not frame0_pid(proj):
        return False
    frame0_command(frame0_port(proj), "file:save", {"allowSaveAs": False})
    return True

def frame0_down(proj):
    """Save, then quit the project's Frame0. Returns whether one was running. Raises RuntimeError, leaving the app up, when it cannot save."""
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


# ---------- frame0 draw: many shapes in one call ----------

# Each frame0 MCP tool call is one model turn, and every turn re-sends the whole session, so a wireframe drawn shape by shape
# costs hundreds of turns. `frame0 draw` takes the same tools as a JSON list and runs them in one command: the same names,
# arguments, and defaults as frame0-mcp-server, which sends them to the app as these API commands.
FRAME0_FRAMES = {"phone": ("Phone", 320, 690, 0), "tablet": ("Tablet", 600, 800, 0), "desktop": ("Desktop", 800, 600, 32),
                 "browser": ("Browser", 800, 600, 76), "watch": ("Watch", 198, 242, 0), "tv": ("TV", 960, 570, 0)}
FRAME0_ICONS = {"small": 16, "medium": 24, "large": 32, "extra-large": 48}
FRAME0_ALIGN = {"bring-to-front": "align:bring-to-front", "send-to-back": "align:send-to-back", "align-left": "align:align-left",
                "align-right": "align:align-right", "align-horizontal-center": "align:align-center", "align-top": "align:align-top",
                "align-bottom": "align:align-bottom", "align-vertical-center": "align:align-middle",
                "distribute-horizontally": "align:horizontal-distribute", "distribute-vertically": "align:vertical-distribute"}
FRAME0_TOOLS = {  # tool: (required args, optional args)
    "add_page": ({"name"}, {"after"}),  # after: a page id, to put the page right behind it; else it goes behind the current page
    "set_current_page_by_id": ({"pageId"}, set()),
    "create_frame": ({"frameType", "name"}, {"fillColor"}),
    "create_rectangle": ({"name", "left", "top", "width", "height"}, {"parentId", "fillColor", "strokeColor", "corners"}),
    "create_ellipse": ({"name", "left", "top", "width", "height"}, {"parentId", "fillColor", "strokeColor"}),
    "create_text": ({"name", "left", "top", "text"}, {"type", "parentId", "width", "fontColor", "fontSize"}),
    "create_line": ({"name", "x1", "y1", "x2", "y2"}, {"parentId", "strokeColor"}),
    "create_polygon": ({"name", "points"}, {"parentId", "closed", "fillColor", "strokeColor"}),
    "create_connector": ({"name", "startId", "endId"}, {"parentId", "startArrowhead", "endArrowhead", "strokeColor"}),
    "create_icon": ({"name", "left", "top", "size"}, {"parentId", "strokeColor"}),
    "update_shape": ({"shapeId"}, {"name", "width", "height", "fillColor", "strokeColor", "fontColor", "fontSize", "corners", "text"}),
    "move_shape": ({"shapeId", "dx", "dy"}, set()),
    "duplicate_shape": ({"shapeId"}, {"parentId", "dx", "dy"}),
    "delete_shape": ({"shapeId"}, set()),
    "align_shapes": ({"alignType", "shapeIdArray"}, set()),
    "group": ({"shapeIdArray"}, {"parentId"}),
    "set_link": ({"shapeId", "linkType"}, {"url", "pageId"}),
}

def frame0_props(**kw):
    return {k: v for k, v in kw.items() if v is not None}

def frame0_arrowhead(name):
    return "flat" if name in (None, "none") else name

def frame0_op(call, tool, a):
    """Run one tool the way frame0-mcp-server does. Returns the id it made or changed, or None."""
    g = a.get
    def shape(kind, **props):
        return call("shape:create-shape", {"type": kind, "shapeProps": frame0_props(**props), "parentId": g("parentId"), "convertColors": True})
    if tool == "add_page":
        if g("after"):
            call("page:set-current-page", {"pageId": a["after"]})  # page:add puts a page behind the current one, so a page for a journey lands behind that journey's pages
        page = call("page:add", {"pageProps": {"name": a["name"]}})
        return page.get("id") if isinstance(page, dict) else page
    if tool == "set_current_page_by_id":
        call("page:set-current-page", {"pageId": a["pageId"]})
        return a["pageId"]
    if tool == "create_frame":
        if a["frameType"] not in FRAME0_FRAMES:
            raise ValueError(f"frameType is one of {', '.join(FRAME0_FRAMES)}")
        name, w, h, header = FRAME0_FRAMES[a["frameType"]]
        sid = call("shape:create-shape-from-library-by-query", {"query": f"{name}&@Frame", "shapeProps": frame0_props(
            name=a["name"], left=0, top=-header, width=w, height=h + header, fillColor=g("fillColor", "#ffffff")), "convertColors": True})
        call("view:fit-to-screen")
        return sid
    if tool in ("create_rectangle", "create_ellipse"):
        return shape("Rectangle" if tool == "create_rectangle" else "Ellipse", name=a["name"], left=a["left"], top=a["top"], width=a["width"], height=a["height"],
                     fillColor=g("fillColor", "#ffffff"), strokeColor=g("strokeColor", "#000000"),
                     corners=g("corners", [0, 0, 0, 0]) if tool == "create_rectangle" else None)
    if tool == "create_text":
        return shape("Text", name=a["name"], left=a["left"], width=g("width"), top=a["top"], text=a["text"], fontColor=g("fontColor", "#000000"),
                     fontSize=g("fontSize"), wordWrap=g("type") == "paragraph")
    if tool in ("create_line", "create_polygon"):
        path = [[a["x1"], a["y1"]], [a["x2"], a["y2"]]] if tool == "create_line" else [[p["x"], p["y"]] for p in a["points"]]
        if tool == "create_polygon":
            if len(path) < 3:
                raise ValueError("points needs at least 3 points")
            if g("closed", True) and path[0] != path[-1]:
                path.append(path[0])
        return shape("Line", name=a["name"], path=path, tailEndType="flat", headEndType="flat", strokeColor=g("strokeColor", "#000000"), lineType="straight")
    if tool == "create_connector":
        return call("shape:create-connector", {"tailId": a["startId"], "headId": a["endId"], "shapeProps": frame0_props(
            name=a["name"], tailEndType=frame0_arrowhead(g("startArrowhead")), headEndType=frame0_arrowhead(g("endArrowhead")),
            strokeColor=g("strokeColor", "#000000")), "parentId": g("parentId"), "convertColors": True})
    if tool == "create_icon":
        size = FRAME0_ICONS.get(a["size"], 24)
        return call("shape:create-icon", {"iconName": a["name"], "shapeProps": frame0_props(left=a["left"], top=a["top"], width=size, height=size,
                    strokeColor=g("strokeColor", "#000000")), "parentId": g("parentId"), "convertColors": True})
    if tool == "update_shape":
        return call("shape:update-shape", {"shapeId": a["shapeId"], "shapeProps": frame0_props(**{k: g(k) for k in FRAME0_TOOLS[tool][1]}), "convertColors": True})
    if tool == "move_shape":
        call("shape:move", {"shapeId": a["shapeId"], "dx": a["dx"], "dy": a["dy"]})
        return a["shapeId"]
    if tool == "duplicate_shape":
        return call("edit:duplicate", {"shapeIdArray": [a["shapeId"]], "parentId": g("parentId"), "dx": g("dx"), "dy": g("dy")})[0]
    if tool == "delete_shape":
        call("edit:delete", {"shapeIdArray": [a["shapeId"]]})
        return None
    if tool == "align_shapes":
        if a["alignType"] not in FRAME0_ALIGN:
            raise ValueError(f"alignType is one of {', '.join(FRAME0_ALIGN)}")
        call(FRAME0_ALIGN[a["alignType"]], {"shapeIdArray": a["shapeIdArray"]})
        return None
    if tool == "group":
        return call("shape:group", {"shapeIdArray": a["shapeIdArray"], "parentId": g("parentId")})
    call("shape:set-link", {"shapeId": a["shapeId"], "linkProps": frame0_props(linkType=a["linkType"], url=g("url"), pageId=g("pageId"))})
    return a["shapeId"]

FRAME0_ID_ARGS = ("parentId", "startId", "endId", "shapeId", "pageId", "shapeIdArray", "after")  # where `$name` means an id; a text's "$5" stays text

def frame0_refs(op):
    """The `$name` references in an op's id arguments."""
    vals = [v for k in FRAME0_ID_ARGS if k in op for v in (op[k] if isinstance(op[k], list) else [op[k]])]
    return [v for v in vals if isinstance(v, str) and v.startswith("$")]

def frame0_resolve(op, ids):
    """The op's arguments with each `$name` in an id argument swapped for the id an earlier op saved `as` name."""
    sub = lambda v: [sub(x) for x in v] if isinstance(v, list) else ids.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v
    return {k: sub(v) if k in FRAME0_ID_ARGS else v for k, v in op.items() if k not in ("tool", "as")}

def frame0_check(ops):
    """Every problem with a draw list that can be seen before anything is drawn, as one message each."""
    if not isinstance(ops, list) or not ops:
        return ["the draw list is a JSON array of ops, each {\"tool\": \"create_text\", \"as\": \"title\", ...the tool's arguments}"]
    errors, named = [], set()
    for n, op in enumerate(ops, 1):
        if not isinstance(op, dict) or op.get("tool") not in FRAME0_TOOLS:
            errors.append(f"op {n}: tool is one of {', '.join(FRAME0_TOOLS)}, not {op.get('tool') if isinstance(op, dict) else op!r}")
            continue
        need, may = FRAME0_TOOLS[op["tool"]]
        args = {k for k in op if k not in ("tool", "as")}
        if need - args:
            errors.append(f"op {n} ({op['tool']}): missing {', '.join(sorted(need - args))}")
        if args - need - may:
            errors.append(f"op {n} ({op['tool']}): unknown {', '.join(sorted(args - need - may))}")
        errors += [f"op {n} ({op['tool']}): {r} names no earlier op's `as`" for r in frame0_refs(op) if r[1:] not in named]
        if "as" in op:
            named.add(op["as"])
    return errors

def frame0_line(n, op, sid, call):
    """One short line per op: what it made, its id, and a created shape's box (a text's real size, to place what follows)."""
    label = f"{n:>3} {op.get('as', '-')} {op['tool']}"
    if sid is None:
        return label
    if not op["tool"].startswith("create_") and op["tool"] not in ("duplicate_shape", "group"):
        return f"{label} {sid}"
    try:
        s = call("shape:get-shape", {"shapeId": sid}) or {}
    except RuntimeError:  # drawn all the same: the box is only a convenience
        s = {}
    box = " ".join(f"{k}={round(s[k])}" for k in ("left", "top", "width", "height") if isinstance(s.get(k), (int, float)))
    return f"{label} {sid} {box}".rstrip()

def frame0_draw(proj, ops):
    """Run a draw list against the project's Frame0, then save design.f0. Returns the lines to print; raises RuntimeError naming the
    op that failed, after saving what was drawn before it."""
    errors = frame0_check(ops)
    if errors:
        raise RuntimeError("nothing drawn:\n" + "\n".join(errors))
    if not frame0_pid(proj):
        raise RuntimeError(f"{proj.name}'s Frame0 is not running; `frame0 up` starts it")
    call, ids, lines = frame0_client(frame0_port(proj)), {}, []
    for n, op in enumerate(ops, 1):
        try:
            sid = frame0_op(call, op["tool"], frame0_resolve(op, ids))
        except (RuntimeError, ValueError, KeyError, IndexError, TypeError) as e:
            try:
                call("file:save", {"allowSaveAs": False})
                kept = "drawn and saved"
            except RuntimeError as save:
                kept = f"drawn but not saved ({save})"
            done = f"ops 1-{n - 1} are {kept}" if n > 1 else "nothing was drawn"
            raise RuntimeError("\n".join([*lines, f"op {n} ({op['tool']}) failed: {e}",
                                          f"{done}; send op {n} on, with the ids above in place of its $names"])) from e
        if "as" in op and sid is not None:
            ids[op["as"]] = sid
        lines.append(frame0_line(n, op, sid, call))
    call("file:save", {"allowSaveAs": False})
    return lines


def cmd_frame0(a):
    """`frame0 up` starts the project's own Frame0 on design.f0, `draw` runs a JSON list of frame0 tool calls in one go and saves,
    `save` writes the drawing to it, `down` saves and quits. (`frame0 pages|move|delete|links|lint` are fc_f0pages'; `frame0 mcp` is the session's MCP server, run by Claude Code through main.)"""
    proj = fc_core.project_dir(a)
    design = proj / "design.f0"
    try:
        if a.action == "up":
            port, started = frame0_up(proj)
            print(f"frame0 for {proj.name} {'started' if started else 'already running'} on port {port}, file {design}")
            if started:
                print(f"Frame0 asks once to allow \"{FRAME0_CLIENT}\" when the first tool call reaches it: the product owner clicks Allow")
        elif a.action == "draw":
            src = sys.stdin.read() if a.file in (None, "-") else Path(a.file).read_text()
            try:
                ops = json.loads(src)
            except ValueError as e:
                sys.exit(f"frame0 draw: the draw list is not JSON: {e}")
            print("\n".join(frame0_draw(proj, ops)))
            print(f"drew {len(ops)} ops, saved {design}")
        elif a.action == "save":
            print(f"saved {design}" if frame0_save(proj) else f"{proj.name}'s Frame0 is not running; `frame0 up` starts it")
        elif a.action == "down":
            print(f"frame0 for {proj.name} saved to {design} and stopped" if frame0_down(proj) else f"{proj.name}'s Frame0 is not running")
    except RuntimeError as e:
        sys.exit(f"frame0 {a.action}: {e}")
