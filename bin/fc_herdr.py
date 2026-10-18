import shlex, json, os, re, signal, subprocess, sys, time
from pathlib import Path
import fc_core


# ---------- herdr ----------
# Inside herdr (HERDR_ENV=1) the fleet is visible: one space per project, a `status` tab, one tab per task holding a named
# interactive pi agent the team lead can steer with `herdr agent prompt`, and a verify tab of stage panes. Every call
# here is best-effort: outside herdr, or when herdr refuses, the run continues exactly as the headless path would.

HERDR_SPACES = {}  # project name -> workspace id, filled by herdr_space
PI_HERDR_EXT = Path.home() / ".pi" / "agent" / "extensions" / "herdr-agent-state.ts"

def herdr_env():
    return os.environ.get("HERDR_ENV") == "1" and bool(os.environ.get("HERDR_SOCKET_PATH"))

PANE_MAKERS = (("tab", "create"), ("pane", "split"), ("workspace", "create"))
def herdr_argv(args):
    """The herdr command line for `args`. A new pane gets the herdr server's env, not ours, so a call that makes one passes the
    caller's COMPOSE_CONFIG and HOME on: a scratch config stays scratch in the CLI, agent, or teammate that pane runs.
    They go last: herdr reads `pane split`'s pane id only as the argument right after the subcommand."""
    args = [str(a) for a in args]
    if tuple(args[:2]) in PANE_MAKERS:
        args += [x for k in ("COMPOSE_CONFIG", "HOME") if os.environ.get(k) for x in ("--env", f"{k}={os.environ[k]}")]
    return ["herdr", *args]

def herdr(*args, check=False, timeout=120):
    """One herdr CLI call. Returns the JSON `result`, or None when not inside herdr or the call failed (raises if check)."""
    if not herdr_env():
        return None
    try:
        p = subprocess.run(herdr_argv(args), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        if check:
            raise RuntimeError(f"herdr {' '.join(map(str, args[:2]))}: {e}")
        return None
    try:
        out = json.loads((p.stdout or p.stderr or "{}").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        out = {}
    if p.returncode or "error" in out:
        if check:
            raise RuntimeError(f"herdr {' '.join(map(str, args[:2]))}: {(out.get('error') or {}).get('code') or p.stderr.strip()[-200:]}")
        return None
    return out.get("result", out)

def herdr_error(*args, timeout=120):
    """Like herdr() but returns the error code string on failure ("timeout", "agent_blocked", ...) instead of None."""
    p = subprocess.run(herdr_argv(args), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    try:
        out = json.loads((p.stdout or p.stderr or "{}").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        out = {}
    if p.returncode or "error" in out:
        return None, ((out.get("error") or {}).get("code") or p.stderr.strip()[-200:] or "error")
    return out.get("result", out), None

def herdr_text(*args, timeout=30):
    """One herdr CLI call whose answer is plain text (`agent read`): the text, or "" outside herdr or when the call failed."""
    if not herdr_env():
        return ""
    try:
        p = subprocess.run(herdr_argv(args), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""

def herdr_ready(agent, timeout=60):
    """Return once a Claude session's input box (its `❯` line) is on screen, or it is already on a turn, blocked on a dialog, or done.
    `herdr agent start` reports a Claude session ready seconds before its UI exists, while the pane still shows the shell command
    (`herdr agent explain`: idle, rule none): text typed then is kept in the box unsent, or dropped outright, so a brief waits for the box."""
    for _ in range(max(1, timeout // 2)):
        got = (herdr("agent", "get", agent) or {}).get("agent") or {}
        if not got or got.get("agent_status") in ("working", "blocked", "done"):
            return
        if any(ln.lstrip().startswith("❯") for ln in herdr_text("agent", "read", agent, "--source", "visible", "--lines", "40").splitlines()):
            return
        time.sleep(2)

def herdr_dialog(agent):
    """The dialog a blocked Claude session shows (its title, text, and choices, on one line), read from its pane: everything below
    the last rule line, without the key hints. "unknown" when the pane cannot be read."""
    lines = herdr_text("agent", "read", agent, "--source", "visible", "--lines", "40").splitlines()
    rules = [i for i, ln in enumerate(lines) if ln.strip() and set(ln.strip()) <= set("─━-")]
    body = [ln.strip().removeprefix("❯").strip() for ln in lines[rules[-1] + 1 if rules else 0:]]
    text = " / ".join(ln for ln in body if ln and not ln.startswith(("Enter to confirm", "Esc to")))
    return text[:400] or "unknown"

def herdr_await_start(agent, first=None, tries=3):
    """Return once `agent` has started on its brief, the first prompt it gets. This only confirms the submission landed (status
    working, blocked, or done); when it did not, presses Enter for a box that kept the text without submitting, then sends `first`
    again for a box that lost it, and fails loudly with the agent name when it still did not start."""
    def started():  # `done` counts too: a short first turn can finish before the check
        return ((herdr("agent", "get", agent) or {}).get("agent") or {}).get("agent_status") in ("working", "blocked", "done")
    def settles(secs):
        for _ in range(secs // 2):
            if started():
                return True
            time.sleep(2)
        return False
    for attempt in range(tries + 1):
        if attempt:
            herdr("agent", "send-keys", agent, "enter")
            if settles(6):
                return
            if first:
                herdr("agent", "prompt", agent, first)
        if settles(20):
            return
    raise RuntimeError(f"{agent} did not start on its brief after {tries} retries: look in its tab"
                       + (f", and send it again with: herdr agent prompt {agent} {shlex.quote(first)}" if first else ""))

def herdr_start_crew(*args, tries=8):
    """`herdr agent start` for a teammate, retried while its pane is still coming up: starts running in parallel (designcrews,
    testcrews) race each other and the new pane answers agent_pane_busy until its shell is there, or agent_name_not_found while herdr
    has not yet registered the name the start waits for (the session may be up under its pane's default name: it is renamed)."""
    for i in range(tries):
        try:
            return herdr("agent", "start", *args, check=True, timeout=90)
        except RuntimeError as e:
            if ("timeout" in str(e) or "agent_name_not_found" in str(e)) and "--pane" in args:  # the session can come up after the call gave up: name it rather than lose it
                pane = args[args.index("--pane") + 1]
                for _ in range(10):  # it may still be registering with herdr when the call gives up
                    if any(ag.get("pane_id") == pane for ag in live_agents()):
                        print(f"herdr agent start timed out but {args[0]} came up; continuing")
                        return herdr("agent", "rename", pane, args[0], check=True)
                    time.sleep(2)
                if pane_launching(args[0], pane):  # one last look by name and by pane: an agent that can still come up is never declared dead
                    print(f"herdr agent start timed out but {args[0]} is still starting in its pane; continuing")
                    return None
            if not any(c in str(e) for c in ("agent_pane_busy", "agent_name_not_found")) or i == tries - 1:
                raise
            time.sleep(0.5 * (i + 1))

def pane_processes(pane):
    """The processes running in `pane` in front of its shell: empty when the pane holds nothing but an idle shell."""
    info = (herdr("pane", "process-info", "--pane", pane) or {}).get("process_info") or {}
    return [p for p in info.get("foreground_processes", []) if p.get("pid") != info.get("shell_pid")] \
        if info.get("foreground_process_group_id") != info.get("shell_pid") else []

def pane_launching(agent, pane):
    """True when `agent` is registered by name, listed on `pane`, or the pane runs a process that is still becoming it."""
    return bool(herdr("agent", "get", agent)) or any(ag.get("pane_id") == pane for ag in live_agents()) or bool(pane_processes(pane))

def pane_kill(pane):
    """Stop whatever runs in `pane` in front of its shell, so closing the tab leaves nothing unregistered behind."""
    for p in pane_processes(pane):
        try:
            os.kill(p["pid"], signal.SIGTERM)
        except (OSError, KeyError):
            pass

def agent_name(slug, tid):
    """herdr agent names: [a-z][a-z0-9_-]{0,31}, unique among live agents. `<slug>-<id>`, slug trimmed to fit."""
    s = re.sub(r"[^a-z0-9_-]+", "-", slug.lower()).strip("-")
    if not re.match(r"[a-z]", s):
        s = "fc-" + s
    return f"{s[:32 - len(tid) - 1]}-{tid}"

def herdr_main_repo(wt):
    common = fc_core.sh(["git", "rev-parse", "--git-common-dir"], wt, check=False).stdout.strip()
    return str(Path(wt, common).resolve().parent) if common else str(wt)

def herdr_find_space(wt):
    """The workspace id whose checkout is this path (`worktree.checkout_path` in `workspace list`)."""
    wt = str(Path(wt).resolve())
    for w in (herdr("workspace", "list") or {}).get("workspaces", []):
        cp = (w.get("worktree") or {}).get("checkout_path")
        if cp and str(Path(cp).resolve()) == wt:
            return w["workspace_id"]
    return None

def project_worktree(proj):
    """The project's own checkout: proj is `<worktree>/.compose/<name>`."""
    return Path(proj).resolve().parents[1]

def live_agents():
    return (herdr("agent", "list") or {}).get("agents", [])

def herdr_space(proj):
    """Open the project's worktree as its own herdr space labelled `<name>`, grouped under the repo's space. Idempotent.
    Keyed on the project's worktree, never on where a command happens to run (verify runs in the CLI's stack worktree)."""
    if not herdr_env():
        return None
    slug, wt = Path(proj).name, project_worktree(proj)
    if slug in HERDR_SPACES:
        return HERDR_SPACES[slug]
    space = herdr_find_space(wt)
    if not space:
        r = herdr("worktree", "open", "--cwd", herdr_main_repo(wt), "--path", str(wt), "--label", slug, "--no-focus") or {}
        space = (r.get("workspace") or {}).get("workspace_id") or r.get("workspace_id")
    if not space:
        r = herdr("workspace", "create", "--cwd", str(wt), "--label", slug, "--no-focus") or {}
        space = (r.get("workspace") or {}).get("workspace_id")
    if space:
        HERDR_SPACES[slug] = space
        herdr("workspace", "rename", space, slug)
        for label, t in herdr_tabs(space).items():
            if label and label.isdigit():  # the tab herdr opened with the space: a shell in the project worktree
                herdr("tab", "rename", t["tab_id"], "shell")
        herdr_status_tab(space, wt, slug)
    return space


def herdr_tabs(space):
    return {t.get("label"): t for t in (herdr("tab", "list", "--workspace", space) or {}).get("tabs", [])}

def herdr_status_tab(space, wt, slug):
    """A `status` tab running `compose status --watch`, so the product owner sees every task's state without asking."""
    if "status" in herdr_tabs(space):
        return
    r = herdr("tab", "create", "--workspace", space, "--label", "status", "--cwd", str(wt), "--no-focus") or {}
    pane = (r.get("root_pane") or {}).get("pane_id")
    if pane:
        me = str(Path(sys.argv[0]).resolve())
        herdr("pane", "run", pane, f"clear; {me} status --repo {wt} --project {slug} --watch")

def herdr_label(session, label, cost, state="working"):
    """Display-only pane metadata: the state label the product owner reads next to the agent, and the running cost."""
    if session and session.get("pane"):
        herdr("pane", "report-metadata", session["pane"], "--source", "compose", "--state-label", f"{state}={label}",
              "--state-label", f"done={label}", "--token", f"cost=${cost:.4f}")

IMPLEMENTERS_TAB = "implementers"

def herdr_implementer_pane(space, cwd, env):
    """A fresh pane for one implementer in the space's single `implementers` tab: the tab's root pane when the tab is new,
    else a split of its newest pane, alternating right and down so the panes tile instead of thinning into strips."""
    env_args = [x for k, v in env.items() for x in ("--env", f"{k}={v}")]
    tab = herdr_tabs(space).get(IMPLEMENTERS_TAB)
    if not tab:
        r = herdr("tab", "create", "--workspace", space, "--label", IMPLEMENTERS_TAB, "--cwd", str(cwd), *env_args, "--no-focus", check=True)
        return r["root_pane"]["pane_id"]
    panes = [p for p in (herdr("pane", "list", "--workspace", space) or {}).get("panes", []) if p.get("tab_id") == tab["tab_id"]]
    direction = "right" if len(panes) % 2 else "down"
    r = herdr("pane", "split", panes[-1]["pane_id"], "--direction", direction, "--cwd", str(cwd), *env_args, "--no-focus", check=True)
    return r["pane"]["pane_id"]

def herdr_agent_start(*args, tries=8):
    """`herdr agent start`, retried while the pane is still coming up: a pane split a moment ago answers agent_pane_busy
    until its shell prompt is there, which is the harness racing itself and never a reason to fail a task."""
    for i in range(tries):
        started, err = herdr_error("agent", "start", *args, timeout=90)
        if err not in ("agent_pane_busy", "agent_name_not_found") or i == tries - 1:
            break
        time.sleep(0.5 * (i + 1))
    if err:
        raise RuntimeError(f"herdr agent start: {err}")
    return started


def herdr_verify_panes(space, wt, names):
    """The space's one `verify` tab, rebuilt per run, with one pane per stage, each a plain shell the CLI reports states for. {name: pane_id}."""
    if not space or not names:
        return {}
    for label, t in herdr_tabs(space).items():  # the previous run's tab (and the older `verify HH:MM` ones)
        if label == "verify" or re.fullmatch(r"verify \d\d:\d\d", label or ""):
            herdr("tab", "close", t["tab_id"])
    r = herdr("tab", "create", "--workspace", space, "--label", "verify", "--cwd", str(wt), "--no-focus") or {}
    pane = (r.get("root_pane") or {}).get("pane_id")
    if not pane:
        return {}
    panes, prev = {names[0]: pane}, pane
    for n in names[1:]:
        s = herdr("pane", "split", prev, "--direction", "down", "--cwd", str(wt), "--no-focus") or {}
        prev = (s.get("pane") or {}).get("pane_id") or prev
        panes[n] = prev
    for n, pid in panes.items():
        herdr("pane", "rename", pid, n)
        herdr_stage(panes, n, "idle", "pending")
    return panes

def herdr_stage(panes, name, state, message=""):
    if panes.get(name):
        herdr("pane", "report-agent", panes[name], "--source", "compose", "--agent", name, "--state", state, "--message", message, "--seq", str(time.time_ns()))


def herdr_space_is(space, name):
    """Only the project's own space is ever closed by its clean: a checkout path can be a pool slot another project now uses."""
    return any(w.get("workspace_id") == space and w.get("label") == name for w in (herdr("workspace", "list") or {}).get("workspaces", []))
