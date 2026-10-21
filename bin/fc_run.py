import argparse, json, os, signal, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import fc_core, fc_config, fc_tasks, fc_linear, fc_claude, fc_models, fc_proc, fc_herdr, fc_pi, fc_worktree, fc_layers, fc_stack, fc_change, fc_crew, fc_briefs, fc_implement, fc_init, fc_verify


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
    layers = list(fc_worktree.task_branches(repo, proj))
    def one(tid):
        m, branch = metas.get(tid) or {}, fc_worktree.task_branch(repo, proj, tid)
        try:
            # A stacked task's own change starts at the nearest layer below it, not at the trunk under the whole chain.
            below = [b for b in layers if b != branch
                     and fc_core.sh(["git", "merge-base", "--is-ancestor", b, branch], repo, check=False).returncode == 0]
            base = max([fc_core.sh(["git", "merge-base", trunk, branch], repo).stdout.strip(), *below],
                       key=lambda c: int(fc_core.sh(["git", "rev-list", "--count", f"{trunk}..{c}"], repo).stdout))
            diff = fc_core.sh(["git", "diff", base, branch, "--", *(m.get("files") or [])], repo, check=False).stdout
            shape = '{"verdict": "clean" | "flag", "reason": str}'
            v = fc_models.fast_object(env, "You triage one finished coding task for a senior reviewer. " + TRIAGE_BAR +
                          f" Return JSON {shape}; a flag reason is one line quoting the code.",
                          f"TASK BRIEF:\n{(m.get('body') or '')[:6000]}\n\nFILES IT MAY CHANGE: {', '.join(m.get('files') or [])}\n\n"
                          f"DIFF:\n{diff[:40000]}", shape, "verdict", max_tokens=300, timeout=30)
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

RUN_PARALLEL = 3  # tasks at once when neither --parallel nor the config's `parallel` says

def require_committed(repo, stack=True):
    """The preflight of a run (fc_init.start_checks), every problem at once before anything is cloned. Every task clone starts
    from the project branch's last commit, so its tests must be committed: it stops on anything dirty, naming it (the agent wiring
    a session hook rewrites and the tools' own directories are left out: fc_worktree.dirty_paths), on a key its service rejects,
    and with `stack` on a gh that is not logged in. A Mac on battery, a loaded machine or a crash-looping container only warns."""
    fc_init.start_checks(repo, stack, hint="commit the tests first so worktrees include them")

def cmd_run(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    only = set(a.only.split(",")) if a.only else None
    require_committed(repo, not a.no_stack)
    tasks = [m for m in fc_tasks.code_tasks(fc_tasks.load_tasks(proj, required=True)) if not only or m["id"] in only]
    if not tasks:
        sys.exit("no tasks on Linear under this feature carry a compose block" + (f" with ids {a.only}" if only else ""))
    redo = bool(getattr(a, "redo", False))
    a.parallel = getattr(a, "parallel", None) or fc_config.PARALLEL or RUN_PARALLEL
    kept = {m["id"]: fc_tasks.task_finished(proj, m, redo) for m in tasks}
    for tid, why in kept.items():
        if why:
            fc_core.say(f"{tid} keep    {why}" + ("; pass --redo to rebuild it" if why.startswith("its result") else ""))
    tasks = [m for m in tasks if not kept[m["id"]]]
    if not tasks:
        return fc_core.say("nothing to run: every task is finished")
    if redo:
        os.environ["COMPOSE_REDO"] = "1"
    # Test-writing teammates write on their own branches; their tests must be on the project branch before any implementer starts.
    pending = [m["id"] for m in tasks if fc_briefs.test_open(proj, m["id"])]
    if pending:
        busy = [t for t in pending if (fc_crew.crew_reports(proj, fc_herdr.agent_name(proj.name, f"tests-{t}")) or [{}])[-1].get("state") != "done"]
        if busy:
            sys.exit(f"test-writing teammates still writing: {', '.join('tests-' + t for t in busy)}; wait for their done reports, then run again")
        fc_briefs.collect_tests(proj, ",".join(pending))
    unwritten = [m["id"] for m in tasks if fc_briefs.test_open(proj, m["id"]) or m["id"] in fc_briefs.waiting_writers(proj)]
    if unwritten:  # the collect starts the writers that waited for another writer of the same test file
        sys.exit(f"test-writing teammates still to write: {', '.join('tests-' + t for t in unwritten)}; wait for their done reports, then run again")
    missing = [f"{m['id']} {p}" for m in tasks for p in m.get("protected") or [] if not (repo / p).exists()]
    if missing:  # checked here, not in spec-check: the cut is checked before its tests are written
        sys.exit(f"protected tests not on the project branch: {', '.join(missing)}; write them (compose testcrews) or fix `protected:`, then run again")
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
    # pi takes a provider's key from its own auth.json before the workspace key compose hands it, so such an entry bills elsewhere.
    shadowing = [p for p in fc_pi.pi_auth_overrides(fc_pi.PI_AUTH) if any(m.startswith(f"pi:{p}/") for m in models)]
    if shadowing:
        sys.exit(f"preflight stopped; nothing was cloned or run. {fc_pi.PI_AUTH} holds a key for {' and '.join(shadowing)}, which pi "
                 f"uses instead of the key of workspace {fc_config.WORKSPACE!r}: remove {'that entry' if len(shadowing) == 1 else 'those entries'} from it")
    fc_core.say(f"preflight  {', '.join(models)}")
    with ThreadPoolExecutor(max_workers=max(1, len(models))) as ex:
        bad = [b for b in ex.map(probe, models) if b]
    if bad:
        sys.exit("preflight failed; nothing was cloned or run. Fix the model id or preset in "
                 f"{fc_config.CONFIG_PATH} (`models`) or the task's `model:`:\n  " + "\n  ".join(bad))

def run_tasks(repo, proj, tasks, a):
    fc_proc.keep_awake()  # a run lasts hours; a sleeping Mac stops every agent and fails every check that waits on a timeout
    models = {m["model"] for m in tasks}
    preflight(models | {fc_models.fallback_for(m) for m in models})
    a.trunk = a.trunk or fc_core.current_branch(repo)  # the branch the user started on is the stack's trunk; it is never switched
    if not a.no_stack and fc_worktree.stack_order(repo, proj):
        # Earlier layers must contain everything committed on trunk since they were built (new tests, new task files), or a
        # task stacked on them starts without its own test. Rebase the existing chain onto the current trunk tip first.
        # `--no-stack` leaves the chain alone: a task with `after:` still rebases what it stacks on, the rest never wait on it.
        fc_layers.linearize(repo, proj, a.trunk, fc_worktree.stack_worktree(repo, proj, a.trunk))
        if fc_layers.STACK_STOP:
            sys.exit(f"stack  STOP  {fc_layers.STACK_STOP}")
    fc_herdr.herdr_space(proj)
    t0 = time.time()
    (proj / "results").mkdir(exist_ok=True)
    fc_core.atomic_write((proj / "results" / "run.json"), json.dumps({"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tasks": [m["id"] for m in tasks], "args": {"attempts": a.attempts, "parallel": a.parallel, "trunk": a.trunk, "no_stack": a.no_stack}}, indent=2))
    fc_core.say(f"run start project={proj.name} tasks={len(tasks)} parallel={a.parallel} attempts={a.attempts}")
    # Dependency order: a task runs once every `after:` task in this run has passed (it then stacks on that branch) or was
    # merged or skipped earlier. Independent tasks run in parallel; a chain runs layer by layer.
    metas = {m["id"]: m for m in tasks}
    ids = set(metas)
    deps = {p: [d for d in (x.strip() for x in str(m.get("after") or "").split(",")) if d in ids] for p, m in metas.items()}
    results, pending, failed_ids, halt, reflecting = [], dict(deps), set(), None, []
    waits = fc_tasks.waiting(tasks)  # an unfinished blocker outside the feature's tasks holds its task like a hold
    from concurrent.futures import wait, FIRST_COMPLETED
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        running = {}
        while pending or running:
            hold = {**waits, **fc_tasks.held(proj)}  # re-read every pass: a hold or a release lands while the run goes on
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
            try:
                finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
            except KeyboardInterrupt:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                fc_proc.stop()
                print(f"\n[{fc_core.now()}] run stopped by Ctrl-C; `compose resume` continues it", file=sys.stderr)
                os._exit(130)
            for f in finished:
                p = running.pop(f)
                try:
                    r = f.result()
                except RuntimeError as e:  # a chain that no longer rebases: the task never started; one line with the commands, and the run goes on
                    fc_core.say(f"{p} STOP  {e}")
                    r = {"id": metas[p]["id"], "title": metas[p].get("title"), "status": "unchained", "attempts": 0, "seconds": 0.0, "cost": 0.0,
                         "branch": "-", "log": [{"stop": str(e)}]}
                    fc_core.atomic_write((proj / "results" / f"{p}.json"), json.dumps(r, indent=2))
                if r["status"] == "held":  # held while it was prepared, before its first turn: pending again, the next pass reads the hold
                    pending[p] = []
                    continue
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
    if any(m.get("linear") for m in tasks):
        fc_linear.linear_reconcile(proj)
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
        fc_stack.register_stack(repo, proj, a.trunk)
    if halt:
        done_ids = {r["id"] for r in results if r["status"] in (*fc_tasks.FINISHED, "already_green")}
        remaining = sorted(metas[p]["id"] for p in metas if metas[p]["id"] not in done_ids)
        fc_models.payment_halt(repo, proj, "run", remaining, {"attempts": a.attempts, "parallel": a.parallel, "trunk": a.trunk, "no_stack": a.no_stack}, halt)
    (proj / "results" / "resume.json").unlink(missing_ok=True)
    (proj / "results" / "run.json").unlink(missing_ok=True)
    fc_core.atomic_write((proj / "results" / "run-cost.json"), json.dumps(fc_core.LEDGER.snapshot(), indent=2))
    sys.exit(0 if all(r["status"] in fc_tasks.FINISHED for r in results) else 1)


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
        require_committed(repo, not getattr(ns, "no_stack", False))
        tasks = [m for m in fc_tasks.load_tasks(proj, required=True) if m["id"] in set(state["remaining"]) and not fc_tasks.task_finished(proj, m)]
        if not tasks:
            path.unlink(missing_ok=True)
            sys.exit("nothing left to run; cleared the halt")
        ns.parallel = getattr(a, "parallel", None) or fc_config.PARALLEL or getattr(ns, "parallel", None) or RUN_PARALLEL  # flag, config, the halted run's
        fc_core.say(f"resume {len(tasks)} task(s): {', '.join(m['id'] for m in tasks)}")
        run_tasks(repo, proj, tasks, ns)
    else:
        ns.fix, ns.skip_e2e, ns.skip_review = state["args"]["fix"], state["args"]["skip_e2e"], state["args"]["skip_review"]
        fc_verify.cmd_verify(ns)
