import json, os, re, signal, subprocess, sys, time
from pathlib import Path
import fc_core, fc_config, fc_tasks, fc_linear, fc_claude, fc_models, fc_herdr, fc_worktree, fc_layers


def implementer(cwd, model, prompt, session=None, task=None, timeout=None):
    """Route a turn to the harness named by the model id: `pi:<provider/model>` runs pi (as a named herdr agent when the run
    is inside herdr and `task` names the project's space), anything else runs OpenCode."""
    fake = os.environ.get("COMPOSE_FAKE_402")  # test hook: behave as if the provider refused for billing (optionally only for prompts matching)
    if fake and os.environ.get("COMPOSE_FAKE_402_MATCH", "") in prompt:
        raise fc_models.PaymentRequired(fake, "Payment required to access this resource (simulated)")
    prompt = fc_core.scrub(prompt)
    if fc_claude.is_claude(model):
        return fc_claude.claude_once(cwd, prompt, model=fc_claude.claude_id(model))
    if model.startswith("pi:"):
        if fc_herdr.herdr_env() and task and task.get("space"):
            return herdr_pi(cwd, model[3:], prompt, session, task, timeout)
        return fc_models.pi_turn(cwd, model[3:], prompt, session, timeout)
    return fc_models.opencode(cwd, model, prompt, session)


def herdr_pi(cwd, model, prompt, session, task, timeout=None):
    """One turn of an interactive pi running as a named herdr agent in its own pane of the space's `implementers` tab.
    Same contract as pi_turn(): (session, reply_text, tool_calls, usage). The session dict names the agent, its pane and tab,
    and the pi session file the turn's text and usage are read from. The team lead steers the same agent with
    `herdr agent prompt <name> ...` between the CLI's own prompts."""
    timeout = timeout or fc_models.TURN_TIMEOUT
    meta, proj = task["meta"], task["proj"]
    tid, name = meta["id"], fc_herdr.agent_name(proj.name, meta["id"])
    title = f"{tid} {meta.get('title', '')}".strip()[:60]
    if session is None:
        old = fc_herdr.herdr("agent", "get", name)
        if old:  # a previous run's agent for this task: its pane goes, the name is reused
            fc_herdr.herdr("pane", "close", (old.get("agent") or old).get("pane_id"))
        # No key in the pane's env: pi's tools (the task's test among them) inherit it. pi gets it in --api-key below.
        pane = fc_herdr.herdr_implementer_pane(task["space"], cwd, {"GRAFT_NO_GITIGNORE": "1", "GRAFT_NO_IGNORE": "1",
                                                                     "COMPOSE_CONFIG": fc_core.scratch_config()})
        fc_herdr.herdr("pane", "rename", pane, title)
        sdir = Path(cwd).parent / (Path(cwd).name + ".pi-sessions")
        sdir.mkdir(exist_ok=True)
        import uuid
        args = ["--tui-mode", "regular", "--no-extensions", *(["-e", str(fc_herdr.PI_HERDR_EXT)] if fc_herdr.PI_HERDR_EXT.exists() else []),
                "--no-skills", "--no-prompt-templates", "--thinking", "low", "--session-id", str(uuid.uuid4()), "--session-dir", str(sdir), "--model", model,
                *fc_models.pi_turn_key_args(model)]
        started = fc_herdr.herdr_agent_start(name, "--kind", "pi", "--pane", pane, "--timeout", "60000", "--", *args)
        sfile = ((started.get("agent") or {}).get("agent_session") or {}).get("value")
        session = {"name": name, "pane": pane, "sfile": sfile, "seen": 0}
        fc_herdr.herdr("pane", "report-metadata", pane, "--source", "compose", "--title", title, "--token", f"model={model.split('/')[-1].split('@')[0]}")
    for attempt in range(2):
        result, err = fc_herdr.herdr_error("agent", "prompt", session["name"], prompt, "--wait", "--timeout", str(timeout * 1000), timeout=timeout + 30)
        if err == "agent_blocked" and attempt == 0:  # pi is showing a dialog from the last turn; dismiss it and resend
            fc_herdr.herdr("agent", "send-keys", session["name"], "esc")
            time.sleep(1)
            continue
        break
    if err == "timeout" or err == "agent_prompt_stalled":
        fc_herdr.herdr("agent", "send-keys", session["name"], "esc")
        fc_herdr.herdr("pane", "close", session["pane"])
        raise subprocess.TimeoutExpired("herdr agent prompt", timeout)
    if err:
        raise RuntimeError(f"herdr agent prompt {session['name']}: {err}")
    if not session.get("sfile"):
        got = fc_herdr.herdr("agent", "get", session["name"]) or {}
        session["sfile"] = ((got.get("agent") or {}).get("agent_session") or {}).get("value")
    session["seen"], text, tools, usage, errors = fc_models.parse_pi_session(session["sfile"] or "", session["seen"])
    if not text and not tools and not usage["tokens_in"]:
        raise RuntimeError(f"provider refused the request: {'; '.join(errors) or 'empty turn with no usage'}")
    if model in fc_config.PRICES:
        usage["cost"] = (usage["tokens_in"] * fc_config.PRICES[model][0] + usage["tokens_out"] * fc_config.PRICES[model][1]) / 1e6
    fc_core.LEDGER.add("openrouter" if "openrouter" in model else model.split("/")[0], usage["tokens_in"], usage["tokens_out"], usage["cost"])
    if any("rate" in e.lower() and "limit" in e.lower() for e in errors):
        raise fc_models.RateLimited(usage)
    return session, text, tools, usage

LEARNING_RE = re.compile(r"^from (a learning|.+'s learning)")  # heads a trail learning block in `trail ask` output
BANNERS = ("[trail]", "⬆ trail", "· no learnings")  # trail's own notes there, not code

def trail_pack(wt, query, repo=None, limit=6):
    """Context pack from a trail graph, $0 and no model. The graph is git-ignored, so a worktree gets its own graph:
    the main repo's graph is copied in as a cache, at the same place (graft/ or .trail/cache/), and rebuilt from the
    worktree's files (so a bench reset is not leaked)."""
    src = repo and fc_worktree.graph_dir(repo)
    if src and not fc_worktree.graph_dir(wt):
        import shutil
        shutil.copytree(src, wt / src.relative_to(repo), dirs_exist_ok=True)
        (wt / ".trail" / "cache").mkdir(parents=True, exist_ok=True)
        fc_core.sh(["trail", "build", "--no-gitignore", "--no-ignore", str(wt)], wt, timeout=600, check=False)
    if not fc_worktree.graph_dir(wt):
        return ""
    p = fc_core.sh(["trail", "ask", query, "--source", "-n", str(limit), "--no-refresh", str(wt)], wt, timeout=60, check=False)
    if p.returncode:
        return ""
    lines, skip = [], None  # "learning": inside a learning block, which runs to a blank line; "blank": right after a banner
    for l in p.stdout.splitlines():
        if LEARNING_RE.match(l) or l.startswith(BANNERS):
            skip = "learning" if LEARNING_RE.match(l) else "blank"
        elif not l.strip() and skip:
            skip = None  # the blank line closing what was dropped goes with it
        elif skip != "learning":
            skip = None
            lines.append(l)
    return "\n".join(lines).strip()[:12000]

def branch_budget(wt, base, allowed=None):
    """(lines changed vs base counting the working tree, new document files, files outside the task's `files:` list).
    All three are hard limits for an implementer: size, no documents, and scope."""
    fc_core.sh(["git", "add", "-A"], wt, check=False)
    lines = 0
    for row in fc_core.sh(["git", "diff", "--cached", "--numstat", base], wt, check=False).stdout.splitlines():
        a, d, f = row.split("\t", 2)
        if not fc_worktree.GENERATED_RE.search(f):  # lockfiles are regenerated, nobody reads them
            lines += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    changed = fc_core.sh(["git", "diff", "--cached", "--name-only", base], wt, check=False).stdout.split()
    new_docs = [f for f in fc_core.sh(["git", "diff", "--cached", "--name-only", "--diff-filter=A", base], wt, check=False).stdout.split()
                if fc_config.DOC_RE.search(f)]
    stray = [f for f in changed if allowed is not None and f not in allowed and f not in new_docs]
    return lines, new_docs, stray

def task_base(repo, proj, meta):
    """The branch a task builds on. A task whose `after:` names unmerged task branches stacks on top of them (they must form one
    chain, so each PR shows only its own layer); otherwise it builds on HEAD like any independent task."""
    after = [x.strip() for x in str(meta.get("after") or "").split(",") if x.strip()]
    head = fc_core.sh(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    unmerged = []
    for dep in after:
        b = f"fast/{proj.name}/{dep}"
        if fc_core.sh(["git", "rev-parse", "--verify", "-q", b], repo, check=False).returncode != 0:
            continue  # no branch: the dependency was merged (or never ran, which `run` refuses earlier)
        if fc_core.sh(["git", "merge-base", "--is-ancestor", b, head], repo, check=False).returncode != 0:
            unmerged.append(b)
    if not unmerged:
        return "HEAD", head
    # The project is one stack: linearize what has passed so far and build on the chain's top, which contains every dependency.
    trunk = fc_core.current_branch(repo)
    with fc_worktree.STACK_LOCK:  # read the base before another task's linearize rewrites it
        chain = fc_layers.linearize(repo, proj, trunk, fc_worktree.stack_worktree(repo, proj, trunk))
        missing = [b for b in unmerged if b not in chain]
        if missing:
            raise RuntimeError(f"after: {', '.join(missing)} could not be chained: {fc_layers.STACK_STOP or 'rebase conflict'}")
        # Base on the highest dependency, not the chain top: layers ordered after this task must stay above it in history.
        base = max(unmerged, key=chain.index)
        return base, fc_core.sh(["git", "rev-parse", base], repo).stdout.strip()

PRETTIER_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".scss", ".json", ".html", ".vue"}

def format_files(wt, files, base="HEAD"):
    """Format a passed task's own changed files with the repo's formatter, deterministically and with no model, so verify's
    fix rounds never spend one on formatting: gofmt for Go, the repo's installed prettier for web files. Whatever the formatter,
    a text file ends with exactly one final newline, unless it had none on base. Returns what changed."""
    import shutil
    out = []
    for f in files:
        p = wt / f
        cmd = None
        if p.suffix == ".go" and shutil.which("gofmt"):
            cmd = ["gofmt", "-w", str(p)]
        elif p.suffix in PRETTIER_EXT:
            d = p.parent
            while cmd is None and (d == wt or wt in d.parents):  # the nearest node_modules, up to the clone root
                bin_ = d / "node_modules" / ".bin" / "prettier"
                cmd = [str(bin_), "--write", str(p)] if bin_.exists() else None
                d = d.parent
        before = p.read_bytes()
        if cmd:
            fc_core.sh(cmd, wt, timeout=120, check=False)
        data = p.read_bytes()
        text = b"\0" not in data and data.strip()
        old = fc_core.sh(["git", "show", f"{base}:{f}"], wt, check=False) if text else None  # only text is decoded
        if text and (old.returncode != 0 or old.stdout.endswith("\n")):
            data = data.rstrip(b"\n") + b"\n"
            p.write_bytes(data)
        if data != before:
            out.append(f)
    return out

READER_TIMEOUT = 120  # seconds the test reader may take before the raw tail goes back alone

def read_failure(wt, meta, output, log_path):
    """(brief, usage): the test reader's short fix brief for a failed test run, for the implementer's next attempt. The reader
    (models.test_reader, Claude Haiku by default) runs headless in the task's clone with read-only tools, so it can point at the
    file:line but never edit or run anything. ("", None) when no Claude reader is set, or it fails or times out: the raw tail
    always follows, so this only ever adds."""
    if not fc_config.TEST_READER or not fc_claude.is_claude(fc_config.TEST_READER):
        return "", None
    prompt = (f"A test run failed in this repository.\nTest command: {meta['test']}\nFull output: {log_path}\nOutput (tail):\n{output[-6000:]}\n\n"
              f"Files the fix may change: {', '.join(meta['files']) or 'any'}. Open the test file and those files with Read when the output alone does not "
              "show where the problem is; you cannot edit files or run commands. "
              "Reply with at most 8 short lines and nothing else: each failing case, what it expected versus what it got, and the file:line "
              "to look at. No advice beyond that, no code.")
    try:
        _, reply, _, usage = fc_claude.claude_once(wt, prompt, timeout=READER_TIMEOUT, model=fc_claude.claude_id(fc_config.TEST_READER), tools="Read,Grep,Glob")
    except Exception:  # noqa: BLE001 - a timeout or a refused call leaves the raw tail
        return "", None
    return reply.strip()[:1500], usage

HANG_HINT = ("The test did not finish within {limit}s, so it hangs: most likely a deadlock (for example a query run while "
             "another query's rows are still open on a single connection) or something waiting forever. Fix the hang.")

def timed(cmd, cwd, limit, env=None):
    """Run a shell command with a hard time limit, whatever the language or test runner. On a hang the whole process
    group goes (a test binary must not outlive its shell) and the result is exit 124 with a deadlock hint. The output
    comes back scrubbed of secrets: it goes on to models and results/. A change to the user's ~/.compose meanwhile is flagged."""
    before = fc_core.home_state()
    p = subprocess.Popen(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    try:
        out, err = p.communicate(timeout=limit)
        return subprocess.CompletedProcess(cmd, p.returncode, fc_core.scrub(out), fc_core.scrub(err))
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):  # the group is already gone (macOS says EPERM)
                break
            time.sleep(0.5)
            if p.poll() is not None:
                break
        out, err = (fc_core.scrub(x or "") for x in p.communicate())
        return subprocess.CompletedProcess(cmd, 124, out[-2000:], (err[-1000:] + "\n" + HANG_HINT.format(limit=limit)).strip())
    finally:
        fc_core.flag_home(before, f"`{cmd}`")

def run_test(meta, wt):
    """A task's test command under the time limit (a task's block can set `test_timeout:`)."""
    return timed(meta["test"], wt, int(meta.get("test_timeout") or fc_models.TEST_TIMEOUT), env=fc_core.clean_env())

def cmd_timed(argv):
    """`compose timed <seconds> -- <command>`: what teammates run tests and commands through, so a hang fails fast."""
    if len(argv) < 3 or argv[1] != "--":
        sys.exit("usage: compose timed <seconds> -- <command>")
    r = timed(" ".join(argv[2:]), os.getcwd(), int(argv[0]), env=fc_core.clean_env())
    sys.stdout.write(r.stdout); sys.stderr.write(r.stderr if r.stderr.endswith("\n") or not r.stderr else r.stderr + "\n")
    sys.exit(r.returncode)

def run_task(repo, proj, task, attempts, model=None, reset_files=False, tag=""):
    meta = dict(task)  # the fallback switches meta["model"]; the shared task list stays as synced
    body = meta.pop("body")
    if model:
        meta["model"] = model
    tid, branch = meta["id"], f"fast/{proj.name}/{meta['id']}{tag}"
    wt = proj / "worktrees" / (tid + tag)
    # A separate clone, not a git worktree: opencode links worktrees to the main checkout as "project copies" and
    # resolves edits of existing files there. A clone has its own .git, so nothing can leak. Shared objects keep it cheap.
    import shutil
    if wt.exists():
        shutil.rmtree(wt)
    fc_core.sh(["git", "worktree", "prune"], repo, check=False)
    why = not tag and fc_tasks.task_finished(proj, meta, redo=bool(os.environ.get("COMPOSE_REDO")))
    if why:
        # A passed layer may already have a PR, and a hand-done one carries a teammate's commit. Never replace either silently;
        # `--redo` says the user wants it rebuilt.
        fc_core.say(f"{tid} keep    {why}; pass --redo to rebuild it")
        return json.loads((proj / "results" / f"{tid}.json").read_text())
    fc_worktree.replace_branch(repo, proj, branch)  # a re-run (or --redo) replaces the previous attempt
    fc_core.sh(["git", "clone", "--quiet", "--shared", "--no-hardlinks", str(repo), str(wt)], repo)
    base_name, base = task_base(repo, proj, meta)
    fc_core.sh(["git", "checkout", "-q", "-b", branch, base], wt)  # a stacked task starts from its lower layer's tip
    fc_worktree.ready_checkout(repo, wt, borrow=not fc_worktree.names_lockfile(meta), install=fc_core.project_config(proj).get("install"))
    for name in ("opencode.jsonc", "opencode.json"):  # untracked local config the implementer needs
        if (repo / name).exists() and not (wt / name).exists():
            shutil.copy(repo / name, wt / name)
    if reset_files:
        # Benchmark mode: remove the implementation so the frozen test is red again and the model starts from scratch.
        for f in meta["files"]:
            if (wt / f).exists():
                (wt / f).unlink()
        fc_core.sh(["git", "commit", "-qam", fc_core.typed("reset implementation", "deps", fc_core.commit_convention(proj)) if fc_core.commit_convention(proj) else "bench: reset implementation"], wt, check=False)
    before = fc_core.digests(wt, meta["protected"])
    # Red first: a test that already passes on HEAD means the task is done or the test is vacuous. Do not spend an implementer on it.
    red = run_test(meta, wt)
    if red.returncode == 0:
        fc_core.say(f"{tid} skip    test already passes on {base_name}; fix the test or drop the task")
        result = {"id": tid, "title": meta.get("title"), "status": "already_green", "model": meta["model"], "attempts": 0,
                  "seconds": 0.0, "cost": 0.0, "branch": branch, "worktree": str(wt), "diffstat": "", "log": []}
        (proj / "results").mkdir(exist_ok=True)
        fc_core.atomic_write((proj / "results" / f"{tid}.json"), json.dumps(result, indent=2))
        return result
    goal = re.search(r"## Goal\n(.*?)(?:\n## |\Z)", body, re.S)
    pack = trail_pack(wt, f"{meta.get('title', '')}: {(goal.group(1) if goal else body)[:400]}", repo=repo)
    context = (f"CONTEXT PACK from the repo's trail graph (exact file:line, with source). Use it instead of exploring. "
               f"If you need more, run `trail ask \"<question>\"` or `trail callers <symbol>`; do not open unrelated files.\n{pack}\n\n"
               if pack else "")
    root = str(wt.resolve())
    abs_files = ", ".join(str(wt.resolve() / f) for f in meta["files"]) or "files under the root as needed"
    abs_protected = ", ".join(str(wt.resolve() / f) for f in meta["protected"]) or "none"
    prompt = (f"You are implementing one small task in this repository.\n\n"
              f"REPOSITORY ROOT FOR THIS TASK: {root}\n"
              f"Every file you read, create, or edit must be under that root. Project docs may mention other absolute paths "
              f"(for example the original checkout this task was cloned from); those are read-only references, never edit them.\n\n"
              f"{context}{body}\n\n"
              f"Files you may edit: {abs_files}.\n"
              f"Files you must NOT edit: {abs_protected}.\n"
              f"Done means this command exits 0: {meta['test']}\n"
              "Do not run it, or any other test or build: compose runs the test after your turn ends and sends you what failed. "
              "Read the test file, edit, and end your turn.\n"
              "The test contains cases beyond the examples listed here, so implement the described behavior, not the examples. "
              "Read only the test file and the files named above; do not explore other docs or directories. "
              "Make the smallest, simplest change that passes: no defensive checks, flags, "
              "hardening, helpers, or comments the task does not ask for. Do not explain, just edit.\n"
              f"Hard limits: the whole change must stay under {fc_config.MAX_DIFF_LINES} changed lines (added plus deleted), you must not "
              "create any document file (.md, .txt, .rst, docs/), and you may change ONLY the files listed above, even if other "
              "tests in the repo fail: other tasks own them. A change that breaks any of these is rejected.\n"
              "If a fact this brief states is wrong (a function, file, or API it names is missing or behaves differently), do not "
              "work around it: end your reply with one line `CONTRADICTION: <what the brief says> / <what the code shows, file:line>` and stop.")
    log, session, started, status, cost = [], None, time.time(), "failed", 0.0
    original_prompt = prompt
    def progress(state):  # `compose status --watch` reads this while the task runs
        (proj / "results").mkdir(exist_ok=True)
        fc_core.atomic_write((proj / "results" / f"{tid}.json"), json.dumps({"id": tid, "title": meta.get("title"), "status": state, "model": meta["model"],
            "attempts": len(log), "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), "seconds": round(time.time() - started, 1),
            "cost": round(cost, 6), "branch": branch, "base": base_name, "worktree": str(wt), "log": log}, indent=2))
    progress("running")
    fc_core.say(f"{tid} start   {meta.get('title', '')}  model={meta['model']}")
    if not reset_files and not tag:  # bench runs leave Linear alone
        fc_linear.linear_event(proj, meta, "dispatched")
    rate_waits = 0
    attempt = 0
    fails = 0  # failed attempts on the current model
    fall = lambda: None if reset_files else fc_models.fallback_for(meta["model"])  # bench measures the named model alone
    def switch(why, next_prompt):  # hand the task to the fallback model in a fresh session (a session is bound to its model)
        nonlocal session, prompt, fails
        model = fall()
        fc_core.say(f"{tid} fallback {meta['model']} {why}; switching to {model}")
        log[-1]["fallback"] = {"from": meta["model"], "to": model, "why": why}  # on the attempt that triggered it
        meta["model"], session, prompt, fails = model, None, next_prompt, 0
    def failed(why, next_prompt):  # one more failed attempt: the fallback takes over after models.fallback_after of them
        nonlocal fails
        fails += 1
        if fall() and fails >= fc_config.FALLBACK_AFTER:
            switch(why, next_prompt)
            return True
        return False
    while attempt < attempts:
        attempt += 1
        t0 = time.time()
        try:
            session, reply, tools, usage = implementer(wt, meta["model"], prompt, session, task={"proj": proj, "meta": meta, "space": fc_herdr.HERDR_SPACES.get(proj.name)},
                                                       timeout=fc_models.TURN_TIMEOUT)
        except fc_models.RateLimited as e:
            cost += e.usage["cost"]
            if fall():
                log.append({"attempt": attempt, "rate_limited": True, "seconds": round(time.time() - t0, 1), "usage": e.usage})
                switch(f"rate-limited by provider", original_prompt)
                attempt -= 1
                continue
            rate_waits += 1
            if rate_waits > 4:
                log.append({"attempt": attempt, "error": "rate limited 4 times; giving up"})
                break
            wait = 20 * rate_waits
            fc_core.say(f"{tid} rate-limited by provider; fresh session in {wait}s (wait {rate_waits}/4)")
            log.append({"attempt": attempt, "rate_limited": True, "seconds": round(time.time() - t0, 1), "usage": e.usage})
            session = None  # the compacted session is dead; restart from the original prompt
            prompt = original_prompt
            attempt -= 1
            time.sleep(wait)
            continue
        except subprocess.TimeoutExpired:
            # A hung implementer (tool call never returning) costs one attempt, not the task: fresh session, same prompt.
            fc_core.say(f"{tid} attempt {attempt} timeout  implementer turn did not finish within {fc_core.fmt(time.time() - t0)}; fresh session")
            log.append({"attempt": attempt, "seconds": round(time.time() - t0, 1), "error": "implementer timed out"})
            session = None
            prompt = original_prompt
            failed("timed out", original_prompt)
            continue
        except fc_models.PaymentRequired as e:
            fc_core.say(f"{tid} HALT    payment required at {e.provider}: {e.message[:120]}")
            log.append({"attempt": attempt, "payment_required": {"provider": e.provider, "message": e.message}})
            status = "payment_required"
            break
        except Exception as e:  # noqa: BLE001
            fc_core.say(f"{tid} error   {str(e)[-300:]}")
            log.append({"attempt": attempt, "error": str(e)[-2000:]})
            if fall():  # a fresh session on the same model until the fallback takes over
                if not failed("errored", original_prompt):
                    session, prompt = None, original_prompt
                continue
            break
        cost += usage["cost"]
        found = contradiction(reply)
        if found:  # the brief states something the code disproves: more attempts would only work around it
            log.append({"attempt": attempt, "seconds": round(time.time() - t0, 1), "tool_calls": tools, "usage": usage,
                        "contradiction": found, "reply": reply[-1500:]})
            fc_core.say(f"{tid} attempt {attempt} contradiction  {found[:160]}")
            status = "contradiction"
            break
        test = run_test(meta, wt)
        tampered = [f for f, d in fc_core.digests(wt, meta["protected"]).items() if d != before[f]]
        lines, new_docs, stray = branch_budget(wt, base, allowed=meta["files"] if meta["files"] else None)
        entry = {"attempt": attempt, "seconds": round(time.time() - t0, 1), "tool_calls": tools, "usage": usage,
                 "test_exit": test.returncode, "tampered": tampered, "lines": lines, "new_docs": new_docs, "stray": stray,
                 "reply": reply[-1500:], "test_output": (test.stdout + test.stderr)[-3000:]}
        log.append(entry)
        progress("running")
        if isinstance(session, dict):
            fc_herdr.herdr_label(session, f"attempt {attempt}/{attempts}", cost)
        over = lines > fc_config.MAX_DIFF_LINES
        verdict = "pass" if test.returncode == 0 and not over and not new_docs and not stray else "fail"
        output, reader = test.stdout + test.stderr, None
        if test.returncode != 0 and not tampered:  # the reader's brief, written before the line so its cost is on it
            (proj / "results").mkdir(parents=True, exist_ok=True)
            log_path = proj / "results" / f"{tid}.test.log"
            log_path.write_text(output)
            entry["summary"], reader = read_failure(wt, meta, output, log_path)
            if reader:
                entry["reader"] = {"model": fc_config.TEST_READER, "usage": reader}
                cost += reader["cost"]
                progress("running")
        fc_core.say(f"{tid} attempt {attempt} {verdict}  {fc_core.fmt(entry['seconds'])}  tools={tools}  lines={lines}  ${usage['cost']:.4f}"
            + (f"  reader ${reader['cost']:.4f}" + (f" (list ${reader['reference_cost']:.4f})" if reader.get("reference_cost") else "") if reader else "")
            + (f"  OVER {fc_config.MAX_DIFF_LINES}" if over else "") + (f"  new docs: {', '.join(new_docs)}" if new_docs else "")
            + (f"  outside files: {', '.join(stray)}" if stray else ""))
        if tampered:
            status = "rejected_tampered"
            break
        if verdict == "pass":
            status = "passed"
            break
        problems = []
        if test.returncode != 0:
            summary = entry["summary"]
            problems.append(f"The test still fails.\nCommand: {meta['test']}\nExit code: {test.returncode}\n"
                            + (f"What failed:\n{summary}\n" if summary else "") + f"Output (tail):\n{output[-1000:]}"
                            + f"\nFull output: {log_path.resolve()}; read it before you change anything.")
        if over:
            problems.append(f"Your change is {lines} lines (added plus deleted); the hard limit is {fc_config.MAX_DIFF_LINES}. Shrink it: revert "
                            "unrelated edits, drop new files that are not named in the task, remove long comments and duplication.")
        if new_docs:
            problems.append("Delete these document files; implementers never add documents: " + ", ".join(new_docs))
        if stray:
            problems.append("Revert every change to these files, they are outside this task (another task owns them; the test for "
                            "this task must pass with only the named files changed): " + ", ".join(stray)
                            + f"\nFiles you may change: {', '.join(meta['files'])}")
        status = ("rejected_size" if over else "rejected_docs" if new_docs else "rejected_scope" if stray else status) if test.returncode == 0 else status
        prompt = "\n\n".join(problems) + "\nFix it without editing protected files."
        fresh = original_prompt + "\n\nA previous attempt left edits in the files and did not pass:\n\n" + prompt
        if not failed("missed", fresh) and session is None:  # nothing to resume (Claude Code turns are one-shot): start from the task too
            prompt = fresh
    # Isolation guard: an implementer must never touch the main checkout. If it did (seen with opencode despite --dir),
    # revert those files and record it; the task's own result lives in its worktree branch.
    # Only this task's own files are reverted: the team lead may be editing other files in the main checkout meanwhile.
    dirty = [l.split()[-1] for l in fc_core.sh(["git", "status", "--porcelain"], repo, check=False).stdout.splitlines()]
    mine = [f for f in dirty if f in meta["files"] or f in meta["protected"]]
    others = [f for f in dirty if f not in mine]
    if mine:
        fc_core.sh(["git", "checkout", "--"] + [f for f in mine if (repo / f).exists() and fc_core.sh(["git", "ls-files", "--error-unmatch", f], repo, check=False).returncode == 0], repo, check=False)
        for f in mine:
            if fc_core.sh(["git", "ls-files", "--error-unmatch", f], repo, check=False).returncode != 0 and (repo / f).exists():
                (repo / f).unlink()
        fc_core.say(f"{tid} WARNING implementer wrote into the main checkout; reverted its task files: {', '.join(mine)}")
        log.append({"leak_reverted": mine})
    if others:
        fc_core.say(f"{tid} note: main checkout has other uncommitted changes (left alone): {', '.join(others)[:160]}")
    if status == "passed":
        fc_core.sh(["git", "add", "-A"], wt)
        changed = [f for f in fc_core.sh(["git", "diff", "--cached", "--name-only", base], wt, check=False).stdout.split() if f in meta["files"]]
        kept = {f: (wt / f).read_bytes() for f in changed if (wt / f).is_file()}
        formatted = format_files(wt, list(kept), base)
        if formatted and run_test(meta, wt).returncode != 0:
            for f, b in kept.items():
                (wt / f).write_bytes(b)
            fc_core.say(f"{tid} note    formatting broke the test; committed unformatted: {', '.join(formatted)}")
        elif formatted:
            fc_core.say(f"{tid} format  {', '.join(formatted)}")
        fc_core.sh(["git", "add", "-A"], wt)
        fc_core.sh(["git", "commit", "-qm", fc_layers.commit_message(meta, fc_core.commit_convention(proj))], wt, check=False)
        fc_core.sh(["git", "fetch", "-q", str(wt), f"{branch}:{branch}"], repo)  # the task branch now exists in the main repo: a layer for review, never merged here
        if fc_worktree.names_lockfile(meta):
            fc_worktree.adopt_installs(repo, wt)
    diff = fc_core.sh(["git", "diff", base, "--stat"], wt, check=False).stdout
    total = round(time.time() - started, 1)
    fc_core.say(f"{tid} {status:10} total {fc_core.fmt(total)}  attempts={len(log)}  ${cost:.4f}")
    if isinstance(session, dict):
        fc_herdr.herdr_label(session, status, cost, state="idle")
        if status == "passed":  # its branch is the record; a missed task's pane stays for the team lead to read and steer
            fc_herdr.herdr("pane", "close", session["pane"])
    result = {"id": tid, "title": meta.get("title"), "status": status, "model": meta["model"], "attempts": len(log),
              "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), "seconds": total, "cost": round(cost, 6),
              "branch": branch, "base": base_name, "worktree": str(wt), "diffstat": diff, "log": log}
    (proj / "results").mkdir(exist_ok=True)
    fc_core.atomic_write((proj / "results" / f"{tid}.json"), json.dumps(result, indent=2))
    if not reset_files and not tag:
        fc_linear.linear_event(proj, meta, "passed" if status == "passed" else "failed", result)
    return result


CONTRADICTION_RE = re.compile(r"^[ \t>*_`-]*CONTRADICTION[*_`]*:[*_]*[ \t]*(.+?)[`*_ \t]*$", re.M)  # markdown around it too

def contradiction(reply):
    """The implementer's last `CONTRADICTION:` line when it found its brief wrong; the prompt's own template echoed back is not one."""
    found = [x.strip() for x in CONTRADICTION_RE.findall(reply or "") if "<what the brief says>" not in x]
    return found[-1] if found else None
