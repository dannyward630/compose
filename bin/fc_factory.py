"""`compose factory`: start and stop the build loop process, watch what it does, and set its pace, planning and offers."""
import fcntl, json, os, signal, subprocess, sys, time, traceback
from pathlib import Path

import fc_core, fc_config, fc_herdr, fc_change, fc_watch, fc_factorystate, fc_factoryturn

POLL = 2.0  # seconds between looks at the event log in one watch

def lock_path(repo):
    path = fc_factorystate.state_path(repo).with_name("factory.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def alive(pid):
    """True while a process with this pid exists (one we may not signal still counts)."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def clock(t=None):
    return time.strftime("%H:%M:%S", time.localtime(t))

def spawn_loop(repo):
    """The loop as a process of its own, out of this terminal's session; its output goes to .compose/factory.log. Returns its pid."""
    log = fc_factorystate.state_path(repo).with_name("factory.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as out:
        p = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "compose.py"), "factory", "loop", "--repo", str(repo)],
                             start_new_session=True, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    return p.pid

def _sleep(seconds, stopping):
    end = time.monotonic() + seconds
    while not stopping() and (left := end - time.monotonic()) > 0:
        time.sleep(min(1.0, left))

def run_loop(repo, turns=None):
    """One turn after another until SIGTERM (after the turn it is in) or `turns` are done; the pid stays recorded, `alive` tells whether it runs."""
    lock = open(lock_path(repo), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        sys.exit("factory: already running")
    stop = []
    previous = signal.signal(signal.SIGTERM, lambda signum, frame: stop.append(signum))
    try:
        state = fc_factorystate.load_state(repo)
        state["pid"], state["started"], state["stopped"] = os.getpid(), time.time(), None
        fc_factorystate.save_state(repo, state)
        done = 0
        while not stop and (turns is None or done < turns):
            state = fc_factorystate.load_state(repo)  # a verb run meanwhile (pace, plan, decline) is not written over
            try:
                lines = fc_factoryturn.turn(repo, state, time.time())
            except Exception as e:
                traceback.print_exc()
                lines = [f'event factory=turn-failed why="{type(e).__name__}: {e}"  (the next turn tries again)']
            for line in lines:
                fc_factorystate.add_event(repo, line)
            fc_factorystate.save_state(repo, state)
            done += 1
            if turns is None or done < turns:
                _sleep(fc_config.FACTORY["turn_seconds"], lambda: bool(stop))
    finally:
        signal.signal(signal.SIGTERM, previous)
        lock.close()

def status_lines(repo, state):
    p = fc_factorystate.pace(state)
    if alive(state["pid"]):
        head = f'running (pid {state["pid"]}, since {clock(state["started"])})'
    elif state["stopped"]:
        head = f'stopped (since {clock(state["stopped"])})'
    else:
        head = "not running"
    lines = [f'factory: {head}, {p["mode"]} pace {p["cap"]} tickets at once']
    for ident, r in sorted(state["dispatched"].items()):
        lines.append(f'  dispatched: {ident} ({r["project"]}, {r["kind"]})')
    if state["offer"]:
        lines.append(f'  last offer: {state["offer"]["id"]} ({state["offer"]["layer"]})')
    if state["planning"]:
        lines.append(f'  planning: {state["planning"]["id"]}')
    if state["declined_until"] and state["declined_until"] > time.time():
        lines.append(f'  no planning offers until {clock(state["declined_until"])[:5]}')
    return lines

def verb_start(a, repo):
    if not fc_herdr.herdr_env():
        sys.exit("factory: start it inside herdr: the team leads it starts live there (sections/0h.md)")
    state = fc_factorystate.load_state(repo)
    if alive(state["pid"]):
        sys.exit(f'factory: already running (pid {state["pid"]}); compose factory status shows it')
    state["stopped"] = None
    state["pid"] = spawn_loop(repo)
    fc_factorystate.save_state(repo, state)
    print(f'factory: started (pid {state["pid"]}), {fc_factorystate.pace(state)["mode"]} pace {fc_factorystate.pace(state)["cap"]} tickets at once; '
          f'compose factory watch wakes you on its events')

def verb_stop(a, repo):
    state = fc_factorystate.load_state(repo)
    state["stopped"] = time.time()
    held = 0
    for ident, record in sorted(state["dispatched"].items()) if a.hold else ():
        got = fc_factoryturn.project_for(repo, record["feature"])
        if not got:
            continue
        rests = fc_change.rests_on(got[2], [ident])
        if rests:
            fc_change.hold_tasks(got[2], list(rests), f"factory stopped: {a.hold}")
            held += len(rests)
    fc_factorystate.save_state(repo, state)
    if state["pid"] and state["pid"] != os.getpid() and alive(state["pid"]):
        os.kill(state["pid"], signal.SIGTERM)
    print(f"factory: stopped; held {held} tasks" if a.hold else "factory: stopped; running work finishes")

def verb_status(a, repo):
    state = fc_factorystate.load_state(repo)
    lines = status_lines(repo, state)
    if a.json:
        print(json.dumps({"running": alive(state["pid"]), "pid": state["pid"], "pace": fc_factorystate.pace(state), "dispatched": state["dispatched"],
                          "offer": state["offer"], "planning": state["planning"], "lines": lines}, indent=2))
    else:
        print("\n".join(lines))

def _seen_path(repo):
    return fc_factorystate.state_path(repo).with_name(f"factory-watch-{fc_watch.watch_key()}.json")

def verb_watch(a, repo):
    path = _seen_path(repo)
    try:
        mem = json.loads(path.read_text())
    except (OSError, ValueError):
        mem = {}
    seen, lost = mem.get("seen", 0), mem.get("lost")
    deadline = None if a.timeout is None else time.monotonic() + float(a.timeout)
    while True:
        new = fc_factorystate.events_since(repo, seen)
        state = fc_factorystate.load_state(repo)
        out = [f'[{clock(e["at"])}] {e["line"]}' for e in new]
        if new:
            seen = new[-1]["n"]
        if state["pid"] and not state["stopped"] and not alive(state["pid"]) and lost != state["pid"]:
            lost = state["pid"]
            out.append(f"[{fc_core.now()}] event factory=loop-lost  (the loop is not running: compose factory start runs it again; its state is on disk)")
        if out:
            path.parent.mkdir(parents=True, exist_ok=True)
            fc_core.atomic_write(path, json.dumps({"seen": seen, "lost": lost}))
            print("\n".join(out))
            return
        if deadline is not None and time.monotonic() >= deadline:
            print(f"[{fc_core.now()}] event timeout")
            sys.exit(2)
        time.sleep(POLL if deadline is None else max(0.0, min(POLL, deadline - time.monotonic())))

def verb_pace(a, repo):
    state = fc_factorystate.load_state(repo)
    p = fc_factorystate.pace(state)
    if a.target is None:
        print(f'factory: {p["mode"]} pace {p["cap"]} tickets at once')
        return
    if not a.target.isdigit() or int(a.target) < 1:
        sys.exit(f"factory pace takes a whole number of 1 or more, not {a.target}")
    state["day_tickets"] = int(a.target)
    fc_factorystate.save_state(repo, state)
    print(f'factory: {p["mode"]} pace {a.target} tickets at once (was {p["cap"]}); nothing running is stopped')

def verb_plan(a, repo):
    state = fc_factorystate.load_state(repo)
    if a.done:
        state["planning"] = None
        fc_factorystate.save_state(repo, state)
        print("factory: planning done; offers resume")
        return
    if not a.target:
        sys.exit("factory plan takes the ticket being planned (compose factory plan NEB-30) or --done")
    state["planning"] = {"id": a.target, "at": time.time()}
    out_of_order = a.target != (state["offer"] or {}).get("id")
    if out_of_order and a.target not in state["out_of_order"]:
        state["out_of_order"].append(a.target)
    fc_factorystate.save_state(repo, state)
    print(f"factory: planning {a.target}" + (" (out of order: once it is specced you are asked whether to move it up)" if out_of_order else ""))

def verb_decline(a, repo):
    state = fc_factorystate.load_state(repo)
    state["declined_until"] = time.time() + 60 * fc_config.FACTORY["offer_snooze_minutes"]
    state["said"].pop("offer", None)
    fc_factorystate.save_state(repo, state)
    print(f'factory: no planning offers until {clock(state["declined_until"])[:5]}; ready work keeps building')

def verb_loop(a, repo):
    run_loop(repo)

def cmd_factory(a):
    if a.action in ("start", "loop") and not fc_config.LINEAR_KEY:
        sys.exit(fc_config.needs_linear_key("compose factory"))
    globals()[f"verb_{a.action}"](a, Path(a.repo).resolve())
