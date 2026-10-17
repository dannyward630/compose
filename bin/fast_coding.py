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
import argparse, json, os, re, signal, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc_cost, fc_mcp  # noqa: E402
import fc_core, fc_config, fc_tasks, fc_linear, fc_claude, fc_models, fc_herdr, fc_worktree, fc_layers, fc_change, fc_frame0, fc_crew, fc_init, fc_figma, fc_briefs, fc_implement, fc_jev, fc_verify, fc_run, fc_status, fc_spec, fc_watch, fc_yolo  # noqa: E402

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
                            ("run", fc_run.cmd_run, "dispatch tasks to parallel implementers (pi by default)"),
                            ("verify", fc_verify.cmd_verify, "local no-mistakes-style pipeline: checks, confirmed fast-model review, jev e2e, auto-fix loop"),
                            ("bench", cmd_bench, "frozen task set x models: pass rate, attempts, p50/p95 time, cost per task"),
                            ("resume", fc_run.cmd_resume, "continue a run or verify that stopped on PAYMENT REQUIRED"),
                            ("done", fc_status.cmd_done, "record tasks the team lead finished by hand: --only ids --note why"),
                            ("sync", fc_linear.cmd_sync, "store the feature and its tasks: --from-linear reads them from Linear, else JSON on stdin"),
                            ("tasks", fc_spec.cmd_tasks, "the task list to review before dispatch: ids, titles, files, after, tests; warns on shared files"),
                            ("spec-check", fc_spec.cmd_spec_check, "check the synced feature, its stories, and its tasks against the spec; --stdin reads the sync JSON"),
                            ("projects", fc_status.cmd_projects, "list every project (feature) with its task progress"),
                            ("cost", fc_status.cmd_cost, "tokens per teammate session and per run provider; --json"),
                            ("status", fc_status.cmd_status, "projects and every task's state, attempts, time, cost, stack layer; --watch redraws live"),
                            ("watch", fc_watch.cmd_watch, "block until a task finishes, an agent blocks, a run ends, or verify finishes; print one event line and exit"),
                            ("top", fc_status.cmd_top, "check out the stack top in the CLI worktree for manual testing; --detach to release it"),
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
                            ("triage", fc_run.cmd_triage, "fast-model look at each passed task: clean or flag (run does this at its end)"),
                            ("reflect", fc_change.cmd_reflect, "screen the settled decisions against evidence with Jev: HOLDS | BROKEN | UNCLEAR per line"),
                            ("hold", fc_change.cmd_hold, "hold tasks back from dispatch while the plan changes: --only ids --reason why; --release ids|all"),
                            ("yolo", fc_yolo.cmd_yolo, "the product owner is away: [--push] [words] enters, `decided \"<q>: <a>\"` logs an answer taken, `off` prints the digest and archives"),
                            ("change", fc_change.cmd_change, "start | done | undo a change of course: what changed in Linear and why, undoable"),
                            ("crew", fc_crew.cmd_crew, "start | list | focus | stop teammates, the Claude sessions in the project's herdr space (the team lead, the wayfinder, helpers)"),
                            ("report", fc_crew.cmd_report, "a teammate session reports up: working | needs-user | blocked | done, with one line"),
                            ("models", fc_models.cmd_models, "--probe: clear the day's cached model probes and probe the crew models again"),
                            ("frame0", fc_frame0.cmd_frame0, "up | save | down the project's own Frame0 (wireframes in .fast-coding/<project>/design.f0)"),
                            ("figma", fc_figma.cmd_figma, "check | tree | judge: store the target Figma file key and prove Framelink reads it; save a task's node tree; judge it with Jev"),
                            ("teardown", fc_crew.cmd_teardown, "close the project's implementer, verify, and finished teammate tabs (the team lead's done does this)"),
                            ("guard", fc_crew.cmd_guard, "Claude Code PreToolUse hook: the team lead writes no code (reads the hook event on stdin)"),
                            ("rewake", fc_watch.cmd_rewake, "Claude Code Stop hook: park a watch after each team lead turn; its event wakes the session"),
                            ("reenter", fc_watch.cmd_reenter, "Claude Code SessionStart hook: after a compaction, point the teammate back at its brief, the board, and Linear"),
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
            s.add_argument("--stall", type=float, default=None, help=f"seconds of silence with work pending before a stall event (default verify.json stall_seconds, else {fc_watch.STALL_SECONDS})")
            s.add_argument("--interval", type=float, default=fc_watch.WATCH_INTERVAL)
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
    if a.fn not in (fc_config.cmd_workspace, fc_crew.cmd_guard, fc_watch.cmd_rewake, fc_crew.cmd_skillcheck):  # the hooks run in every session: no config, no output
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
