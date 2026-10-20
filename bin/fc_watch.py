import argparse, fcntl, json, os, re, sys, time
from pathlib import Path
import fc_core, fc_tasks, fc_herdr, fc_change, fc_crew, fc_status, fc_briefs


YOLO_HINT = "  yolo=on (answer with the recommendation; log it: compose yolo decided ...)"

# ---------- watch ----------
FINAL_STATES = ("passed", "already_green", "failed", "contradiction", "rejected_size", "rejected_docs", "rejected_scope", "rejected_tampered", "payment_required", "interrupted", "hand_done", "unchained")

AGENTS_INTERVAL = 10.0  # seconds between `herdr agent list` calls in one watch loop: a teammate's status moves at the pace of its turns

class Agents:
    """`herdr agent list` for one watch loop, asked at most once per AGENTS_INTERVAL: one process per poll from every parked watch is too many.
    Asked again when the crew `records` changed since the last list: a teammate `crew_up` just marked as listed is judged by a list
    taken after that, never by one from before herdr listed it, which would count it as closed."""
    def __init__(self):
        self.at, self.listed, self.records = None, None, None

    def __call__(self, records=None):
        now = time.monotonic()
        if self.at is None or now - self.at >= AGENTS_INTERVAL or records != self.records:
            self.listed, self.at, self.records = fc_herdr.herdr("agent", "list"), now, records
        return self.listed

def watch_snapshot(repo, proj, agents=None):
    """Everything a team lead decides on: each task's state, each herdr agent's status, run and verify markers."""
    try:
        rows = fc_status.board(repo, proj)["rows"]
    except json.JSONDecodeError:  # a writer that is not ours caught mid-write: one more look, then the real error
        time.sleep(0.5)
        rows = fc_status.board(repo, proj)["rows"]
    # The marker alone is not enough: a run that crashes leaves it behind, and watch then waits on a dead run forever.
    snap = {"tasks": {}, "agents": {}, "run": fc_tasks.run_alive(proj), "crashed": bool(fc_tasks.run_marker(proj)) and not fc_tasks.run_alive(proj), "verify": None, "halt": None,
            "crew": {f.stem: fc_crew.crew_reports(proj, f.stem) for f in sorted((proj / "results" / "crew").glob("*.status"))}
            if (proj / "results" / "crew").exists() else {}}
    try:
        h = json.loads((proj / "results" / "resume.json").read_text())
        snap["halt"] = [h["halted_at"], h["provider"], len(h.get("remaining") or [])]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    try:
        snap["ready"] = {i["id"]: i["title"] for i in json.loads((proj / "results" / "ready.json").read_text())}
    except (OSError, json.JSONDecodeError):
        snap["ready"] = {}
    for r in rows:
        snap["tasks"][r["id"]] = {"state": r["state"], "attempts": r["attempts"], "cost": r["cost"], "note": r["note"], "linear": r["linear"], "title": r["title"]}
    records = [json.loads(f.read_text()) for f in sorted((proj / "results" / "crew").glob("*.json"))]  # before the list: it must be as new as they are
    listed = agents(records) if agents else fc_herdr.herdr("agent", "list")
    agents = None if listed is None else listed.get("agents", [])
    for ag in agents or []:
        n = ag.get("name") or ""
        if fc_herdr.agent_id(proj.name, n):
            snap["agents"][n] = ag.get("agent_status")
    snap["closed"] = [c["name"] for c in records if fc_crew.tab_closed(c, agents)]  # whatever their last report says, not working
    snap["owner"] = crew_owners(records, agents)  # which engineering manager session each teammate is: watch_scope
    pis = [c for c in records if "skill" in c and c.get("agent", c["name"]) in snap["agents"]]
    try:
        cur = fc_crew.skill_hashes() if pis else {}
    except OSError:
        pis = []
    snap["skill"] = {c["name"]: changed for c in pis if (changed := fc_crew.skill_changed(c["skill"], cur))}  # live pi teammates reading an old skill
    v = proj / "results" / "verify.json"
    if v.exists():
        try:
            snap["verify"] = [int(v.stat().st_mtime), bool(json.loads(v.read_text()).get("passed"))]  # a list: snapshots round-trip JSON
        except (json.JSONDecodeError, OSError):
            pass
    # The newest sign of life anywhere in the project, and when the last run ended: the stall rules read these.
    marks = [(fc_core.report_time(r[-1]["at"]), f"teammate {n} reported {r[-1]['state']}") for n, r in snap["crew"].items() if r]
    marks += [(f.stat().st_mtime, f"result {f.name}") for f in (proj / "results").glob("*.json") if not f.name.startswith("watch")]
    snap["last"] = list(max(marks)) if marks else [0, ""]
    cost = proj / "results" / "run-cost.json"
    snap["run_end"] = cost.stat().st_mtime if cost.exists() and not snap["run"] else 0
    cut = fc_change.evidence_cut(proj)  # a screen a closed change or a dismissal already answered is not news, not even to `--now`
    snap["reflects"] = {}
    for f in sorted((proj / "results").glob("reflect-*.json")):
        try:
            r = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if r.get("at", "") > cut:
            snap["reflects"][str(f)] = {"trigger": r.get("trigger"), "error": r.get("error"), "counts": fc_change.reflect_counts(r)}
    return snap

def crew_owners(records, agents):
    """Each teammate an engineering manager session started, mapped to that session (`started_by`) while a live agent still sits in
    its pane; the team lead's own teammates follow their team lead. A teammate whose session ended has no owner, so any engineering
    manager session adopts it, and so does one from before `started_by` existed. `agents` None (herdr cannot say) keeps every session live."""
    live = None if agents is None else {ag.get("pane_id") for ag in agents}
    own = {c["name"]: c["started_by"] for c in records
           if c.get("reports_to") == "manager" and c.get("started_by") and (live is None or c["started_by"] in live)}
    lead = next((own[c["name"]] for c in records if c.get("role") == "orchestrator" and c["name"] in own), None)
    if lead:
        own |= {c["name"]: lead for c in records if c.get("reports_to") == "orchestrator"}
    return own

STALL_SECONDS = 240  # verify.json `stall_seconds` or `watch --stall` change it

def watch_mem(proj, key):
    """What one watcher (key: watch_key) last reported and which stalls it fired, in results/watch-<key>.json."""
    try:
        return json.loads((proj / "results" / f"watch-{key}.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}

def watch_save(proj, key, **kv):
    mem = watch_mem(proj, key) | kv
    f = proj / "results" / f"watch-{key}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(f.with_suffix(".tmp"), json.dumps(mem))
    f.with_suffix(".tmp").replace(f)  # atomic: a reader never sees half a file

def watch_lock(proj, key, wait=True):
    """One live watch per watcher, held until the returned file closes. None when another holds it and wait is False."""
    (proj / "results").mkdir(parents=True, exist_ok=True)
    f = open(proj / "results" / f"watch-{key}.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        return f
    except BlockingIOError:
        f.close()
        return None

def watch_stalls(proj, snap, limit, now_s=None, key="all"):
    """The silences an event diff never shows: work is pending but nothing moves. Each stall fires once per watcher
    (results/watch-<key>.json remembers it), so a supervisor that nudges is not woken again for the same silence."""
    now_s = now_s or time.time()
    orch = fc_herdr.agent_name(proj.name, "orchestrator")
    last = {n: (r[-1]["state"], fc_core.report_time(r[-1]["at"])) for n, r in snap.get("crew", {}).items() if r}
    closed = set(snap.get("closed", ()))
    pending = [t for t, v in snap["tasks"].items() if v["state"] in ("pending", "running", "interrupted")]
    on_hold = [t for t, v in snap["tasks"].items() if v["state"] == "held"]  # waiting on a change of course: still work to move
    working = [n for n, (st, _) in last.items() if st == "working" and n != orch and n not in closed]
    mem = watch_mem(proj, key)
    fired, seen = set(mem.get("fired", [])), mem.get("seen", {})
    lead = orch in snap.get("crew", {}) or orch in snap["agents"]  # a project started without a team lead (a designer started directly) never has one
    who = f" agent={orch}" if lead else ""
    status = snap["agents"].get(orch, "gone")
    if (seen.get(orch) or [None])[0] != status:
        seen[orch] = [status, now_s]
    ev = []
    hm = lambda t: time.strftime("%H:%M:%S", time.localtime(t))
    tail = f"{f'team lead {status}' if lead else 'no team lead'}, pending tasks {len(pending)}{f', held {len(on_hold)}' if on_hold else ''}, teammates working {','.join(working) or 'none'}"
    if lead:
        tail += f"  (read: herdr agent read {orch} --lines 60; nudge: herdr agent prompt {orch} \"...\")"
    def fire(key, what):
        if key not in fired:
            fired.add(key)
            ev.append(f"event stall={what}; {tail}")
    for n in snap.get("closed", ()):
        r = snap.get("crew", {}).get(n) or []
        if r and r[-1]["state"] != "done" and not (re.search(r"-tests-\d+$", n) and fc_briefs.test_ready(r[-1])):  # collect closes a writer after its test ready
            fire(f"ended:{n}:{r[-1]['at']}", f"ended agent={n} its tab closed with its last report {r[-1]['state']}")
    if not (last.get(orch, ("",))[0] == "done" or any(st == "needs-user" for st, _ in last.values())):  # finished, or waiting on the product owner: silence is expected
        lt, what = snap.get("last") or (0, "")
        if (pending or on_hold or working or snap["run"]) and lt and now_s - lt >= limit:
            fire(f"quiet:{lt}", f"quiet{who} nothing moved for {fc_core.fmt(now_s - lt)}, last: {what} at {hm(lt)}")
        tests = {n: v for n, v in last.items() if re.search(r"-tests-\d+$", n)}
        if tests and all(st == "done" or n in closed for n, (st, _) in tests.items()) and not snap["run"] and pending \
                and all(snap["tasks"][t]["state"] == "pending" for t in pending):
            done_at = max(t for _, t in tests.values())
            if now_s - done_at >= limit:
                fire(f"undispatched:{done_at}", f"undispatched{who} every test-writing teammate was done by {hm(done_at)} and nothing is dispatched")
        ended = max(snap.get("run_end") or 0, (snap.get("verify") or (0,))[0])
        if lead and ended and not snap["run"] and last.get(orch, ("", 0))[1] < ended and now_s - ended >= limit:
            fire(f"after:{ended}", f"no-next-step agent={orch} the last run or verify ended at {hm(ended)} and the team lead has not reported since")
        since = seen[orch][1]
        if lead and status in ("idle", "done") and (pending or on_hold) and now_s - since >= limit:
            fire(f"idle:{since}", f"idle agent={orch} the team lead has been {status} since {hm(since)} with {len(pending + on_hold)} task(s) pending")
    try:
        watch_save(proj, key, fired=sorted(fired), seen=seen)
    except OSError:
        pass
    return ev

def watch_events(before, after):
    """The actionable differences between two snapshots, one line each. Attempt counts and idle/done flaps are not events."""
    ev = []
    for tid, t in after["tasks"].items():
        b = before["tasks"].get(tid, {})
        if t["state"] != b.get("state") and (t["state"] in FINAL_STATES or t["state"] == "running"):
            ev.append(f"event task={tid} state={t['state']} attempts={t['attempts']} cost=${t['cost']:.4f}"
                      + (f" branch={t['note']}" if t["note"] else "") + (f" linear={t['linear']}" if t["linear"] else "") + f" title={t['title']!r}")
    for n, st in after["agents"].items():
        if st == "blocked" and before["agents"].get(n) != "blocked":
            ev.append(f"event agent={n} status=blocked  (read: herdr agent read {n} --lines 60; steer: herdr agent prompt {n} \"...\")")
    if before["run"] and not after["run"]:
        passed = sum(t["state"] in ("passed", "already_green", "merged") for t in after["tasks"].values())
        ev.append(f"event run=ended passed={passed}/{len(after['tasks'])}"
                  + ("  CRASHED: the run process died without finishing; read results/run.log, fix the cause, then `compose resume`" if after.get("crashed") else ""))
    if after.get("halt") and after["halt"] != before.get("halt"):
        at_, provider, left = after["halt"]
        ev.append(f"event halt=payment provider={provider} remaining={left} at={at_!r}  (the product owner's stop: tell them, wait for "
                  f"their word, then `compose resume`)")
    new = {i: t for i, t in after.get("ready", {}).items() if i not in before.get("ready", {})}
    if new:
        import fc_linear
        items = [{"id": i, "title": t} for i, t in new.items()]
        ev.append(f"event ready={','.join(new)}  ({fc_linear.ready_line(items)}; tell the product owner)")
    if after["verify"] and after["verify"] != before["verify"]:
        ev.append(f"event verify={'PASS' if after['verify'][1] else 'FAIL'}")
    for n, reports in after.get("crew", {}).items():
        for r in reports[len(before.get("crew", {}).get(n, [])):]:
            if r["message"] != "started":
                ev.append(f"event crew={n} state={r['state']} message={r['message']!r}")
    for n, changed in after.get("skill", {}).items():
        if changed != before.get("skill", {}).get(n):
            ev.append(f"event crew={n} skill=stale changed={','.join(changed)}")
    for path, r in after.get("reflects", {}).items():
        if path in before.get("reflects", {}):
            continue
        if r["error"]:
            ev.append(f"event reflect={path} error={r['error']!r}  (the screen did not run: judge the evidence yourself)")
        elif sum(r["counts"]):
            ev.append(f"event reflect={path} broken={r['counts'][0]} unclear={r['counts'][1]} trigger={r['trigger']}")
    return ev

def yolo_mark(proj, events):
    """Under yolo, a question line tells the engineering manager it answers it itself, and who set yolo when another session did."""
    if not (y := fc_tasks.yolo_state(proj)):
        return events
    by = fc_tasks.yolo_by(y)
    hint = YOLO_HINT if by in ("this session", "unknown") else YOLO_HINT.replace("yolo=on (", f"yolo=on set by {by} (", 1)
    return [e + hint if re.match(r"event crew=\S+ state=needs-user ", e) else e for e in events]

def watch_filter(events, slug, sources, direct=(), others=()):
    """`--from` names the teammates whose reports wake you (the engineering manager watches only its team lead); without it you get
    everything except the team lead's own reports, which go up to the engineering manager. `direct` names the teammates that report to
    this watcher (crew_reporting_to): a planner or designer the engineering manager started itself passes whatever `--from` says, so
    its needs-user and blocked reach the product owner (manager_attention) while the `--from orchestrator` watch runs. `others` names
    another engineering manager session's teammates (watch_scope): none of their lines wakes this one unless `--from` names them."""
    if others := [n for n in others if n not in sources]:
        events = [e for e in events if not any(f"crew={n} " in e or f"agent={n} " in e for n in others)]
    if sources:  # a tool-bug from any teammate wakes the engineering manager too: it owns fixing the tool; a stall is its to supervise
        return [e for e in events if " state=tool-bug " in e or " state=fallback " in e or e.startswith("event stall=")
                or e.startswith("event ready=")
                or any(f"crew={n} " in e or f"agent={n} " in e for n in (*sources, *direct))]
    me = fc_herdr.agent_name(slug, "orchestrator")
    return [e for e in events if f"crew={me} " not in e and not e.startswith(f"event stall=idle agent={me} ")]  # idle: it waits on this watch

WATCH_INTERVAL = 2.0

def watch_key():
    """Whose watch this is: COMPOSE_ROLE, else the engineering manager, one per session (`manager-<herdr pane>`; bare `manager`
    outside herdr). Two engineering manager sessions on one project never share a lock or a memory, so neither waits on the
    other's watch or has its events marked seen by it."""
    if role := os.environ.get("COMPOSE_ROLE"):
        return role
    return "manager-" + re.sub(r"[^\w-]", "-", fc_core.session_id()) if fc_core.session_id() else "manager"

def watch_scope(proj, snap):
    """(direct, others) for an engineering manager's watch: the teammates this session started (crew_owners), plus every one that
    reports to an engineering manager whose session ended or never recorded one; and those another live session started."""
    if os.environ.get("COMPOSE_ROLE"):
        return (), ()
    mine, owner = fc_core.session_id(), snap.get("owner") or {}
    return ([n for n in fc_crew.crew_reporting_to(proj, "manager") if owner.get(n, mine) == mine],
            [n for n, by in owner.items() if by != mine])

def cmd_watch(a, rewake=False):
    """Sleep on the project until something a team lead must act on happens, print it, exit. Zero tokens while waiting:
    run it in the background and let its exit wake you. `--now` prints the current state as events and exits.
    Each watcher (watch_key: COMPOSE_ROLE, else this engineering manager session; --from only filters what is printed) remembers what it last
    reported, so a watch started later still reports what happened while none ran. `rewake` is the Stop hook's mode: the event goes to stderr with exit 2, which wakes the session."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    sources = [fc_herdr.agent_ref(proj.name, x.strip()) for x in (a.from_ or "").split(",") if x.strip()]
    key = watch_key()
    if a.now:
        cur = watch_snapshot(repo, proj)
        empty = {"tasks": {}, "agents": {}, "run": cur["run"] or cur.get("crashed"), "verify": None, "halt": None,
                 "crew": {n: r[:-1] for n, r in cur["crew"].items()}}  # each teammate's latest report, once
        lines = yolo_mark(proj, watch_filter(watch_events(empty, cur), proj.name, sources, *watch_scope(proj, cur)))
        if y := fc_tasks.yolo_state(proj):
            lines.insert(0, f"event yolo=on push={'yes' if y.get('push') else 'no'} since={y['since']!r} by={fc_tasks.yolo_by(y)!r} words={y.get('words', '')!r}")
        if cur["run"]:
            lines.append(f"event run=live pid={(fc_tasks.run_marker(proj) or {}).get('pid')}  (a run is in progress: supervise it with watch, "
                         f"read results/run.log; do not start a second)")
        for line in lines or ["event idle  nothing running"]:
            print(line)
        watch_save(proj, key, base=cur)  # the reconcile is the acknowledgement: the next watch reports only what changes after it
        return
    lock = watch_lock(proj, key, wait=not rewake)  # a second watch waits its turn; a second hook leaves it to the parked one
    if not lock:
        return
    with lock:  # held until this watch returns or exits
        before = watch_mem(proj, key).get("base") or watch_snapshot(repo, proj)
        emit = (lambda s: print(s, file=sys.stderr)) if rewake else print
        parent = os.getppid()
        deadline = time.time() + a.timeout if a.timeout else None
        try:
            cfg_stall = json.loads((proj / "verify.json").read_text()).get("stall_seconds")
        except (OSError, json.JSONDecodeError):
            cfg_stall = None
        limit = a.stall if a.stall is not None else (cfg_stall or STALL_SECONDS)
        agents = Agents()
        while True:
            time.sleep(a.interval)
            if rewake and os.getppid() != parent:
                return  # the session that parked this hook is gone
            after = watch_snapshot(repo, proj, agents)
            ev = yolo_mark(proj, watch_filter(watch_events(before, after) + watch_stalls(proj, after, limit, key=key), proj.name, sources, *watch_scope(proj, after)))
            if ev:
                fc_crew.manager_attention(proj, ev)
                if rewake:
                    emit("compose watch woke you. When this turn ends the Stop hook parks the next watch; do not start one yourself.")
                    try:
                        if note := fc_crew.skill_notice(a.session):  # a wake is a prompt the UserPromptSubmit hook never sees
                            emit(note)
                    except Exception:
                        pass
                for line in ev:
                    emit(f"[{fc_core.now()}] {line}")
                watch_save(proj, key, base=after)  # after printing: a watch killed in between reports it again rather than never
                if rewake:
                    sys.exit(2)
                return
            before = after
            if deadline and time.time() > deadline:
                watch_save(proj, key, base=after)
                pending = sum(t["state"] in ("pending", "running", "interrupted") for t in after["tasks"].values())
                working = [n for n, r in after["crew"].items() if r and r[-1]["state"] == "working" and n not in after.get("closed", ())]
                print(f"[{fc_core.now()}] event timeout  nothing changed in {fc_core.fmt(a.timeout)}: pending tasks {pending}, teammates working "
                      f"{','.join(working) or 'none'}, run {'live' if after['run'] else 'not live'}, verify "
                      f"{'PASS' if after['verify'] and after['verify'][1] else 'FAIL' if after['verify'] else 'not run'}")
                sys.exit(2)

def cmd_rewake(a):
    """Claude Code Stop hook (the plugin's hooks.json, asyncRewake): when a team lead's turn ends, park a watch whose event
    wakes the idle session. Its herdr tab carries the role, project, and worktree. Every other session returns at once,
    a headless one (`claude -p`, which Claude Code marks CLAUDE_CODE_ENTRYPOINT=sdk-*) too. A wake names skill files changed since the last one."""
    project = os.environ.get("COMPOSE_PROJECT")
    if os.environ.get("COMPOSE_ROLE") != "orchestrator" or not project or os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    try:
        session = re.sub(r"[^\w-]", "", json.load(sys.stdin).get("session_id") or "")
    except Exception:
        session = ""
    cmd_watch(argparse.Namespace(repo=os.environ.get("COMPOSE_REPO") or ".", project=project, now=False, from_=None,
                                 timeout=0, stall=None, interval=WATCH_INTERVAL, session=session), rewake=True)

def crew_in_pane(proj, pane):
    """The teammate whose record says it runs in herdr pane `pane`, else None."""
    for f in sorted(fc_crew.crew_dir(proj).glob("*.json")) if pane else ():
        try:
            c = json.loads(f.read_text())
        except ValueError:
            continue
        if isinstance(c, dict) and c.get("pane") == pane:
            return c.get("name")
    return None

def cmd_reenter(a):
    """Claude Code SessionStart hook (matcher compact): after a compaction the session continues by re-entering through 0r, not from scratch.
    Its herdr tab carries the role, the teammate's name, project, and worktree. COMPOSE_ROLE is `crew` for every teammate but the
    guarded ones, so the brief is found by the name (a session started before its tab carried one: by the pane its record names).
    Every other session returns at once, a headless one (`claude -p`, which Claude Code marks CLAUDE_CODE_ENTRYPOINT=sdk-*) too."""
    project, role = os.environ.get("COMPOSE_PROJECT"), os.environ.get("COMPOSE_ROLE")
    if not role or not project or os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    proj = fc_core.project_dir(argparse.Namespace(repo=os.environ.get("COMPOSE_REPO") or ".", project=project))
    name = os.environ.get("COMPOSE_TEAMMATE") or crew_in_pane(proj, os.environ.get("HERDR_PANE_ID")) or fc_herdr.agent_name(project, role)
    print("Your context was just compacted; the session continues by re-entering through 0r, not from scratch.")
    print(f"Re-read your brief file {fc_crew.crew_dir(proj) / f'{name}.brief.md'} now.")
    print(f"Run `compose status --repo {os.environ.get('COMPOSE_REPO') or '.'} --project {project}` and "
          f"`compose watch --repo {os.environ.get('COMPOSE_REPO') or '.'} --project {project} --now` to see the board.")
    print("Re-read the feature's Decisions so far and Plan on Linear before acting.")
