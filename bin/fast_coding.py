#!/usr/bin/env python3
"""fast-coding: a frontier model plans, parallel fast implementers build, a local pipeline verifies. Stdlib only.

Layout inside any repo (all of .fast-coding/ and graft/ are git-ignored; `init` ignores them before anything else, nothing here is committed):
  .fast-coding/<project>/linear.json   {"feature": "<Linear issue>"}: the plan is its description, its tasks are issues under it
  .fast-coding/<project>/verify.json    local verification config
  .fast-coding/<project>/results/       tasks.json (the team lead's Linear sync), one JSON per task run, verify results
  .fast-coding/<project>/worktrees/     one git clone per task
  .fast-coding/<project>/design.f0      the project's Frame0 wireframes; frame0/ is its own Frame0 instance's data
Nothing is pushed. The only network calls are the model APIs.
"""
import argparse, fcntl, json, os, re, signal, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc_cost, fc_mcp  # noqa: E402
import fc_core, fc_config, fc_tasks, fc_linear, fc_claude, fc_models, fc_herdr, fc_worktree, fc_layers, fc_change, fc_frame0, fc_crew, fc_init, fc_figma, fc_briefs, fc_implement, fc_jev, fc_verify  # noqa: E402

TRIAGE_BAR = ("Flag the layer only for: a change outside its listed files; hardening, flags, helpers, or abstractions the brief "
              "does not ask for; code far more complex than the brief needs; a UI state not placed or styled the way the brief says; "
              "anything aimed at the test rather than the user. Everything else is clean; style nits are clean.")

def triage(repo, proj, ids):
    """One fast-model look per passed task, all at once: `clean`, or `flag: <reason quoting the code>`. It only points the
    team lead at layers to read in full; it never rejects. Stored as `triage` in the task's result file."""
    env = fc_models.fast_env()
    if not env.get("TEXT_MODEL_API_KEY"):
        return {}
    metas = {m["id"]: m for m in fc_tasks.load_tasks(proj)}
    trunk = fc_core.current_branch(repo)
    def one(tid):
        m, branch = metas.get(tid) or {}, f"fast/{proj.name}/{tid}"
        try:
            base = fc_core.sh(["git", "merge-base", trunk, branch], repo).stdout.strip()
            diff = fc_core.sh(["git", "diff", base, branch, "--", *(m.get("files") or [])], repo, check=False).stdout
            v = fc_models.fast_json(env, "You triage one finished coding task for a senior reviewer. " + TRIAGE_BAR +
                          ' Return JSON {"verdict": "clean" | "flag", "reason": str}; a flag reason is one line quoting the code.',
                          f"TASK BRIEF:\n{(m.get('body') or '')[:6000]}\n\nFILES IT MAY CHANGE: {', '.join(m.get('files') or [])}\n\n"
                          f"DIFF:\n{diff[:40000]}", max_tokens=300, timeout=30)
            verdict, reason = ("flag" if v.get("verdict") == "flag" else "clean"), str(v.get("reason") or "").strip()[:300]
        except Exception as e:  # noqa: BLE001 - triage is advisory
            verdict, reason = "unknown", f"triage failed: {str(e)[:150]}"
        f = proj / "results" / f"{tid}.json"
        if f.exists():
            r = json.loads(f.read_text()); r["triage"] = {"verdict": verdict, "reason": reason}
            fc_core.atomic_write(f, json.dumps(r, indent=2))
        return tid, verdict, reason
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(one, ids))
    for tid, verdict, reason in out:
        fc_core.say(f"{tid} triage  {verdict}" + (f": {reason}" if verdict != "clean" and reason else ""))
    return {tid: (v, r) for tid, v, r in out}

def cmd_triage(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    ids = [x.strip() for x in a.only.split(",")] if a.only else sorted(
        f.stem for f in (proj / "results").glob("[0-9]*.json") if json.loads(f.read_text()).get("status") == "passed")
    if not triage(repo, proj, ids):
        sys.exit("no fast-model key (TEXT_MODEL_API_KEY) or no passed tasks: nothing triaged")

def cmd_run(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    only = set(a.only.split(",")) if a.only else None
    if fc_core.sh(["git", "status", "--porcelain"], repo).stdout.strip():
        sys.exit("repo has uncommitted changes; commit the tests first so worktrees include them")
    tasks = [m for m in fc_tasks.code_tasks(fc_tasks.load_tasks(proj, required=True)) if not only or m["id"] in only]
    if not tasks:
        sys.exit("no tasks on Linear under this feature carry a fast-coding block" + (f" with ids {a.only}" if only else ""))
    redo = bool(getattr(a, "redo", False))
    kept = {m["id"]: fc_tasks.task_finished(proj, m, redo) for m in tasks}
    for tid, why in kept.items():
        if why:
            fc_core.say(f"{tid} keep    {why}" + ("; pass --redo to rebuild it" if why.startswith("its result") else ""))
    tasks = [m for m in tasks if not kept[m["id"]]]
    if not tasks:
        return fc_core.say("nothing to run: every task is finished")
    if redo:
        os.environ["FAST_CODING_REDO"] = "1"
    # Test-writing teammates write on their own branches; their tests must be on the project branch before any implementer starts.
    wt = fc_herdr.project_worktree(proj)
    pending = [m["id"] for m in tasks if fc_core.sh(["git", "rev-parse", "--verify", "-q", fc_briefs.test_branch(proj, m["id"])], wt, check=False).returncode == 0]
    if pending:
        busy = [t for t in pending if (fc_crew.crew_reports(proj, fc_herdr.agent_name(proj.name, f"tests-{t}")) or [{}])[-1].get("state") != "done"]
        if busy:
            sys.exit(f"test-writing teammates still writing: {', '.join('tests-' + t for t in busy)}; wait for their done reports, then run again")
        fc_briefs.collect_tests(proj, ",".join(pending))
    run_tasks(repo, proj, tasks, a)

def preflight(models):
    """One tiny turn per model a run can call, before any clone: a wrong model id or preset slug stops the run here with the
    provider's message, instead of failing every task (and, for a fallback, only on the first miss). A rate limit proves the
    model resolved, so it passes."""
    import shutil
    def probe(model):
        root = Path(tempfile.mkdtemp())
        (root / "p").mkdir()
        try:
            fc_implement.implementer(root / "p", model, "Reply with the single word OK. Do not use tools.")
            return None
        except fc_models.RateLimited:
            return None
        except Exception as e:  # noqa: BLE001
            return f"{model}: {str(e)[-400:]}"
        finally:
            shutil.rmtree(root, ignore_errors=True)
    models = sorted(m for m in models if m and not fc_claude.is_claude(m))  # Claude Code is the subscription; nothing to resolve
    fc_core.say(f"preflight  {', '.join(models)}")
    with ThreadPoolExecutor(max_workers=max(1, len(models))) as ex:
        bad = [b for b in ex.map(probe, models) if b]
    if bad:
        sys.exit("preflight failed; nothing was cloned or run. Fix the model id or preset in "
                 f"{fc_config.CONFIG_PATH} (`models`) or the task's `model:`:\n  " + "\n  ".join(bad))

def run_tasks(repo, proj, tasks, a):
    models = {m["model"] for m in tasks}
    preflight(models | {fc_models.fallback_for(m) for m in models})
    a.trunk = a.trunk or fc_core.current_branch(repo)  # the branch the user started on is the stack's trunk; it is never switched
    if fc_worktree.stack_order(repo, proj):
        # Earlier layers must contain everything committed on trunk since they were built (new tests, new task files), or a
        # task stacked on them starts without its own test. Rebase the existing chain onto the current trunk tip first.
        fc_layers.linearize(repo, proj, a.trunk, fc_worktree.stack_worktree(repo, proj, a.trunk))
        if fc_layers.STACK_STOP:
            sys.exit(f"stack  STOP  {fc_layers.STACK_STOP}")
    fc_herdr.herdr_space(proj)
    t0 = time.time()
    (proj / "results").mkdir(exist_ok=True)
    fc_core.atomic_write((proj / "results" / "run.json"), json.dumps({"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tasks": [m["id"] for m in tasks], "args": {"attempts": a.attempts, "parallel": a.parallel, "trunk": a.trunk, "no_stack": a.no_stack}}, indent=2))
    fc_core.say(f"run start  project={proj.name} tasks={len(tasks)} parallel={a.parallel} attempts={a.attempts}")
    # Dependency order: a task runs once every `after:` task in this run has passed (it then stacks on that branch) or was
    # merged or skipped earlier. Independent tasks run in parallel; a chain runs layer by layer.
    metas = {m["id"]: m for m in tasks}
    ids = set(metas)
    deps = {p: [d for d in (x.strip() for x in str(m.get("after") or "").split(",")) if d in ids] for p, m in metas.items()}
    results, pending, failed_ids, halt, reflecting = [], dict(deps), set(), None, []
    from concurrent.futures import wait, FIRST_COMPLETED
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        running = {}
        while pending or running:
            hold = fc_tasks.held(proj)  # re-read every pass: a hold or a release lands while the run goes on
            ready = [] if halt else [p for p, d in pending.items() if not d and p not in running.values() and p not in hold]
            for p in ready[:a.parallel - len(running)]:  # only into free slots: a task queued inside the pool is out of a hold's reach
                del pending[p]
                running[ex.submit(fc_implement.run_task, repo, proj, metas[p], a.attempts)] = p
            if halt and not running:
                break  # a payment halt: leave the rest pending, do not mark them blocked
            if not running:
                stuck = fc_tasks.held_behind(pending, hold, failed_ids)
                for p in pending:
                    if p in stuck:  # left pending for the run after the re-plan, not blocked
                        fc_core.say(f"{p} held    " + (hold[p]["reason"] if p in hold else "after held " + ",".join(sorted(set(pending[p]) & stuck))))
                        continue
                    results.append({"id": metas[p]["id"], "title": metas[p].get("title"), "status": "blocked_by_" + ",".join(deps[p]),
                                    "attempts": 0, "seconds": 0.0, "cost": 0.0, "branch": "-"})  # it waits on something that failed
                break
            finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for f in finished:
                p = running.pop(f)
                try:
                    r = f.result()
                except RuntimeError as e:  # a chain that no longer rebases: one line with the commands, not a traceback
                    sys.exit(f"{p} STOP  {e}")
                results.append(r)
                if r["status"] in fc_change.REFLECT_ON:  # the screen runs beside the run; dispatch never waits on it
                    reflecting.append(threading.Thread(target=reflect_task, args=(proj, r)))
                    reflecting[-1].start()
                tid = metas[p]["id"]
                if r["status"] == "payment_required":
                    pay = next(x["payment_required"] for x in r["log"] if "payment_required" in x)
                    halt = halt or fc_models.PaymentRequired(pay["provider"], pay["message"])
                if r["status"] != "passed":
                    failed_ids.add(tid)
                for q in pending:
                    pending[q] = [d for d in pending[q] if d != tid or d in failed_ids]
    for t in reflecting:  # every screen is on disk before the run reports its end
        t.join()
    results.sort(key=lambda r: r["id"])
    total = time.time() - t0
    print()
    print(f"{'task':6} {'status':18} {'attempts':8} {'time':>9} {'cost':>9}  branch")
    for r in results:
        print(f"{r['id']:6} {r['status']:18} {r['attempts']:<8} {fc_core.fmt(r['seconds']):>9} {'$' + format(r['cost'], '.4f'):>9}  {r['branch']}")
    passed = sum(r["status"] == "passed" for r in results)
    if passed:
        triage(repo, proj, [r["id"] for r in results if r["status"] == "passed"])
    fc_core.say(f"run done   {passed}/{len(results)} passed  wall {fc_core.fmt(total)}  sum of task time {fc_core.fmt(sum(r['seconds'] for r in results))}")
    fc_core.say(fc_core.LEDGER.line())
    if passed and not a.no_stack:
        fc_layers.register_stack(repo, proj, a.trunk)
    if halt:
        done_ids = {r["id"] for r in results if r["status"] in (*fc_tasks.FINISHED, "already_green")}
        remaining = sorted(metas[p]["id"] for p in metas if metas[p]["id"] not in done_ids)
        fc_models.payment_halt(repo, proj, "run", remaining, {"attempts": a.attempts, "parallel": a.parallel, "trunk": a.trunk, "no_stack": a.no_stack}, halt)
    (proj / "results" / "resume.json").unlink(missing_ok=True)
    (proj / "results" / "run.json").unlink(missing_ok=True)
    fc_core.atomic_write((proj / "results" / "run-cost.json"), json.dumps(fc_core.LEDGER.snapshot(), indent=2))
    sys.exit(0 if all(r["status"] in fc_tasks.FINISHED for r in results) else 1)

# ---------- `yolo`: the product owner is away; the engineering manager answers with the recommendation and logs it ----------
YOLO_NEVER = ("destructive, irreversible, and security-sensitive actions are never pre-authorizable whatever the words say: "
              "anything that costs money beyond the configured models (a model or provider switch, keys), the payment halt, "
              "merging a toolsmith fix into fast-coding itself, force-push, `clean --delete-unmerged`, `crew stop --force`, "
              "attended prompts (Frame0 Allow, sign-ins), and anything the product owner's CLAUDE.md forbids. These still stop and wait.")
YOLO_HINT = "  yolo=on (answer with the recommendation; log it: fast-coding yolo decided ...)"

def yolo_digest(repo, proj, y):
    """What the product owner reads on return, rendered only from disk: their words, the decisions, what waits, what failed, what is done, cost."""
    since = fc_core.report_time(y["since"])
    snap = watch_snapshot(repo, proj)
    changed = lambda tid: (f := proj / "results" / f"{tid}.json").exists() and f.stat().st_mtime >= since
    tasks = {tid: t for tid, t in snap["tasks"].items() if changed(tid)}
    waiting = [f"{n}: {r[-1]['state']}  {r[-1]['message']}" for n, r in snap["crew"].items()
               if r and r[-1]["state"] in ("needs-user", "blocked") and fc_core.report_time(r[-1]["at"]) >= since]
    if snap["halt"]:
        waiting.append(f"payment halt at {snap['halt'][1]} ({snap['halt'][2]} task(s) left): top up, then `fast-coding resume`")
    verify = snap["verify"] if snap["verify"] and snap["verify"][0] >= since else None
    if verify and not verify[1]:
        waiting.append("verify FAIL: read results/verify.json")
    failed = [f"{tid} {t['title']}  {t['state']}" for tid, t in tasks.items() if t["state"] == "failed" or t["state"].startswith(("rejected_", "exhausted"))]
    done = [f"{tid} {t['title']}  {t['state']}" for tid, t in tasks.items() if t["state"] in ("passed", "already_green", "merged")]
    if verify and verify[1]:
        done.append("verify PASS")
    layers = proj / "layers.json"
    if layers.exists() and layers.stat().st_mtime >= since:
        done.append("stack submitted: " + ", ".join(json.loads(layers.read_text())))
    elif stack := fc_worktree.stack_order(repo, proj):
        done.append(f"stack ok locally, not pushed: {' <- '.join(stack)}")
    t = fc_cost.total(fc_cost.rows(proj))
    task_cost = sum(v["cost"] for v in snap["tasks"].values())
    sections = [("Your instructions", [y.get("words") or "(no words)", f"push: {'yes' if y.get('push') else 'no'}"]),
                ("Decided for you", [f"{d['ts']}  {d['text']}" for d in y.get("decisions", [])]),
                ("Waiting on you", waiting), ("Tried and failed", failed), ("Done", done),
                ("Cost", [f"{t['input']}in  {t['cache_created']}cc  {t['cache_read']}cr  {t['output']}out  ({t['teammates']} teammates)  tasks ${task_cost:.4f}"])]
    out = [f"yolo off for {proj.name}: away since {y['since']}"]
    for head, items in sections:
        out += ["", head] + [f"- {i}" for i in items or ["none"]]
    return "\n".join(out)

def cmd_yolo(a):
    """Enter yolo (words pre-answer questions verbatim; --push permits the stack's submit), log a decision taken, or come back (`off`)."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    path = proj / "results" / "yolo.json"
    y = fc_tasks.yolo_state(proj)
    words = list(a.words or [])
    if words[:1] in (["off"], ["decided"]) and not y:
        print(f"yolo is not on for {proj.name}; `fast-coding yolo --project {proj.name} [--push] [words]` turns it on")
        sys.exit(1)
    if words == ["off"]:
        print(yolo_digest(repo, proj, y))
        os.replace(path, path.with_name(f"yolo-{y['since'].replace(' ', 'T').replace(':', '')}.json"))
        return
    if words[:1] == ["decided"]:
        if len(words) < 2:
            sys.exit('yolo decided needs "<question>: <answer taken>"')
        y["decisions"].append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "text": " ".join(words[1:])})
        fc_core.atomic_write(path, json.dumps(y, indent=2))
        print(f"logged for the product owner's return: {' '.join(words[1:])}")
        return
    y = y or {"since": time.strftime("%Y-%m-%d %H:%M:%S"), "decisions": []}
    y.update(push=bool(a.push), words=" ".join(words) if words else y.get("words", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(path, json.dumps(y, indent=2))
    print(f"yolo on for {proj.name} since {y['since']}: the engineering manager answers with the recommendation and logs each answer")
    print(f"your words: {y['words'] or '(none)'}")
    print(f"push: {'yes, the verified stack is submitted' if y['push'] else 'no, the stack waits for you'}")
    print(YOLO_NEVER)
    print(f"back: `fast-coding yolo off --project {proj.name}` prints what happened")

def reflect_task(proj, r):
    """A task ended without passing: screen the settled lines against what its last attempt showed. It runs beside the run,
    so nothing here may stop it."""
    try:
        last = (r.get("log") or [{}])[-1]
        head = f"task {r['id']} {r.get('title') or ''}".strip()
        if r["status"] == "contradiction":
            found = last.get("contradiction", "")
            fc_change.reflect(proj, f"task:{r['id']}", f"{head}: the implementer found its brief wrong: {found}",
                    against=[found.split(" / ")[0].strip()])
            return
        why = (last.get("error") or (f"changed files outside its task: {', '.join(last['stray'])}" if last.get("stray") else "")
               or last.get("summary") or (last.get("test_output") or "").strip()[-1500:] or "no detail")
        fc_change.reflect(proj, f"task:{r['id']}", f"{head} ended {r['status']} after {r['attempts']} attempt(s): {why}")
    except Exception as e:  # noqa: BLE001
        fc_core.say(f"{r['id']} reflect failed ({str(e)[:200]}); the run goes on")

def task_state(repo, proj, meta, trunk_head):
    """One row for `status`: state, attempts, seconds, cost, branch note. State comes from the result file, the branch, and trunk."""
    tid = meta["id"]
    res = proj / "results" / f"{tid}.json"
    r = json.loads(res.read_text()) if res.exists() else {}
    branch = f"fast/{proj.name}/{tid}"
    has_branch = fc_core.sh(["git", "rev-parse", "--verify", "-q", branch], repo, check=False).returncode == 0
    merged = has_branch and fc_core.sh(["git", "merge-base", "--is-ancestor", branch, trunk_head], repo, check=False).returncode == 0
    state = r.get("status") or "pending"
    if state == "pending" and fc_tasks.linear_done(meta):
        state = "merged"  # done on Linear (another story's task, or finished earlier): never run again, never a stall
    elif state == "running" and not fc_tasks.run_alive(proj):
        state = "interrupted"  # the run died without writing a final state; `fast-coding resume` re-runs it
    elif state in ("passed", "already_green") and (merged or not has_branch) and meta.get("kind") != "design":
        state = "merged"
    elif state == "hand_done":
        state = "hand_done" if has_branch and not merged else "merged (hand)"
    note = branch if has_branch and not merged else ""
    deps = [d.strip() for d in str(meta.get("after") or "").split(",") if d.strip()]
    if state == "pending" and deps:
        note = "after " + ", ".join(deps)
    hold = fc_tasks.held(proj).get(tid)
    if state == "pending" and hold:
        state, note = "held", hold["reason"]
    return {"id": tid, "title": meta.get("title", ""), "state": state, "attempts": r.get("attempts", 0), "seconds": r.get("seconds", 0.0),
            "cost": r.get("cost", 0.0), "note": note, "model": (r.get("model") or meta.get("model", "")).split("/")[-1]}

def render_status(repo, projects):
    out = []
    for proj in projects:
        tasks = fc_tasks.load_tasks(proj)
        trunk = fc_core.current_branch(repo)
        trunk_head = fc_core.sh(["git", "rev-parse", "HEAD"], repo).stdout.strip()
        rows = [task_state(repo, proj, m, trunk_head) for m in tasks]
        layers = {b: i + 1 for i, b in enumerate(fc_worktree.stack_order(repo, proj))}
        counts = {}
        for r in rows:
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        v = proj / "results" / "verify.json"
        vtxt = ""
        if v.exists():
            vd = json.loads(v.read_text())
            vtxt = f"  verify {'PASS' if vd.get('passed') else 'FAIL'} {fc_core.fmt(vd.get('seconds', 0))} at {time.strftime('%H:%M', time.localtime(v.stat().st_mtime))}"
        halt = proj / "results" / "resume.json"
        htxt = ""
        if halt.exists():
            hd = json.loads(halt.read_text())
            htxt = f"  HALTED {hd['halted_at'][11:16]} payment required at {hd['provider']} ({len(hd.get('remaining', []))} task(s) left) -> fast-coding resume"
        m = fc_tasks.run_marker(proj)
        rtxt = f"  run live since {m['started_at'][11:16]} (pid {m['pid']})" if m and fc_tasks.pid_alive(m.get("pid")) else \
               (f"  run INTERRUPTED (started {m['started_at'][11:16]}) -> fast-coding resume" if m else "")
        summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        on = f" (after {fc_core.project_after(proj)})" if fc_core.project_after(proj) else ""
        out.append(f"project {proj.name}   trunk {trunk}{on}   {len(rows)} tasks: {summary}{rtxt}{vtxt}{htxt}{fc_change.change_line(proj)}")
        if y := fc_tasks.yolo_state(proj):
            out.append(f"  yolo on{' (push)' if y.get('push') else ''} since {y['since']}")
        t = fc_cost.total(fc_cost.rows(proj))
        out.append(f"  cost  {t['input']}in  {t['cache_created']}cc  {t['cache_read']}cr  {t['output']}out  ({t['teammates']} teammates)")
        out.append(f"  {'id':4} {'title':38} {'state':16} {'att':>3} {'time':>8} {'cost':>8}  {'model':14} note")
        for r in rows:
            note = r["note"]
            if note in layers:
                note = f"{note}  layer {layers[note]}"
            out.append(f"  {r['id']:4} {r['title'][:38]:38} {r['state']:16} {r['attempts']:>3} {fc_core.fmt(r['seconds']):>8} {'$' + format(r['cost'], '.4f'):>8}  {r['model'][:14]:14} {note}")
        out.append("")
    return "\n".join(out)

def project_summary(repo, proj):
    """One line per project: name, the feature's title, task counts by state, trunk, last activity."""
    tasks = fc_tasks.load_tasks(proj)
    trunk_head = fc_core.sh(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    counts = {}
    for m in tasks:
        st = task_state(repo, proj, m, trunk_head)["state"].split(" ")[0]
        counts[st] = counts.get(st, 0) + 1
    title = fc_tasks.linear_cache(proj)["feature"].get("title", "") or "(not synced from Linear yet)"
    stamps = [f.stat().st_mtime for f in (proj / "results").glob("*.json")] if (proj / "results").exists() else []
    last = time.strftime("%Y-%m-%d %H:%M", time.localtime(max(stamps))) if stamps else "never run"
    done = counts.get("merged", 0) + counts.get("passed", 0) + counts.get("hand_done", 0) + counts.get("already_green", 0)
    halted = (proj / "results" / "resume.json").exists()
    return {"name": proj.name, "title": title, "tasks": len(tasks), "done": done, "counts": counts, "last": last, "halted": halted,
            "after": fc_core.project_after(proj)}

def file_clashes(tasks):
    """Files two still-open tasks own without one being reachable from the other through `after:`: {file: [task ids]}."""
    deps = {m["id"]: {d.strip() for d in str(m.get("after") or "").split(",") if d.strip()} for m in tasks}
    def ordered(a, b):  # b is reached from a through `after:` links, so one runs before the other
        seen, todo = set(), [a]
        while todo:
            for d in deps.get(todo.pop(), ()):
                if d == b:
                    return True
                if d not in seen:
                    seen.add(d); todo.append(d)
        return False
    shared = {}
    for m in tasks:
        for f in m["files"]:
            shared.setdefault(f, []).append(m["id"])
    clashes = {}
    for f, ids in shared.items():
        loose = [i for i in ids if any(j != i and not ordered(i, j) and not ordered(j, i) for j in ids)]
        if loose:
            clashes[f] = loose
    return clashes

def cmd_tasks(a):
    """The task list as the user should review it before dispatch: id, title, files it owns, what it builds on, its test."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    tasks = fc_tasks.load_tasks(proj, required=True)
    if not tasks:
        sys.exit("no tasks on Linear under this feature carry a fast-coding block")
    print(f"project {proj.name}   {len(tasks)} tasks   stack order (bottom first): {' <- '.join(m['id'] for m in tasks)}")
    print(f"  {'id':4} {'title':40} {'after':10} {'linear':9} files | protected | test")
    for m in tasks:
        after = str(m.get("after") or "").strip() or "-"
        linear = str(m.get("linear") or "").strip() or "-"
        owned = ', '.join(m['nodes']) if m.get('kind') == 'design' else ', '.join(m['files'])
        print(f"  {m['id']:4} {m.get('title', '')[:40]:40} {after:10} {linear:9} {owned or '-'} | {', '.join(m['protected']) or '-'} | {m['test']}")
    # Only tasks still to run can clash; a later wave may legitimately touch a file an already-merged task owned.
    trunk_head = fc_core.sh(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    open_tasks = [m for m in tasks if task_state(repo, proj, m, trunk_head)["state"].split(" ")[0] not in ("merged", "hand_done", "already_green")]
    clashes = file_clashes(open_tasks)
    if clashes:
        print("\n  WARNING two tasks own the same file (they must be one task, or one must be `after:` the other):")
        for f, ids in clashes.items():
            print(f"    {f}: {', '.join(ids)}")
    pages = {}
    for m in (t for t in open_tasks if t.get("kind") == "design"):
        for n in m["nodes"]:
            pages.setdefault(n.split("/")[0], set()).add(m["id"])
    page_clashes = {p: sorted(ids) for p, ids in pages.items() if len(ids) > 1}
    if page_clashes:
        print("\n  WARNING two design tasks own the same page (one page per task):")
        for p, ids in page_clashes.items():
            print(f"    {p}: {', '.join(ids)}")
    big = [(m["id"], why) for m in open_tasks if (why := too_big(m))]
    if big:
        print("\n  WARNING TASK TOO BIG: split it before `run`; a task is one tiny change a fast model finishes in one short turn:")
        for tid, why in big:
            print(f"    {tid}: {why}")
    waves = run_waves(open_tasks)
    if waves:
        print(f"\n  run waves (each wave in parallel): {'  then  '.join(', '.join(w) for w in waves)}")
    if len(open_tasks) >= 3 and len(waves) > len(open_tasks) / 2:
        print(f"\n  WARNING SERIAL CHAIN: {len(open_tasks)} tasks run in {len(waves)} waves, mostly one after another. Keep an `after:` "
              "(blocked-by) only where a task needs another task's code or file; stack order for review comes from ids, not from `after:`.")


def run_waves(tasks):
    """The tasks grouped as `run` dispatches them when every task passes: a task waits only for its `after:` tasks in the list."""
    ids = {m["id"] for m in tasks}
    deps = {m["id"]: {d.strip() for d in str(m.get("after") or "").split(",") if d.strip() in ids} for m in tasks}
    waves, done = [], set()
    while len(done) < len(deps):
        wave = sorted(t for t, d in deps.items() if t not in done and d <= done)
        if not wave:  # a cycle in `after:`; `run` would mark these blocked
            break
        waves.append(wave)
        done |= set(wave)
    return waves

def spec_check(data, root=None):
    """(ok, issue id, level, gaps) for the feature, then every non-canceled issue: a story or a task."""
    issues = [i for i in data["issues"] if (i.get("status") or "").lower() not in fc_tasks.CANCELED]
    tasks = [t for t in (fc_tasks.task_from_issue(i) for i in issues) if t]
    out = []
    desc = (data["feature"].get("description") or "")
    gaps = []
    m = re.search(r"## Not yet specified\n+([^\n]*)", desc)
    if not m or m.group(1).strip() != "None":
        gaps.append(f"`## Not yet specified` holds {m.group(1).strip() if m else 'nothing'}: say `None` when the plan is settled")
    if "### Codebase brief" not in desc:
        gaps.append("no `### Codebase brief` section")
    if "## Plan" not in desc:
        gaps.append("no `## Plan` section")
    by_issue = {t["linear"]: t["id"] for t in tasks}
    tasks = [dict(t, after=",".join(by_issue[b] for b in t["blocked_by"] if b in by_issue)) for t in tasks]
    clashes = file_clashes(tasks)
    if clashes:
        detail = "; ".join(f"{f}: {', '.join(ids)}" for f, ids in clashes.items())
        gaps.append(f"two tasks own the same file (they must be one task, or one must be `after:` the other): {detail}")
    waves = run_waves(tasks)
    if len(tasks) >= 3 and len(waves) > len(tasks) / 2:
        gaps.append(f"serial chain: {len(tasks)} tasks run in {len(waves)} waves, mostly one after another")
    out.append((not gaps, data["feature"]["id"], "feature", gaps))
    story_task = any("parentId" in i for i in data["issues"])
    for i in issues:
        meta = fc_tasks.task_from_issue(i)
        desc = i.get("description") or ""
        bullets = fc_tasks.parse_criteria(desc)
        if meta:
            gaps = []
            if too_big(meta):
                gaps.append(f"too big: {too_big(meta)}")
            if len(bullets) > 5:
                gaps.append(f"{len(bullets)} bullets under `## Acceptance criteria` (max 5)")
            if not meta["files"]:
                gaps.append("empty `files:`")
            if not meta["protected"]:
                gaps.append("empty `protected:`")
            if root:
                for p in meta["protected"]:
                    if not (root / p).exists():
                        gaps.append(f"protected path {p} does not exist")
            out.append((not gaps, i["id"], "task", gaps))
        else:
            gaps = []
            if not bullets:
                gaps.append("no bullet under `## Acceptance criteria`")
            if story_task and not any(j.get("parentId") == i["id"] for j in issues if fc_tasks.task_from_issue(j)):
                gaps.append("no task carries this story as its parentId (cut its code, dependency and toolchain changes into tasks)")
            out.append((not gaps, i["id"], "story", gaps))
    return out

def cmd_spec_check(a):
    """The feature, its stories, and its tasks against the spec: one PASS or FAIL line each, exit 1 on any FAIL."""
    if a.stdin:
        try:
            d = json.loads(sys.stdin.read())
        except ValueError as e:
            sys.exit(f"spec-check: stdin is not JSON ({e}); expected {fc_tasks.SYNC_SHAPE}")
        root = None
    else:
        proj = fc_core.project_dir(a)
        root = fc_herdr.project_worktree(proj)
        fc_tasks.load_tasks(proj, required=True)
        cache = fc_tasks.linear_cache(proj)
        d = {"feature": cache.get("feature") or {},
             "issues": [dict(v, id=k) for k, v in (cache.get("issues") or {}).items()]}
    bad = False
    for ok, ident, level, gaps in spec_check(d, root):
        print(f"{'PASS' if ok else 'FAIL'} {ident} {level}" + (f": {'; '.join(gaps)}" if gaps else ""))
        bad = bad or not ok
    if bad:
        sys.exit(1)

MAX_TASK_FILES, MAX_TASK_BRIEF = 2, 2500  # the size the fast implementers pass first try; bigger ones are where they miss

def too_big(meta):
    """Why a task is too big for one fast turn, or None. Cheap signals only: files it owns and the length of its brief."""
    why = []
    if len(meta["files"]) > MAX_TASK_FILES:
        why.append(f"owns {len(meta['files'])} files (max {MAX_TASK_FILES})")
    if len(meta.get("body") or "") > MAX_TASK_BRIEF:
        why.append(f"brief is {len(meta['body'])} chars (max {MAX_TASK_BRIEF})")
    return "; ".join(why) or None

# ---------- watch ----------
FINAL_STATES = ("passed", "already_green", "failed", "contradiction", "rejected_size", "rejected_docs", "rejected_scope", "rejected_tampered", "payment_required", "interrupted", "hand_done")

def watch_snapshot(repo, proj):
    """Everything a team lead decides on: each task's state, each herdr agent's status, run and verify markers."""
    try:
        tasks = fc_tasks.load_tasks(proj)
    except json.JSONDecodeError:  # a writer that is not ours caught mid-write: one more look, then the real error
        time.sleep(0.5)
        tasks = fc_tasks.load_tasks(proj)
    trunk_head = fc_core.sh(["git", "rev-parse", "HEAD"], repo, check=False).stdout.strip()
    # The marker alone is not enough: a run that crashes leaves it behind, and watch then waits on a dead run forever.
    snap = {"tasks": {}, "agents": {}, "run": fc_tasks.run_alive(proj), "crashed": bool(fc_tasks.run_marker(proj)) and not fc_tasks.run_alive(proj), "verify": None, "halt": None,
            "crew": {f.stem: fc_crew.crew_reports(proj, f.stem) for f in sorted((proj / "results" / "crew").glob("*.status"))}
            if (proj / "results" / "crew").exists() else {}}
    try:
        h = json.loads((proj / "results" / "resume.json").read_text())
        snap["halt"] = [h["halted_at"], h["provider"], len(h.get("remaining") or [])]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    for m in tasks:
        r = task_state(repo, proj, m, trunk_head)
        snap["tasks"][m["id"]] = {"state": r["state"], "attempts": r["attempts"], "cost": r["cost"], "note": r["note"], "linear": str(m.get("linear") or ""), "title": r["title"]}
    for ag in (fc_herdr.herdr("agent", "list") or {}).get("agents", []):
        n = ag.get("name") or ""
        if n.startswith(fc_herdr.agent_name(proj.name, "")[:-1]):
            snap["agents"][n] = ag.get("agent_status")
    pis = [c for f in sorted((proj / "results" / "crew").glob("*.json"))
           if "skill" in (c := json.loads(f.read_text())) and c.get("agent", c["name"]) in snap["agents"]]
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

STALL_SECONDS = 240  # verify.json `stall_seconds` or `watch --stall` change it

def watch_mem(proj, key):
    """What one role's watcher (key: FAST_CODING_ROLE, else `manager`) last reported and which stalls it fired, in results/watch-<role>.json."""
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
    if last.get(orch, ("",))[0] == "done" or any(st == "needs-user" for st, _ in last.values()):
        return []  # finished, or waiting on the product owner: silence is expected
    pending = [t for t, v in snap["tasks"].items() if v["state"] in ("pending", "running", "interrupted")]
    on_hold = [t for t, v in snap["tasks"].items() if v["state"] == "held"]  # waiting on a change of course: still work to move
    working = [n for n, (st, _) in last.items() if st == "working" and n != orch]
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
    lt, what = snap.get("last") or (0, "")
    if (pending or on_hold or working or snap["run"]) and lt and now_s - lt >= limit:
        fire(f"quiet:{lt}", f"quiet{who} nothing moved for {fc_core.fmt(now_s - lt)}, last: {what} at {hm(lt)}")
    tests = {n: v for n, v in last.items() if re.search(r"-tests-\d+$", n)}
    if tests and all(st == "done" for st, _ in tests.values()) and not snap["run"] and pending \
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
                  + ("  CRASHED: the run process died without finishing; read results/run.log, fix the cause, then `fast-coding resume`" if after.get("crashed") else ""))
    if after.get("halt") and after["halt"] != before.get("halt"):
        at_, provider, left = after["halt"]
        ev.append(f"event halt=payment provider={provider} remaining={left} at={at_!r}  (the product owner's stop: tell them, wait for "
                  f"their word, then `fast-coding resume`)")
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
    """Under yolo, a question line tells the engineering manager it answers it itself."""
    if not fc_tasks.yolo_state(proj):
        return events
    return [e + YOLO_HINT if re.match(r"event crew=\S+ state=needs-user ", e) else e for e in events]

def watch_filter(events, slug, sources, direct=()):
    """`--from` names the teammates whose reports wake you (the engineering manager watches only its team lead); without it you get
    everything except the team lead's own reports, which go up to the engineering manager. `direct` names the teammates that report to
    this watcher (crew_reporting_to): a planner or designer the engineering manager started itself passes whatever `--from` says, so
    its needs-user and blocked reach the product owner (manager_attention) while the `--from orchestrator` watch runs."""
    if sources:  # a tool-bug from any teammate wakes the engineering manager too: it owns fixing the tool; a stall is its to supervise
        return [e for e in events if " state=tool-bug " in e or " state=fallback " in e or e.startswith("event stall=")
                or any(f"crew={n} " in e or f"agent={n} " in e for n in (*sources, *direct))]
    me = fc_herdr.agent_name(slug, "orchestrator")
    return [e for e in events if f"crew={me} " not in e and not e.startswith(f"event stall=idle agent={me} ")]  # idle: it waits on this watch

WATCH_INTERVAL = 2.0

def cmd_watch(a, rewake=False):
    """Sleep on the project until something a team lead must act on happens, print it, exit. Zero tokens while waiting:
    run it in the background and let its exit wake you. `--now` prints the current state as events and exits.
    Each role's watcher (FAST_CODING_ROLE, else manager; --from only filters what is printed) remembers what it last
    reported, so a watch started later still reports what happened while none ran. `rewake` is the Stop hook's mode: the event goes to stderr with exit 2, which wakes the session."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    sources = [fc_herdr.agent_name(proj.name, x.strip()) if not x.strip().startswith(fc_herdr.agent_name(proj.name, "")) else x.strip()
               for x in (a.from_ or "").split(",") if x.strip()]
    key = os.environ.get("FAST_CODING_ROLE") or "manager"
    direct = lambda: fc_crew.crew_reporting_to(proj, key) if key == "manager" else ()  # the engineering manager's own teammates pass whatever --from says
    if a.now:
        cur = watch_snapshot(repo, proj)
        empty = {"tasks": {}, "agents": {}, "run": cur["run"] or cur.get("crashed"), "verify": None, "halt": None,
                 "crew": {n: r[:-1] for n, r in cur["crew"].items()}}  # each teammate's latest report, once
        lines = yolo_mark(proj, watch_filter(watch_events(empty, cur), proj.name, sources, direct()))
        if y := fc_tasks.yolo_state(proj):
            lines.insert(0, f"event yolo=on push={'yes' if y.get('push') else 'no'} since={y['since']!r} words={y.get('words', '')!r}")
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
        while True:
            time.sleep(a.interval)
            if rewake and os.getppid() != parent:
                return  # the session that parked this hook is gone
            after = watch_snapshot(repo, proj)
            ev = yolo_mark(proj, watch_filter(watch_events(before, after) + watch_stalls(proj, after, limit, key=key), proj.name, sources, direct()))
            if ev:
                fc_crew.manager_attention(proj, ev)
                if rewake:
                    emit("fast-coding watch woke you. When this turn ends the Stop hook parks the next watch; do not start one yourself.")
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
                working = [n for n, r in after["crew"].items() if r and r[-1]["state"] == "working"]
                print(f"[{fc_core.now()}] event timeout  nothing changed in {fc_core.fmt(a.timeout)}: pending tasks {pending}, teammates working "
                      f"{','.join(working) or 'none'}, run {'live' if after['run'] else 'not live'}, verify "
                      f"{'PASS' if after['verify'] and after['verify'][1] else 'FAIL' if after['verify'] else 'not run'}")
                sys.exit(2)

def cmd_rewake(a):
    """Claude Code Stop hook (the plugin's hooks.json, asyncRewake): when a team lead's turn ends, park a watch whose event
    wakes the idle session. Its herdr tab carries the role, project, and worktree. Every other session returns at once,
    a headless one (`claude -p`, which Claude Code marks CLAUDE_CODE_ENTRYPOINT=sdk-*) too. A wake names skill files changed since the last one."""
    project = os.environ.get("FAST_CODING_PROJECT")
    if os.environ.get("FAST_CODING_ROLE") != "orchestrator" or not project or os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    try:
        session = re.sub(r"[^\w-]", "", json.load(sys.stdin).get("session_id") or "")
    except Exception:
        session = ""
    cmd_watch(argparse.Namespace(repo=os.environ.get("FAST_CODING_REPO") or ".", project=project, now=False, from_=None,
                                 timeout=0, stall=None, interval=WATCH_INTERVAL, session=session), rewake=True)

def cmd_reenter(a):
    """Claude Code SessionStart hook (matcher compact): after a compaction the session continues by re-entering through 0r, not from scratch.
    Its herdr tab carries the role, project, and worktree. Every other session returns at once, a headless one (`claude -p`,
    which Claude Code marks CLAUDE_CODE_ENTRYPOINT=sdk-*) too."""
    project, role = os.environ.get("FAST_CODING_PROJECT"), os.environ.get("FAST_CODING_ROLE")
    if not role or not project or os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return
    proj = fc_core.project_dir(argparse.Namespace(repo=os.environ.get("FAST_CODING_REPO") or ".", project=project))
    print("Your context was just compacted; the session continues by re-entering through 0r, not from scratch.")
    print(f"Re-read your brief file {fc_crew.crew_dir(proj) / f'{fc_herdr.agent_name(project, role)}.brief.md'} now.")
    print(f"Run `fast-coding status --repo {os.environ.get('FAST_CODING_REPO') or '.'} --project {project}` and "
          f"`fast-coding watch --repo {os.environ.get('FAST_CODING_REPO') or '.'} --project {project} --now` to see the board.")
    print("Re-read the feature's Decisions so far and Plan on Linear before acting.")

def cmd_projects(a):
    """Every project (feature) across this repository's worktrees with its task progress; `status --project <name>` drills in."""
    repo = Path(a.repo).resolve()
    projects = fc_core.all_projects(repo)
    if not projects:
        sys.exit("no fast-coding projects in this repository; `fast-coding init --project <name>` creates one")
    print(f"{'project':24} {'done':>9}  {'last activity':17} {'worktree':34} title / states")
    for name, (wt, proj) in projects.items():
        ps = project_summary(wt, proj)
        states = ", ".join(f"{n} {k}" for k, n in sorted(ps["counts"].items(), key=lambda kv: -kv[1]))
        flag = "  HALTED (payment) -> fast-coding resume" if ps["halted"] else ""
        after = f"  (after {ps['after']})" if ps["after"] else ""
        print(f"{ps['name']:24} {ps['done']:>4}/{ps['tasks']:<4}  {ps['last']:17} {str(wt)[-34:]:34} {ps['title'] or '-'}  [{states}]{after}{flag}")

def cmd_cost(a):
    """Tokens per teammate session and per run provider; --json prints the rows and their total."""
    proj = fc_core.project_dir(a)
    rows = fc_cost.rows(proj)
    if a.json:
        print(json.dumps({"rows": rows, "total": fc_cost.total(rows)}, indent=2))
    else:
        print(fc_cost.render(rows))

def cmd_status(a):
    """Every project across the repository's worktrees with every task's state. --watch redraws every 2 s while runs write progress."""
    repo = Path(a.repo).resolve()
    projects = fc_core.all_projects(repo)
    if a.project:
        projects = {a.project: projects[a.project]} if a.project in projects else {}
    if not projects:
        sys.exit("no fast-coding projects in this repository")
    while True:
        text = "\n".join(render_status(wt, [proj]) for wt, proj in projects.values())
        if a.watch:
            sys.stdout.write("\x1b[2J\x1b[H" + f"fast-coding status  {fc_core.now()}  (ctrl-c to stop)\n\n" + text)
            sys.stdout.flush()
            try:
                time.sleep(2)
            except KeyboardInterrupt:
                print()
                return
        else:
            print(text, end="")
            return

def cmd_done(a):
    """Record that the team lead finished tasks by hand (status hand_done) so `status` tells the truth. Requires a reason."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    ids = [x.strip() for x in a.only.split(",") if x.strip()]
    (proj / "results").mkdir(exist_ok=True)
    for tid in ids:
        meta = next((m for m in fc_tasks.load_tasks(proj) if m["id"] == tid), None)
        if not meta:
            print(f"{tid}: no such task (run `fast-coding sync` if it is new on Linear)")
            continue
        res = proj / "results" / f"{tid}.json"
        prev = json.loads(res.read_text()) if res.exists() else {}
        prev.update({"id": tid, "title": meta.get("title"), "status": "hand_done", "note": a.note, "model": "orchestrator",
                     "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"), "attempts": prev.get("attempts", 0), "seconds": prev.get("seconds", 0.0),
                     "cost": prev.get("cost", 0.0), "branch": prev.get("branch", f"fast/{proj.name}/{tid}")})
        fc_core.atomic_write(res, json.dumps(prev, indent=2))
        print(f"{tid} hand_done  {meta.get('title', '')}  ({a.note})")

def cmd_top(a):
    """Check out the project's stack top in the CLI worktree and print its path, for manual testing of the whole feature
    (nothing is merged, so the user's checkout never contains it). `--detach` returns the worktree to the trunk."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    trunk = fc_core.current_branch(repo)
    wt = fc_worktree.stack_worktree(repo, proj, trunk)
    if a.detach:
        fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
        print(f"{wt} detached at {trunk}")
        return
    chain = fc_layers.linearize(repo, proj, trunk, wt)
    if not chain:
        sys.exit("no unmerged layers; the trunk already is the top")
    fc_core.sh(["git", "checkout", "-q", "--detach", chain[-1]], wt)
    fc_worktree.ready_checkout(repo, wt, install=fc_core.project_config(proj).get("install"))
    print(f"stack top {chain[-1]} ({len(chain)} layers on {trunk}) checked out at:\n{wt}")

def cmd_resume(a):
    """Continue a run or verify that stopped on PAYMENT REQUIRED, from the saved state in results/resume.json."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    path = proj / "results" / "resume.json"
    if not path.exists():
        m = fc_tasks.run_marker(proj)
        if not m or fc_tasks.pid_alive(m.get("pid")):
            sys.exit("nothing to resume: no payment halt and no interrupted run recorded for this project" + (" (a run is live)" if m else ""))
        done = {t["id"] for t in fc_tasks.load_tasks(proj, required=True) if fc_tasks.task_finished(proj, t)}
        state = {"command": "run", "remaining": [t for t in m["tasks"] if t not in done], "args": m["args"], "halted_at": m["started_at"], "provider": "interrupted run"}
        (proj / "results" / "run.json").unlink(missing_ok=True)
    else:
        state = json.loads(path.read_text())
    fc_core.say(f"resume {state['command']}  halted {state['halted_at']} at {state['provider']}")
    ns = argparse.Namespace(repo=str(repo), project=proj.name, **state["args"])
    if state["command"] == "run":
        if fc_core.sh(["git", "status", "--porcelain"], repo).stdout.strip():
            sys.exit("repo has uncommitted changes; commit first")
        tasks = [m for m in fc_tasks.load_tasks(proj, required=True) if m["id"] in set(state["remaining"]) and not fc_tasks.task_finished(proj, m)]
        if not tasks:
            path.unlink(missing_ok=True)
            sys.exit("nothing left to run; cleared the halt")
        fc_core.say(f"resume {len(tasks)} task(s): {', '.join(state['remaining'])}")
        run_tasks(repo, proj, tasks, ns)
    else:
        ns.fix, ns.skip_e2e, ns.skip_review = state["args"]["fix"], state["args"]["skip_e2e"], state["args"]["skip_review"]
        fc_verify.cmd_verify(ns)

# ---------- bench ----------

def pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

def cmd_bench(a):
    """Frozen task set x models. Each task is reset to red in its worktree, then implemented from scratch by each model."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    only = set(a.only.split(",")) if a.only else None
    if fc_core.sh(["git", "status", "--porcelain"], repo).stdout.strip():
        sys.exit("repo has uncommitted changes; commit first")
    tasks = [m for m in fc_tasks.load_tasks(proj, required=True) if not only or m["id"] in only]
    if not tasks:
        sys.exit("no tasks on Linear under this feature carry a fast-coding block")
    models = a.models.split(",")
    t0 = time.time()
    fc_core.say(f"bench start project={proj.name} tasks={len(tasks)} models={models} runs={a.runs} attempts={a.attempts}")
    rows, raw = [], []
    for model in models:
        before_cost = fc_core.LEDGER.total()
        jobs = [(t, r) for t in tasks for r in range(a.runs)]
        with ThreadPoolExecutor(max_workers=a.parallel) as ex:
            results = list(ex.map(lambda j: fc_implement.run_task(repo, proj, j[0], a.attempts, model=model, reset_files=True,
                                                     tag=f"-bench-{re.sub(r'[^a-z0-9]+', '-', model.lower())}-r{j[1]}"), jobs))
        raw.extend({**r, "bench_model": model} for r in results)
        passed = [r for r in results if r["status"] == "passed"]
        times = [r["seconds"] for r in results]
        rows.append({"model": model, "tasks_x_runs": len(results), "pass_rate": round(len(passed) / len(results), 3),
                     "attempts_mean": round(sum(r["attempts"] for r in results) / len(results), 2),
                     "attempts_max": max(r["attempts"] for r in results),
                     "p50_s": round(pct(times, 0.5), 1), "p95_s": round(pct(times, 0.95), 1),
                     "cost_per_task": round((fc_core.LEDGER.total() - before_cost) / len(results), 5)})
        for r in results:  # keep branches for inspection, drop the clones
            import shutil
            shutil.rmtree(r["worktree"], ignore_errors=True)
    print()
    print(f"{'model':28} {'n':>3} {'pass':>6} {'att.mean':>8} {'att.max':>7} {'p50':>8} {'p95':>8} {'$/task':>9}")
    for r in rows:
        print(f"{r['model']:28} {r['tasks_x_runs']:>3} {r['pass_rate']:>6.0%} {r['attempts_mean']:>8} {r['attempts_max']:>7} "
              f"{fc_core.fmt(r['p50_s']):>8} {fc_core.fmt(r['p95_s']):>8} {'$' + format(r['cost_per_task'], '.4f'):>9}")
    fc_core.say(f"bench done  wall {fc_core.fmt(time.time() - t0)}")
    fc_core.say(fc_core.LEDGER.line())
    out = proj / "results" / f"bench-{time.strftime('%Y%m%d-%H%M%S')}.json"
    fc_core.atomic_write(out, json.dumps({"summary": rows, "runs": raw, "cost": fc_core.LEDGER.snapshot(), "seconds": round(time.time() - t0, 1)}, indent=2))
    print(f"saved {out}")

DETACHED = ("run", "verify", "resume")  # the long commands: a closed tab or a crashed session must not end them

def follow(cmd, log):
    """Run cmd detached, writing to log, and stream the log here until it exits; return its exit code. The work is double
    forked into its own session under launchd: a closed herdr tab makes Claude Code kill its background task's whole process
    tree, and that must end only this follower. Ctrl-C here stops the work too."""
    log, done = Path(log), Path(f"{log}.exit")
    log.write_bytes(b"")
    done.unlink(missing_ok=True)
    env = os.environ | {"FAST_CODING_DETACHED": "1", "PYTHONUNBUFFERED": "1"}
    group = os.fork()
    if group == 0:
        try:
            os.setsid()
            if os.fork() == 0:
                out = os.open(log, os.O_WRONLY | os.O_APPEND)
                os.dup2(out, 1)
                os.dup2(out, 2)
                os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
                os.execve("/bin/sh", ["/bin/sh", "-c", '"$@"; echo $? > "$0"', str(done), *cmd], env)
        finally:
            os._exit(0)
    os.waitpid(group, 0)  # the middle process exits at once; its pid stays the work's process group
    def ended():
        try:
            os.killpg(group, 0)
            return done.exists() and done.read_text().strip() != ""
        except (ProcessLookupError, PermissionError):  # macOS answers EPERM for a group left with only its zombie leader
            return True
    with open(log, "rb") as f:
        while True:
            try:
                finished = ended()  # before the read: everything the work wrote is in the log once it has ended
                chunk = f.read()
                if chunk:
                    sys.stdout.write(chunk.decode(errors="replace"))
                    sys.stdout.flush()
                if finished:
                    code = done.read_text().strip() if done.exists() else ""
                    return int(code) if code else 1  # no code: it was killed before it could write one
                if not chunk:
                    time.sleep(0.2)
            except KeyboardInterrupt:
                os.killpg(group, signal.SIGINT)  # a person stopping it means the work, not just this view of it

def detach(a):
    proj = fc_core.project_dir(argparse.Namespace(repo=a.repo, project=a.project))
    log = proj / "results" / f"{a.cmd}.log"
    log.parent.mkdir(exist_ok=True)
    print(f"[{fc_core.now()}] {a.cmd} runs in its own session; it outlives this terminal. Log: {log}", flush=True)
    sys.exit(follow([sys.executable, *sys.argv], log))

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "timed":
        return fc_implement.cmd_timed(sys.argv[2:])
    ap = argparse.ArgumentParser(prog="fast-coding", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_ in (("doctor", fc_init.cmd_doctor, "check every tool and skill file fast-coding depends on; one MISSING line each, exit 1 when a required one is absent"),
                            ("init", fc_init.cmd_init, "create .fast-coding/<project>/ skeleton"),
                            ("run", cmd_run, "dispatch tasks to parallel implementers (pi by default)"),
                            ("verify", fc_verify.cmd_verify, "local no-mistakes-style pipeline: checks, confirmed fast-model review, jev e2e, auto-fix loop"),
                            ("bench", cmd_bench, "frozen task set x models: pass rate, attempts, p50/p95 time, cost per task"),
                            ("resume", cmd_resume, "continue a run or verify that stopped on PAYMENT REQUIRED"),
                            ("done", cmd_done, "record tasks the team lead finished by hand: --only ids --note why"),
                            ("sync", fc_linear.cmd_sync, "store the feature and its tasks: --from-linear reads them from Linear, else JSON on stdin"),
                            ("tasks", cmd_tasks, "the task list to review before dispatch: ids, titles, files, after, tests; warns on shared files"),
                            ("spec-check", cmd_spec_check, "check the synced feature, its stories, and its tasks against the spec; --stdin reads the sync JSON"),
                            ("projects", cmd_projects, "list every project (feature) with its task progress"),
                            ("cost", cmd_cost, "tokens per teammate session and per run provider; --json"),
                            ("status", cmd_status, "projects and every task's state, attempts, time, cost, stack layer; --watch redraws live"),
                            ("watch", cmd_watch, "block until a task finishes, an agent blocks, a run ends, or verify finishes; print one event line and exit"),
                            ("top", cmd_top, "check out the stack top in the CLI worktree for manual testing; --detach to release it"),
                            ("stack", fc_layers.cmd_stack, "cut unmerged task branches into review layers (verify.json review_layer_lines, default 300) as one gh stack on the real base; --submit pushes and opens one draft PR per layer"),
                            ("clean", fc_init.cmd_clean, "the post-merge step: remove task clones and merged branches, move the tasks proven merged to Done in Linear and roll their story and the feature up, and remove a merged project's worktree and branch"),
                            ("groundwork", fc_briefs.cmd_groundwork, "print the groundwork teammate's brief; --extra adds the project's notes"),
                            ("explore", fc_briefs.cmd_explore, "print the explore teammate's brief (a fast graft-only map of an existing repo); --extra adds notes"),
                            ("graft", fc_init.cmd_graft, "set graft up in the project's worktree again: wire it for Claude Code and build the graph"),
                            ("wayfinder", fc_briefs.cmd_wayfinder, "print the wayfinder teammate's brief (questions on one Lavish page); --extra adds the project's notes"),
                            ("planner", fc_briefs.cmd_planner, "print the planner teammate's brief; --issue is the ticket (default: the project's feature); --extra adds the project's notes"),
                            ("testcrews", fc_briefs.cmd_testcrews, "start one test-writing teammate per task in parallel from the groundwork contract"),
                            ("designer", fc_figma.cmd_designer, "print the designer teammate's brief; --figma stores the file key, --extra adds notes"),
                            ("designcrews", fc_figma.cmd_designcrews, "start one design-NNN builder per open design task"),
                            ("triage", cmd_triage, "fast-model look at each passed task: clean or flag (run does this at its end)"),
                            ("reflect", fc_change.cmd_reflect, "screen the settled decisions against evidence with Jev: HOLDS | BROKEN | UNCLEAR per line"),
                            ("hold", fc_change.cmd_hold, "hold tasks back from dispatch while the plan changes: --only ids --reason why; --release ids|all"),
                            ("yolo", cmd_yolo, "the product owner is away: [--push] [words] enters, `decided \"<q>: <a>\"` logs an answer taken, `off` prints the digest and archives"),
                            ("change", fc_change.cmd_change, "start | done | undo a change of course: what changed in Linear and why, undoable"),
                            ("crew", fc_crew.cmd_crew, "start | list | focus | stop teammates, the Claude sessions in the project's herdr space (the team lead, the wayfinder, helpers)"),
                            ("report", fc_crew.cmd_report, "a teammate session reports up: working | needs-user | blocked | done, with one line"),
                            ("models", fc_models.cmd_models, "--probe: clear the day's cached model probes and probe the crew models again"),
                            ("frame0", fc_frame0.cmd_frame0, "up | save | down the project's own Frame0 (wireframes in .fast-coding/<project>/design.f0)"),
                            ("figma", fc_figma.cmd_figma, "check | tree | judge: store the target Figma file key and prove Framelink reads it; save a task's node tree; judge it with Jev"),
                            ("teardown", fc_crew.cmd_teardown, "close the project's implementer, verify, and finished teammate tabs (the team lead's done does this)"),
                            ("guard", fc_crew.cmd_guard, "Claude Code PreToolUse hook: the team lead writes no code (reads the hook event on stdin)"),
                            ("rewake", cmd_rewake, "Claude Code Stop hook: park a watch after each team lead turn; its event wakes the session"),
                            ("reenter", cmd_reenter, "Claude Code SessionStart hook: after a compaction, point the teammate back at its brief, the board, and Linear"),
                            ("skillcheck", fc_crew.cmd_skillcheck, "Claude Code UserPromptSubmit and PostToolUse(Skill) hook: tell a fast-coding session the skill changed since it read it"),
                            ("workspace", fc_config.cmd_workspace, f"show workspaces, or switch: `workspace personal` (config: {fc_config.CONFIG_PATH})")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--repo", default=".")
        s.add_argument("--project", required=(name == "init"))
        s.set_defaults(fn=fn)
        if name == "init":
            s.add_argument("--here", action="store_true", help="create the project in this checkout instead of its own worktree")
            s.add_argument("--branch", help="name the project's branch (default fast-coding/<project>); on an existing project, renames its branch to this")
            s.add_argument("--after", metavar="PROJECT", help="branch from another project's branch (fast-coding/<PROJECT> unless it chose one): a feature that needs that feature's code")
        if name == "sync":
            s.add_argument("--from-linear", action="store_true", help="read the feature, stories, and tasks from Linear with the workspace key (read-only) instead of stdin")
        if name == "cost":
            s.add_argument("--json", action="store_true", help="print the rows and their total as JSON")
        if name == "spec-check":
            s.add_argument("--stdin", action="store_true", help="read the sync JSON from stdin instead of the project's cache")
        if name == "run":
            s.add_argument("--only", help="comma-separated task ids")
            s.add_argument("--attempts", type=int, default=3)
            s.add_argument("--parallel", type=int, default=3)
            s.add_argument("--trunk", default=None, help="trunk branch the stack targets (default: the branch you are on)")
            s.add_argument("--no-stack", action="store_true", help="do not register passed branches with gh stack")
            s.add_argument("--redo", action="store_true", help="rebuild tasks whose passed branch still exists (otherwise they are kept)")
        if name == "done":
            s.add_argument("--only", required=True, help="comma-separated task ids")
            s.add_argument("--note", required=True, help="why it was done by hand, e.g. 'provider out of credit'")
        if name == "top":
            s.add_argument("--detach", action="store_true")
        if name == "watch":
            s.add_argument("--now", action="store_true", help="print the current state as events and exit (session-start reconcile)")
            s.add_argument("--timeout", type=float, default=600, help="seconds to wait before exiting 2 with a timeout event and a state summary (0 = forever)")
            s.add_argument("--stall", type=float, default=None, help=f"seconds of silence with work pending before a stall event (default verify.json stall_seconds, else {STALL_SECONDS})")
            s.add_argument("--interval", type=float, default=WATCH_INTERVAL)
            s.add_argument("--from", dest="from_", help="only these teammates wake you (roles or agent names, comma-separated); the engineering manager passes orchestrator, its team lead's role")
        if name == "status":
            s.add_argument("--watch", action="store_true", help="redraw every 2 seconds")
        if name == "stack":
            s.add_argument("--trunk", default=None, help="default: the branch you are on")
            s.add_argument("--submit", action="store_true", help="also `gh stack submit --auto`: pushes the layers and opens a draft PR per layer as a GitHub stack")
        if name == "bench":
            s.add_argument("--models", default="pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast,pi:openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras,claude",
                           help="comma-separated model ids: OpenCode ids, 'pi:<provider/model>' for the pi harness, 'claude' = Claude Code one-shot")
            s.add_argument("--only", help="comma-separated task ids")
            s.add_argument("--runs", type=int, default=1, help="repeats per task per model")
            s.add_argument("--attempts", type=int, default=3)
            s.add_argument("--parallel", type=int, default=4)
        if name in ("groundwork", "wayfinder", "explore", "planner", "designer"):
            s.add_argument("--extra", help="project-specific notes appended to the brief; `-` reads them from stdin")
        if name == "planner":
            s.add_argument("--issue", help="the ticket to plan (default: the project's feature)")
        if name == "designer":
            s.add_argument("--figma", help="the target Figma file's url or key: stored in linear.json before the brief prints")
        if name == "designcrews":
            s.add_argument("--only", help="comma-separated task ids")
            s.add_argument("--print", dest="print_", action="store_true", help="print the briefs instead of starting builders")
            s.add_argument("--max", type=int, help="most builders to start at once (default: design_concurrency in verify.json, else 3)")
        if name == "wayfinder":
            s.add_argument("--change", help="an open change of course, e.g. C2: its own page, asking only what the evidence questions")
        if name == "testcrews":
            s.add_argument("--contract", help="default: .fast-coding/<project>/results/contract.md")
            s.add_argument("--only", help="comma-separated task ids")
            s.add_argument("--print", dest="print_", action="store_true", help="print the briefs instead of starting teammates")
            s.add_argument("--budget", type=int, help="test lines per task (default 60; a task's test_lines: wins)")
            s.add_argument("--collect", action="store_true", help="cherry-pick every test-writing teammate's commits onto the project branch in task order")
        if name == "triage":
            s.add_argument("--only", help="comma-separated task ids (default: every passed task)")
        if name == "reflect":
            s.add_argument("--evidence", help="what was found: the product owner's words, a report, a rejection reason; `-` reads stdin")
            s.add_argument("--dismiss", help="why the evidence so far needs no change of course (a false alarm, a task-sized fix): later screens skip it")
            s.add_argument("--against", action="append", help="a Linear line the evidence contradicts, quoted; repeatable")
        if name == "hold":
            s.add_argument("--only", help="comma-separated task ids to hold")
            s.add_argument("--reason", help="one line: why they wait")
            s.add_argument("--release", help="comma-separated task ids, or all")
        if name == "yolo":
            s.add_argument("--push", action="store_true", help="permission, given in advance, to submit the project's verified stack")
            s.add_argument("words", nargs="*", help="what pre-answers questions, verbatim; or `decided <q>: <a>`; or `off`")
        if name == "change":
            s.add_argument("action", choices=("start", "done", "undo"))
            s.add_argument("id", nargs="?", help="undo: the change to undo, e.g. C2")
            s.add_argument("--why", help="start: one line, the reason for the change")
        if name == "crew":
            s.add_argument("action", choices=("start", "list", "focus", "stop"))
            s.add_argument("--role", help="orchestrator (the team lead), wayfinder, or a helper's job; the agent is named <slug>-<role>")
            s.add_argument("--title", help="tab label, e.g. the ticket's title")
            s.add_argument("--brief", help="what to do; `-` reads it from stdin")
            s.add_argument("--force", action="store_true", help="stop: close it even though it has not reported done")
            s.add_argument("--cwd", help="start: run the session in this directory instead of the project worktree (a toolsmith works in the fast-coding repo)")
            s.add_argument("--frame0", action="store_true", help="start: give the session the project's Frame0 tools")
            s.add_argument("--model", help="start: claude:<model-id>, or a name under models.crew (e.g. small); default models.crew[<role>], then models.crew.default")
        if name == "models":
            s.add_argument("--probe", action="store_true")
        if name == "frame0":
            s.add_argument("action", choices=("up", "save", "down"))
        if name == "figma":
            s.add_argument("action", choices=("check", "tree", "judge"))
            s.add_argument("--figma", help="check: the target Figma file's url or key, stored in linear.json")
            s.add_argument("--only", help="judge: comma-separated design task ids; tree: one id")
            s.add_argument("--node", help="tree: comma-separated node ids to fetch through Framelink")
            s.add_argument("--depth", type=int, help="tree: how deep Framelink walks (default: all)")
            s.add_argument("--bindings", help="tree: a file (or - for stdin) with what the write script returned, appended to the tree")
        if name == "report":
            s.add_argument("--as", dest="as_", required=True, help="your agent name, <slug>-<role>")
            s.add_argument("state", help="working | needs-user | blocked | done | tool-bug | contradiction")
            s.add_argument("message", nargs="+")
        if name == "workspace":
            s.add_argument("name", nargs="?", help="workspace to make active, or add | key | remove")
            s.add_argument("target", nargs="?", help="the workspace add, key, or remove acts on")
            s.add_argument("--linear", action="store_true", help="key: store the workspace's Linear API key (stdin) instead of OpenRouter's")
        if name == "clean":
            s.add_argument("--force", action="store_true", help="with --project: clean it although teammates are still working")
            s.add_argument("--delete-unmerged", action="store_true", help="also delete task branches not merged into HEAD (layers a reviewer has not merged yet)")
        if name == "verify":
            s.add_argument("--skip-e2e", action="store_true")
            s.add_argument("--skip-review", action="store_true")
            s.add_argument("--fix", type=int, default=2, help="auto-fix rounds with the fast model before escalating (0 = report only)")
    a, extra = ap.parse_known_args()
    if extra and a.cmd == "yolo":
        a.words += extra  # `yolo decided --project x "<q>: <a>"`: words after the flags are still words
    elif extra:
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    if a.cmd in DETACHED and not os.environ.get("FAST_CODING_DETACHED"):
        return detach(a)
    if a.fn not in (fc_config.cmd_workspace, fc_crew.cmd_guard, cmd_rewake, fc_crew.cmd_skillcheck):  # the hooks run in every session: no config, no output
        ws = fc_config.apply_config()  # "default" when no workspace is chosen
        if a.cmd in ("run", "verify", "bench", "resume"):  # the commands that spend; `watch` output stays one line
            fc_core.say(f"workspace {ws}")
    try:
        a.fn(a)
    except KeyboardInterrupt:
        print(f"\n[{fc_core.now()}] {a.cmd} stopped by Ctrl-C" + ("; `fast-coding resume` continues it" if a.cmd in ("run", "resume") else ""), file=sys.stderr)
        sys.exit(130)

if __name__ == "__main__":
    main()
