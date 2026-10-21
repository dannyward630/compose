import json, os, re, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import fc_core, fc_proc, fc_config, fc_tasks, fc_linear, fc_models, fc_herdr, fc_worktree, fc_layers, fc_change, fc_implement, fc_init, fc_jev, fc_accept


SIMPLICITY_BAR = ("A finding must be a defect against the plan's requirements. Hardening the requirements do not ask for (portability, "
                  "extra error handling, defensive guards, retries) is no defect: no hardening.")

PERSPECTIVES = {
    "correctness": "Find bugs: wrong logic, unhandled inputs, off-by-one, broken edge cases, error paths that lose data. Ignore style.",
    "security": "Find security and data-loss risks: injection, secrets in code, unsafe eval, missing validation at trust boundaries, "
                "destructive operations without guards, credentials leaving the client.",
    "spec": "Check the diff against the plan and acceptance criteria: unmet criteria, scope creep, gamed or weakened tests, "
            "hardcoded site-specific or example-specific logic where general behavior was required.",
    "docs": "Check whether the diff changes behavior, commands, config, or interfaces that the provided docs describe, "
            "and whether those docs were updated to match. Only flag real mismatches.",
}

def well_formed(i):
    """A finding in the shape the reviewer is asked for. The reply is always valid JSON, so a model that spends it on its
    reasoning returns objects of loose thoughts or the schema echoed back; those are not findings."""
    return (isinstance(i, dict) and isinstance(i.get("file"), str) and i["file"].strip() != "" and i.get("severity") in ("high", "medium", "low")
            and isinstance(i.get("note"), str) and i["note"].strip() != "" and (i.get("line") is None or type(i["line"]) is int))

def llm_review(cfg, diff, plan, docs_text, tests_pass):
    """Parallel fast-model reviews, one per perspective, then a confirmation pass on each high or medium finding.
    Only confirmed findings count. Fails on any confirmed high."""
    env = {**fc_core.load_env(cfg.get("env_file", fc_config.ENV_FILE)), **os.environ}
    wanted = cfg.get("perspectives", ["correctness", "security", "spec"] + (["docs"] if docs_text else []))
    schema = ('Return JSON {"issues": [{"file": str, "line": int|null, "severity": "high|medium|low", "note": str}]}. '
              "Be concrete and terse. An empty list means clean. Never invent files not in the input. "
              "Severity: high only for a bug that breaks a stated requirement, loses data, or is a security hole. Performance or style "
              "concerns at the scale this project runs at are low, never high. " + SIMPLICITY_BAR + " Report it as low if you must mention it. "
              + ("The tests currently PASS; do not report anything the tests already prove works." if tests_pass else ""))
    user = (f"PLAN AND CRITERIA:\n{plan[:15000]}\n\nDIFF OR FILES (may be cut off at the end; a file that ends mid-line "
            f"is truncated by this pack, which is never a finding):\n{diff[:150000]}")
    def one(name):
        """(well-formed findings, how many other entries the reply held)."""
        try:
            out = fc_models.fast_json_whole(env, f"You are a strict code reviewer. Perspective: {PERSPECTIVES[name]} {schema}",
                            user + (f"\n\nDOCS:\n{docs_text[:20000]}" if name == "docs" else ""))
            # Small models sometimes return the issues array bare, or something else entirely; never let that crash the stage.
            issues = out.get("issues", []) if isinstance(out, dict) else (out if isinstance(out, list) else [])
            issues = issues if isinstance(issues, list) else []
            kept = [i for i in issues if well_formed(i)]
            malformed = len(issues) - len(kept)
        except fc_models.PaymentRequired:
            raise
        except Exception as e:  # noqa: BLE001
            # A reviewer that fails to answer is a coverage gap to report, not a defect in the code under review.
            kept, malformed = [{"file": "-", "severity": "low", "note": f"{name} review did not return usable findings this round ({type(e).__name__}: {str(e)[:80]})", "confirmed": False}], 0
        for i in kept:
            i["perspective"] = name
        return kept, malformed
    with ThreadPoolExecutor(max_workers=len(wanted)) as ex:
        batches = list(ex.map(one, wanted))
    raw, malformed = [i for kept, _ in batches for i in kept], sum(n for _, n in batches)
    # Confirmation pass: an independent call must name the line that breaks a requirement and how it must read, or the claim is dropped.
    flat = lambda s: " ".join(str(s).split())
    def confirm(i):
        if i.get("confirmed") or i.get("severity") not in ("high", "medium"):
            i.setdefault("confirmed", False)
            return i
        docs = docs_text[:20000] if i.get("perspective") == "docs" else ""
        try:
            # The verdict comes last, so the model compares the line with the requirement before it decides.
            v = fc_models.fast_object(
                env, "You are verifying one code-review claim against the actual code, the plan, and the design context. Fill the fields "
                'in order. "requirement": the words of the plan, design context, or docs the claim says are broken, copied verbatim; for a '
                'crash, data loss, or security hole, one sentence naming it. "wrong_line": the line of the code or docs that breaks it, '
                'copied verbatim, nothing else. "fixed_line": that line as it must read to meet the requirement ("" if it must go). '
                '"confirmed": true only if wrong_line really breaks the requirement. If the code already does what the requirement says, '
                "the claim's own text says the code is correct, or the claim contradicts the plan or the design context, confirmed is "
                "false. If the claim is wrong, speculative, contradicted by passing tests, or about style, reject it. " + SIMPLICITY_BAR,
                (f"DESIGN CONTEXT (authoritative):\n{cfg.get('review_context')}\n\n" if cfg.get("review_context") else "") +
                f"PLAN AND CRITERIA:\n{plan[:15000]}\n\nCLAIM: [{i['severity']}] {i['file']}{':' + str(i['line']) if i.get('line') else ''}: {i['note']}\n\n"
                f"CODE (may be cut off at the end; truncation is not evidence):\n{diff[:150000]}\n\n" + (f"DOCS:\n{docs}\n\n" if docs else "")
                + ("The tests currently pass." if tests_pass else ""),
                '{"requirement": str, "wrong_line": str, "fixed_line": str, "confirmed": bool}', "confirmed")
            wrong, i["fix"] = str(v.get("wrong_line") or ""), str(v.get("fixed_line") or "")
            i["confirmed"], i["evidence"] = bool(v["confirmed"]), wrong[:300]
            if i["confirmed"] and (not flat(wrong) or flat(wrong) not in flat(diff + "\n" + docs)):
                i["confirmed"], i["evidence"] = False, "evidence is not a quote from the code: " + wrong[:300]
            elif i["confirmed"] and flat(i["fix"]) == flat(wrong):
                i["confirmed"], i["evidence"] = False, "the line as it must read is the line as it is: " + wrong[:300]
        except fc_models.PaymentRequired:
            raise
        except Exception as e:  # noqa: BLE001
            i["confirmed"], i["evidence"], i["judge_error"] = False, str(e), True
        return i
    with ThreadPoolExecutor(max_workers=3) as ex:
        issues = list(ex.map(confirm, raw))
    confirmed = [i for i in issues if i["confirmed"]]
    errors = [i for i in issues if i.get("judge_error")]
    return {"pass": not errors and not any(i["severity"] == "high" for i in confirmed), "issues": issues, "confirmed": confirmed, "malformed": malformed,
            **({"error": f"{len(errors)} confirm call(s) failed: {errors[0]['evidence']}"} if errors else {})}

def verify_failed(proj, rounds, findings):
    """verify ended FAIL after its fix rounds: screen the settled lines against the confirmed findings. Tool errors are not
    findings, so a FAIL with none is not screened."""
    if findings.strip():
        try:
            path, _ = fc_change.reflect(proj, "verify", f"verify failed after {len(rounds)} round(s); confirmed findings:\n{findings[:15000]}")
            fc_core.say(f"reflect {path.name}")
        except Exception as e:  # noqa: BLE001  the verdict stands without the screen
            fc_core.say(f"verify reflect failed ({str(e)[:200]})")

def review_inputs(repo, proj, cfg):
    base = fc_worktree.review_base(repo, cfg) or "main"
    diff = fc_core.sh(["git", "diff", f"{base}...HEAD"], repo, check=False).stdout
    tasks = fc_tasks.load_tasks(proj)
    named = sorted({f for t in tasks for f in t["files"] + t["protected"]})
    if not diff.strip():
        # On the base branch itself there is no range; review the current content of every file the tasks name.
        # Whole files only, up to the budget: a file cut mid-line reads as a syntax error to a small reviewer.
        budget, parts, omitted = 140000, [], []
        for f in named:
            if not (repo / f).exists():
                continue
            text = (repo / f).read_text()
            block = f"==== {f} ====\n{text}"
            if sum(len(x) for x in parts) + len(block) > budget:
                omitted.append(f)
                continue
            parts.append(block)
        if omitted:
            parts.append("==== NOT INCLUDED IN THIS PACK (too large; not a finding) ====\n" + "\n".join(omitted))
        diff = "\n\n".join(parts)
    elif len(diff) > 150000:
        diff = diff[:150000] + "\n\n==== PACK TRUNCATED HERE BY THE TOOL (not a finding) ===="
    plan = fc_tasks.linear_cache(proj)["feature"].get("description", "")  # the feature issue's description is the plan
    plan += "\n\n" + "\n\n".join(f"# Task {t['id']}: {t['title']}\n{t['body']}" for t in tasks)
    if cfg.get("review_context"):
        # Design intent reviewers must not contradict (for example: test credentials come from env by design).
        plan = "DESIGN CONTEXT FROM THE PROJECT (authoritative; do not report these as findings):\n" + str(cfg["review_context"]) + "\n\n" + plan
    docs = "\n\n".join(f"==== {d} ====\n{(repo / d).read_text()}" for d in cfg.get("docs", []) if (repo / d).exists())
    protected = sorted({f for t in tasks for f in t["protected"]})
    return diff, plan, docs, protected

def e2e_stage(repo, cfg, panes, report, findings, results=None, retry=True, keep=False):
    """Every e2e case against one shared setup. Returns whether all passed. Runs beside review and jev, which only call models.
    With `results` (the project's results/), a jev case that does not pass keeps its step screenshots in results/e2e/, and with
    `keep` one that passes does too. `retry` False runs a harness failure once: prove expects failures and reads them itself."""
    ok = True
    stage_setup = None
    # The stage owns its lifecycle: fresh ports each run (the config uses $E2E_PORT / $E2E_CLIENT_PORT), and whatever
    # it started (setup's process group, plus anything left listening on its ports that was not before) ends with it,
    # pass, fail, exception, Ctrl-C, SIGTERM or SIGHUP, so no server or browser outlives a round to answer the next one.
    # A verify killed outright ends nothing; the next stage ends that one's browser (reap_orphans).
    for gone in fc_jev.reap_orphans():
        fc_core.say(f"e2e    ended the browser of a verify that is gone: {gone}")
    env = {k: str(v) for k, v in (cfg.get("e2e_env") or {}).items()}
    env.update(E2E_PORT=str(fc_core.free_port()), E2E_CLIENT_PORT=str(fc_core.free_port()))
    env = fc_jev.expand_ports(env, env)
    # Never the product owner's Chrome: without BU_CDP_URL, browser-harness attaches to the running Chrome and waits for approval.
    # So the stage launches its own Chromium on a fresh CDP port and profile (an extension case sets BU_CDP_URL in e2e_env),
    # unless the project says its cases need no browser (e2e_browser: false, for example drivers of a terminal app).
    profile = None if "BU_CDP_URL" in env or cfg.get("e2e_browser") is False else tempfile.mkdtemp(prefix=f"fc-e2e-browser-{os.getpid()}-")
    if profile:
        cdp = fc_core.free_port()
        env.update(BU_CDP_URL=f"http://127.0.0.1:{cdp}", BU_NAME=f"fc-e2e-{cdp}")
    env.setdefault("BU_NAME", f"fc-e2e-{fc_core.free_port()}")  # every stage names its daemons, so it ends its own and no one else's
    cfg = {**cfg, "e2e": [fc_jev.expand_ports(c, env) for c in cfg.get("e2e", [])]}
    ports = fc_jev.e2e_ports(cfg, env)
    busy = {p for p in ports if fc_core.port_listening(p)}
    daemons = fc_jev.harness_daemons(env["BU_NAME"])
    shots = Path(results) / "e2e" if results else None
    if shots:
        shutil.rmtree(shots, ignore_errors=True)  # only the last run's cases

    def end_stage():
        """End what the stage started: from its `finally`, and from a SIGTERM or SIGHUP (fc_proc.HOOKS), which skips that."""
        if stage_setup:
            fc_jev.stop_group(stage_setup)
        fc_jev.kill_listeners(ports - busy)
        fc_jev.end_new_daemons(env["BU_NAME"], daemons)
        if profile:
            shutil.rmtree(profile, ignore_errors=True)
    hook = f"e2e stage {env['BU_NAME']}"
    fc_proc.HOOKS[hook] = end_stage
    try:
        if profile:
            # Headless unless the project asks to watch (e2e_headed): an unattended verify runs while the display sleeps, and a
            # headed Chromium then stops painting, so screenshots and clicks time out. compose's own test suite forces
            # headless (COMPOSE_E2E_HEADLESS=1), so testing the tool never pops a window on the product owner's screen.
            headless = not cfg.get("e2e_headed") or os.environ.get("COMPOSE_E2E_HEADLESS") == "1"
            if not headless:  # a watched window needs the display awake (cmd_verify already holds this for its whole run)
                fc_proc.keep_awake()
            p = fc_core.sh(["bp", "launch", "about:blank", "--profile", profile, *(["--headless"] if headless else [])], repo, timeout=30, check=False,
                   env={**os.environ, "BP_PORT": env["BU_CDP_URL"].rsplit(":", 1)[1]})
            if p.returncode:  # the cases then fail on the dead CDP port, which reads as a tool error, not the app's
                fc_core.say(f"e2e    browser launch failed: {(p.stderr or p.stdout).strip()[-300:]}")
        if cfg.get("e2e_setup"):
            # One setup (for example a local server) for the whole stage; per-case `setup` still works for one-offs.
            stage_setup = subprocess.Popen(cfg["e2e_setup"], shell=True, cwd=repo, env={**fc_core.clean_env(), **env}, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            fc_jev.await_setup(cfg["e2e_setup"], env, cfg.get("e2e_setup_wait", 3))
        for i, case in enumerate(cfg.get("e2e", [])):
            t1 = time.time()
            stage = f"e2e {case.get('name', i)}"[:40]
            fc_herdr.herdr_stage(panes, stage, "working")
            record = {"record_dir": str(shots / f"{i + 1:02d}-{re.sub(r'[^A-Za-z0-9._-]+', '-', str(case.get('name', 'case')))[:60]}"), "keep_record": keep} \
                if shots and not case.get("driver") else {}
            run_case = lambda: fc_jev.jev_e2e({**case, **record, "env": {**env, **(case.get("env") or {})}}, repo)
            r = run_case()
            if retry and r["exit"] and fc_jev.tool_error(r["stdout"] + r["stderr"]):
                fc_core.say(f"e2e    tool error in {case.get('name')}; retrying once")
                r = run_case()
            r["tool_error"] = bool(r["exit"]) and fc_jev.tool_error(r["stdout"] + r["stderr"])
            r["seconds"] = round(time.time() - t1, 1)
            report["e2e"].append(r)
            ok &= r["exit"] == 0
            verdict = "ok  " if r["exit"] == 0 else "TOOL ERROR" if r["tool_error"] and retry else "FAIL"  # prove expects its cases to fail: a blocked jev is not a tool error there
            fc_herdr.herdr_stage(panes, stage, "idle" if r["exit"] == 0 else "blocked", verdict.strip())
            fc_jev.say_case(case.get("name"), r, verdict)
            if r["exit"] and not r["tool_error"]:  # a tool crash is not the app's failure: no fixer gets it
                findings.append(f"E2E failed: {case.get('name')}\n{r['stdout']}\n{r['stderr']}")
    finally:
        if profile:  # browser-harness keeps one daemon per BU_NAME alive; end ours with the browser it drove
            fc_core.sh(["uv", "run", "--quiet", "python", "-c", f"from browser_harness.admin import restart_daemon; restart_daemon({env['BU_NAME']!r})"],
               fc_config.JEV_DIR, timeout=30, check=False)
        end_stage()
        fc_proc.HOOKS.pop(hook, None)  # only now: a SIGTERM during the slow daemon stop above still ends the rest
    return ok

def fix_tests(tasks, files):
    """The test commands that cover a fix: each code task's `test:` whose `files:` or `protected:` holds a file the fix
    changed, once each, in task order. None when a changed file is in no task: only the full checks cover it."""
    cover = [t for t in fc_tasks.code_tasks(tasks) if set(files) & set(t["files"] + t["protected"])]
    if not files or any(all(f not in t["files"] + t["protected"] for t in cover) for f in files):
        return None
    return list(dict.fromkeys(t["test"] for t in cover))

def run_stages(repo, proj, cfg, a, tests=None):
    """One pass: checks (cheap, exact), then e2e in parallel with review and acceptance. With `tests` (a fix round's
    `fix_tests`) the first stage runs only those, and the full checks run once at the end, only when every stage passed.
    A review-only pass (`--review-only`, right after `run`) skips checks and e2e: just the review and acceptance."""
    report, ok, findings = {"checks": [], "scoped": [], "e2e": [], "review": None, "acceptance": None}, True, []
    home = fc_core.home_state()
    review_only = getattr(a, "review_only", False)
    e2e_cases = [] if a.skip_e2e or review_only else cfg.get("e2e", [])
    stages = (["checks"] if (cfg.get("checks") or tests) and not review_only else []) + [f"e2e {c.get('name', i)}"[:40] for i, c in enumerate(e2e_cases)] \
        + ([] if a.skip_review else (["review"] if cfg.get("review", True) else []) + (["jev"] if cfg.get("jev_acceptance", True) else []))
    panes = fc_herdr.herdr_verify_panes(fc_herdr.herdr_space(proj), repo, stages, fc_herdr.tab_label(proj, "verify"))

    def run_checks(cmds, into):
        for c in cmds:
            t1 = time.time()
            p = fc_proc.run(["/bin/sh", "-c", c], cwd=repo, env=fc_core.clean_env(), timeout=900)  # in a group of its own: a stop ends the whole suite
            out = fc_core.scrub(p.stdout + p.stderr)[-3000:]  # the retry and the label read this one text: a suite that prints harness errors in passing tests is no tool error
            if p.returncode and fc_jev.tool_error(out):
                fc_core.say(f"check  tool error; retrying once  {c}")
                p = fc_proc.run(["/bin/sh", "-c", c], cwd=repo, env=fc_core.clean_env(), timeout=900)
                out = fc_core.scrub(p.stdout + p.stderr)[-3000:]
            tool = bool(p.returncode) and fc_jev.tool_error(out)
            into.append({"cmd": c, "exit": p.returncode, "seconds": round(time.time() - t1, 1), "output": out, "tool_error": tool})
            fc_core.say(f"check  {'ok  ' if p.returncode == 0 else 'TOOL ERROR' if tool else 'FAIL'} {fc_core.fmt(time.time() - t1):>8}  {c}")
            if p.returncode and not tool:
                findings.append(f"Command failed: {c}\n{out}")
        passed = all(c["exit"] == 0 for c in into)
        fc_herdr.herdr_stage(panes, "checks", "idle" if passed else "blocked", "ok" if passed else "FAIL")
        return passed

    checks_pass = None  # no checks ran: the reviewers are not told the tests pass
    if not review_only:
        fc_herdr.herdr_stage(panes, "checks", "working", "" if tests is None else "the fix's tests")
        if tests is not None:
            fc_core.say(f"check  scope  {len(tests)} task test(s) for the fix; the full checks run once every stage passes")
        checks_pass = run_checks(cfg.get("checks", []) if tests is None else tests, report["checks"] if tests is None else report["scoped"])
        ok &= checks_pass
    # e2e drives a browser for minutes while review and jev only wait on model calls: run them side by side, after checks
    # (which may bind the same ports as e2e_setup). Findings from both land in the same list.
    pool = ThreadPoolExecutor(max_workers=1)
    e2e = pool.submit(e2e_stage, repo, cfg, panes, report, findings, proj / "results") if not a.skip_e2e and cfg.get("e2e") and not review_only else None
    if not a.skip_review and cfg.get("review", True):
        t1 = time.time()
        fc_herdr.herdr_stage(panes, "review", "working")
        diff, plan, docs, _ = review_inputs(repo, proj, cfg)
        rv = llm_review(cfg, diff, plan, docs, bool(checks_pass))
        rv["seconds"] = round(time.time() - t1, 1)
        report["review"] = rv
        ok &= rv["pass"]  # review always gates; the jev acceptance stage below is advisory unless asked to gate
        fc_herdr.herdr_stage(panes, "review", "idle" if rv["pass"] else "blocked", f"{len(rv['confirmed'])} confirmed")
        fc_core.say(f"review {'ok  ' if rv['pass'] else 'FAIL'} {fc_core.fmt(rv['seconds']):>8}  {len(rv['confirmed'])} confirmed of {len(rv['issues'])} raised"
                    + (f", {rv['malformed']} malformed dropped" if rv.get("malformed") else ""))
        for i in rv["issues"]:
            mark = "confirmed" if i["confirmed"] else "judge err" if i.get("judge_error") else "dropped  "
            print(f"           {mark} [{i.get('severity')}/{i.get('perspective')}] {i.get('file')}{':' + str(i['line']) if i.get('line') else ''}: {' '.join(i.get('note', '').split())}")
        for i in rv["confirmed"]:
            findings.append(f"[{i['severity']}] {i['file']}: {i['note']}\nEvidence: {i.get('evidence', '')}"
                            + (f"\nMust read: {i['fix'] or '(remove the line)'}" if "fix" in i else ""))
    if not a.skip_review and cfg.get("jev_acceptance", True):
        t1 = time.time()
        fc_herdr.herdr_stage(panes, "jev", "working")
        diff, _, _, _ = review_inputs(repo, proj, cfg)
        try:
            acc = fc_accept.jev_acceptance(cfg, proj, diff, repo=repo)
        except Exception as e:  # noqa: BLE001
            acc = {"pass": False, "criteria": [], "failed": [], "error": str(e)}
        acc["seconds"] = round(time.time() - t1, 1)
        report["acceptance"] = acc
        gate = bool(cfg.get("acceptance_gate", False))  # tests already cover every criterion; the classifier is advisory unless asked to gate
        if gate:
            ok &= acc["pass"]
        n = len(acc.get("criteria", []))
        met = sum(r["choice"] == "MET" for r in acc.get("criteria", []))
        fc_herdr.herdr_stage(panes, "jev", "idle" if acc["pass"] or not gate else "blocked", f"{met}/{n} met")
        fc_core.say(f"jev    {'ok  ' if acc['pass'] else ('FAIL' if gate else 'warn')} {fc_core.fmt(acc['seconds']):>8}  {met}/{n} criteria met, "
            f"{len(acc.get('unclear', []))} unproven"
            + (f"  error={acc['error'][:120]}" if acc.get("error") else ""))
        for r in acc.get("criteria", []):
            if r["choice"] != "MET":
                flag = "NOT MET " if r in acc.get("failed", []) else ("unproven" if r in acc.get("suspects", []) else "unclear ")
                print(f"           {flag} p_met={r['p_met']:.2f} p_not={r['p_not_met']:.2f} [{r['task']}] {r['criterion'][:110]}")
        for r in acc.get("failed", []):
            if gate:
                findings.append(f"[high] acceptance criterion not met (task {r['task']}, p={r['p_not_met']}): {r['criterion']}")
        for r in acc.get("unclear", []):
            if gate:
                findings.append(f"[high] acceptance criterion not proven, judged {r['choice']} and not confirmed as a violation (task {r['task']}): {r['criterion']}")
    if e2e:
        ok &= e2e.result()
    pool.shutdown()
    if ok and tests is not None and cfg.get("checks"):  # the fix passed its own tests and every stage: no regression anywhere else
        fc_core.say("check  full   every check, once, after the fix passed every stage")
        fc_herdr.herdr_stage(panes, "checks", "working", "full checks")
        ok &= run_checks(cfg["checks"], report["checks"])
    fc_core.flag_home(home, "verify's checks and e2e")
    return ok, report, "\n\n".join(findings)

def verify_root(repo, proj, cfg):
    """Where verify runs. Task branches are never merged locally, so with unmerged layers verify runs in the CLI worktree
    checked out at the stack's top branch (fix commits then land on that layer, reviewed like everything else); the review
    base is the trunk. With no open layers it runs on the user's checkout against fc_worktree.review_base. A chain whose
    rebase stopped fails verify here, before any stage and with no result recorded."""
    trunk = fc_core.current_branch(repo)
    if not fc_worktree.stack_order(repo, proj):
        return repo, fc_worktree.review_base(repo, cfg) or trunk, None
    wt = fc_worktree.stack_worktree(repo, proj, trunk)
    chain = fc_layers.linearize(repo, proj, trunk, wt)
    if fc_layers.STACK_STOP:  # the top of a partial chain lacks every layer above the stop: a pass there would claim the feature
        fc_core.say(f"verify FAIL  nothing verified or recorded: {fc_layers.STACK_STOP}")
        sys.exit(1)
    if not chain:
        return repo, fc_worktree.review_base(repo, cfg) or trunk, None
    fc_core.sh(["git", "checkout", "-q", chain[-1]], wt)
    fc_worktree.ready_checkout(repo, wt, install=cfg.get("install"))
    fc_core.say(f"verify at    stack top {chain[-1]} ({len(chain)} layer(s) on {trunk}); fixes commit on that layer")
    return wt, trunk, wt

def at_root(value, olds, root):
    """`value` with every absolute path under one of `olds` (the project worktree, the main checkout) moved under `root`, in
    every string, inside dicts and lists too. One pass, longest prefix first, each matched as a whole path: a path already
    moved (the slot lives under the main checkout) is never moved again, and ~/code/app never matches ~/code/app-2/x.
    A project's `.compose/` is git-ignored: a path in it moves only when it exists under `root` (the link stack_worktree makes),
    else it stays where the file is, so an e2e driver kept in the project worktree is still found."""
    olds = sorted({str(o) for o in olds} - {str(root)}, key=len, reverse=True)
    if not olds:
        return value
    path = re.compile(r"(?<![\w.~-])(?:" + "|".join(map(re.escape, olds)) + r")(?=/|$|[\s\"'`;:&|()<>,=])")
    if isinstance(value, dict):
        return {k: at_root(v, olds, root) for k, v in value.items()}
    if isinstance(value, list):
        return [at_root(v, olds, root) for v in value]
    def moved(m):
        tail = re.match(r"/\.compose(?:/[^\s\"'`;:&|()<>,=]*)?", m.string[m.end():])
        return m.group(0) if tail and not Path(str(root) + tail.group(0)).exists() else str(root)
    return path.sub(moved, value) if isinstance(value, str) else value

def cmd_verify(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    fc_init.start_checks(repo, stack=False, tree=False)  # keys and machine only: verify tolerates a dirty tree
    fc_proc.keep_awake()  # a display that sleeps fails every e2e check, and a verify takes long enough for the Mac to sleep
    cfg_path = proj / "verify.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    review_only = getattr(a, "review_only", False)
    if review_only:
        a.fix = 0  # it only reports: the fix loop belongs to the full verify
    t0 = time.time()
    # Review, acceptance, and a fixer read the plan, the criteria, and the protected files from the Linear sync; checks and
    # e2e read only verify.json, so groundwork proves them before planning with --skip-review --fix 0.
    tasks = fc_tasks.load_tasks(proj, required=not a.skip_review or a.fix > 0,
                                hint=f"; checks and e2e alone run without one: `compose verify --project {proj.name} --skip-review --fix 0`")
    left_out = (["tasks"] if not tasks else []) + (["review"] if a.skip_review else []) + (["e2e"] if a.skip_e2e and not review_only else []) + (["checks", "e2e"] if review_only else [])
    fc_core.say(f"verify start project={proj.name} fix_rounds={a.fix}")
    rounds = []
    root, base, wt = verify_root(repo, proj, cfg)
    cfg = {**cfg, "review_base": base}
    if root != repo:
        # Checks and e2e cases (setup, driver, assert, env, every string) may name the main checkout or the project worktree
        # by absolute path; run them against the stack top.
        olds = (repo, fc_core.worktrees(repo)[0])
        cfg.update({k: at_root(cfg[k], olds, root) for k in ("checks", "e2e", "e2e_setup", "e2e_env") if k in cfg})
        cfg["main_repo"] = repo
    try:
        verify_rounds(root, proj, cfg, a, rounds, t0, left_out)
    except fc_models.PaymentRequired as e:
        fc_models.payment_halt(repo, proj, "verify", [], {"fix": a.fix, "skip_e2e": a.skip_e2e, "skip_review": a.skip_review}, e)
    finally:
        if wt is not None:
            fc_core.sh(["git", "checkout", "-q", "--detach", fc_core.current_branch(repo)], wt, check=False)  # free the top branch again

def fix_strays(touched, allowed, named=()):
    """Files a verify fix round may not touch. A fixer gets the same scope as the tasks: only files the stack already
    changes. With no stack diff (verify on a plain checkout) it is free except for lockfiles, which a fixer only rewrites
    when it is working around a broken environment, not fixing a finding. A lockfile a task names in `files:` is part of the work."""
    return [f for f in touched if f not in allowed and f not in named] if allowed else [f for f in touched if Path(f).name in fc_worktree.LOCKFILES and f not in named]

def fix_message(reply, files, conv=None):
    """The fixer's one-line description of its change; when it gave none, or one about the process, the files it changed.
    The tool's name counts only as a word of its own, so docker-compose, compose.yaml, or composer stay a real change."""
    line = next(iter((reply or "").strip().splitlines()), "").strip(" \"'`.")
    if line and len(line) <= 72 and not re.search(r"(?<![\w-])compose(?![\w.-])|verif|finding|wave|task|linear|round", line, re.I):
        return fc_core.typed(line, "fix", conv)
    return fc_core.typed("Fix " + ", ".join(Path(f).name for f in files[:3]), "fix", conv)

def changed_files(repo):
    """Each file differing from HEAD, tracked or untracked (not ignored), with its digest; never the agent wiring (fc_worktree.WIRING)."""
    out = lambda *c: fc_core.sh(["git", *c, "-z"], repo, check=False).stdout.split("\0")
    files = set(out("diff", "--name-only", "--no-renames", "HEAD") + out("ls-files", "--others", "--exclude-standard"))
    return fc_core.digests(repo, sorted(files - {"", *fc_worktree.WIRING}))

def verify_rounds(repo, proj, cfg, a, rounds, t0, left_out=()):
    base = fc_worktree.review_base(repo, cfg)
    allowed = set(fc_core.sh(["git", "diff", "--name-only", f"{base}...HEAD"], repo, check=False).stdout.splitlines()) if base else set()
    dirty = fc_worktree.dirty_paths(repo)  # the user's own changes, read before any stage: what a check leaves behind is verify's
    rejected, tests = [], None  # the first round runs the full checks; a fix round only the tests of what its fix changed
    for rnd in range(a.fix + 1):
        if cfg.get("main_repo"):  # a fix round may have changed the lockfile
            fc_worktree.ready_checkout(cfg["main_repo"], repo, install=cfg.get("install"))
        ok, report, findings = run_stages(repo, proj, cfg, a, tests)
        rounds.append(report)
        if ok or rnd == a.fix:
            break
        if not findings.strip():
            fc_core.say("fix    skip  only tool errors failed (see TOOL ERROR above); nothing for a fixer to change in the app")
            break
        # Fix loop: hand confirmed findings to the fast implementer in the repo itself, then re-run every stage.
        if dirty and rnd == 0:
            fc_core.say(f"fix    skip  repo has uncommitted changes ({', '.join(dirty[:5])}); commit first so a bad fix can be reverted")
            break
        _, _, _, protected = review_inputs(repo, proj, cfg)
        before, pending = fc_core.digests(repo, protected), changed_files(repo)
        t1 = time.time()
        model = cfg.get("fix_model") or os.environ.get("COMPOSE_FIX_MODEL") or fc_config.DEFAULT_MODEL
        if rnd and fc_models.fallback_for(model):  # the first fix did not clear the findings; the fallback takes later rounds
            model = fc_models.fallback_for(model)
        fc_core.say(f"fix    start round {rnd + 1}  model={model}")
        pack = fc_implement.trail_pack(repo, findings[:400])
        prompt = (f"REPOSITORY ROOT: {repo}\nEvery edit must be under that root.\n\n" +
                  (f"CONTEXT PACK from trail (exact file:line). Use it instead of exploring.\n{pack}\n\n" if pack else "") +
                  "Verification of this repository failed. Fix ONLY the findings below with the smallest change. "
                  f"Do not edit these files: {', '.join(protected) or 'none'}. Do not weaken or delete tests. "
                  "Keep behavior the tests already cover. Keep the code simple; do not restructure; " + SIMPLICITY_BAR.replace("no hardening.", "no hardening beyond the findings.") + " "
                  + (f"DESIGN CONTEXT (authoritative; never contradict it): {cfg['review_context']} " if cfg.get("review_context") else "") +
                  "Fix the app for a real user, never for the test harness: do not add labels, text, attributes, or "
                  "shortcuts aimed at the test bot or the e2e script; if a finding is the harness's fault, change nothing. "
                  "Do not run tests or checks: after your turn verify runs the tests of what you changed, and every check once the rest passes. Do not explain, just edit; your whole reply is one line, "
                  "a plain description of the change you made (like 'Save submissions in one transaction'), never about this process.\n\nFINDINGS:\n" + findings[:30000])
        try:
            _, reply, tools, usage = fc_implement.implementer(repo, model, prompt)
        except fc_models.RateLimited as e:
            fc_core.say(f"fix    {e.why}; " + (f"retrying on {fc_models.fallback_for(model)}" if fc_models.fallback_for(model) else "waiting 30s and retrying once"))
            if not fc_models.fallback_for(model):
                time.sleep(30)
            try:
                _, reply, tools, usage = fc_implement.implementer(repo, fc_models.fallback_for(model) or model, prompt)
            except fc_models.PaymentRequired:
                raise
            except Exception as e2:  # noqa: BLE001
                reply, tools, usage = f"fix call failed: {e2}", 0, {"cost": 0.0}
        except fc_models.PaymentRequired:
            raise
        except Exception as e:  # noqa: BLE001
            reply, tools, usage = f"fix call failed: {e}", 0, {"cost": 0.0}
            if fc_models.fallback_for(model):
                fc_core.say(f"fix    {model} errored; retrying on {fc_models.fallback_for(model)}")
                try:
                    _, reply, tools, usage = fc_implement.implementer(repo, fc_models.fallback_for(model), prompt)
                except fc_models.PaymentRequired:
                    raise
                except Exception as e2:  # noqa: BLE001
                    reply, tools, usage = f"fix call failed: {e2}", 0, {"cost": 0.0}
        tampered = [f for f, d in fc_core.digests(repo, protected).items() if d != before[f]]
        if tampered:
            fc_core.sh(["git", "checkout", "--"] + tampered, repo, check=False)
            fc_core.say(f"fix    reverted protected files the fixer touched: {', '.join(tampered)}")
        fixed = [f for f, d in changed_files(repo).items() if f not in pending or pending[f] != d]  # its turn's change alone: no check's leftovers
        added = set(fc_core.sh(["git", "ls-files", "--others", "--exclude-standard", "-z"], repo).stdout.split("\0")) & set(fixed)
        new_docs = [f for f in fixed if f in added and fc_config.DOC_RE.search(f)]
        for f in new_docs:  # fixers, like implementers, never add documents
            (repo / f).unlink()
        if new_docs:
            fc_core.say(f"fix    removed documents the fixer added: {', '.join(new_docs)}")
        fixed = [f for f in fixed if f not in new_docs]
        stray = fix_strays(fixed, allowed, {f for t in fc_tasks.code_tasks(fc_tasks.load_tasks(proj)) for f in t["files"]})
        if stray:
            # The whole round goes: an out-of-scope edit means the fixer worked around something (an install, the toolchain)
            # instead of fixing a finding, and its other edits rest on that. The last stage run failed, so verify ends FAIL.
            if set(fixed) - added:
                fc_core.sh(["git", "--literal-pathspecs", "checkout", "-q", "HEAD", "--", *sorted(set(fixed) - added)], repo)
            for f in added & set(fixed):
                (repo / f).unlink()
            rejected.append({"round": rnd + 1, "files": stray})
            fc_core.say(f"fix    REJECTED round {rnd + 1}: touched files outside the stack ({', '.join(stray[:8])}); reverted the round")
            break
        fc_core.say(f"fix    done  {fc_core.fmt(time.time() - t1):>8}  tools={tools} changed={'yes' if fixed else 'no'}  ${usage['cost']:.4f}")
        if fixed:
            fc_core.sh(["git", "--literal-pathspecs", "add", "-A", "--", *fixed], repo)
            fc_core.sh(["git", "--literal-pathspecs", "commit", "-qm", fix_message(reply, fixed, fc_core.commit_convention(proj)), "--", *fixed], repo, check=False)
            fc_core.say("fix    committed on " + (fc_core.sh(["git", "branch", "--show-current"], repo, check=False).stdout.strip() or "HEAD"))
            tests = fix_tests(fc_tasks.load_tasks(proj), fixed)
            if tests is None:
                fc_core.say("fix    scope  the fix changed a file no task names; the next round runs the full checks")
        else:
            break
    final = {"rounds": rounds, "passed": ok, "rejected_fixes": rejected, "seconds": round(time.time() - t0, 1), "cost": fc_core.LEDGER.snapshot()}
    if left_out:
        final["left_out"] = left_out
    (proj / "results").mkdir(exist_ok=True)
    review_only = getattr(a, "review_only", False)  # its own record: neither the last verify's nor a smoke run's
    fc_core.atomic_write((proj / "results" / ("review.json" if review_only else "smoke.json" if left_out else "verify.json")), json.dumps(final, indent=2))
    (proj / "results" / "resume.json").unlink(missing_ok=True)
    fc_core.say((f"review {'PASS' if ok else 'FAIL'} (review and acceptance only; the full verify runs the checks and e2e)" if review_only else
                 f"smoke {'PASS' if ok else 'FAIL'} ({', '.join('no ' + x for x in left_out)})" if left_out else f"verify {'PASS' if ok else 'FAIL'}")
                + f"  wall {fc_core.fmt(final['seconds'])}  rounds={len(rounds)}")
    if ok and not left_out:
        fc_linear.linear_reconcile(proj, verified=True)
    fc_core.say(fc_core.LEDGER.line())
    if not ok and not left_out:  # a smoke run is a sign of life only; its findings never reach the reflect screen
        print("\nUnresolved after the fix budget. Escalate to the team lead with the confirmed findings above.")
        verify_failed(proj, rounds, findings)
    sys.exit(0 if ok else 1)
