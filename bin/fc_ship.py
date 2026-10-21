"""Shipping a verified stack: check every layer before it is submitted, reword its commits, land it on the base."""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
import fc_core, fc_worktree, fc_layers, fc_stack, fc_jev, fc_verify, fc_update

LAND_POLL = 20      # seconds between looks at a pull request that is not ready yet
LAND_SETTLE = 15    # seconds after a push before its required checks are read: GitHub registers them a moment later
LAND_METHODS = ("squash", "merge", "rebase")

def layer_checks(repo, proj, layers, trunk, wt):
    """The gate on a submit: verify.json `checks` (the cheap ones, never e2e) on each layer's own tree, bottom up, in the CLI's
    worktree. The first layer that fails is the reason returned, with nothing pushed; "" when every layer passes. A layer
    that passed once is not run again while its tip and the checks stay the same."""
    cfg = fc_core.project_config(proj)
    checks = cfg.get("checks") or []
    if not checks:
        fc_core.say("layers no checks in verify.json: the layers are not checked before submit")
        return ""
    checks = fc_verify.at_root(checks, (repo, fc_core.worktrees(repo)[0]), wt)
    kept = Path(proj) / "results" / "layer-checks.json"
    seen = json.loads(kept.read_text()) if kept.exists() else {}
    stamp = hashlib.sha1(json.dumps(checks).encode()).hexdigest()[:12]
    for i, l in enumerate(layers, 1):
        tip = fc_core.sh(["git", "rev-parse", l["branch"]], repo).stdout.strip()
        name = f"layer {i} of {len(layers)} ({l['branch']})"
        if seen.get(l["branch"]) == f"{tip}:{stamp}":
            fc_core.say(f"layers ok    {name}  unchanged since its checks passed")
            continue
        fc_core.sh(["git", "checkout", "-q", "--detach", tip], wt)
        fc_worktree.ready_checkout(repo, wt, install=cfg.get("install"))
        for c in checks:
            t1 = time.time()
            for attempt in (1, 2):
                try:
                    p = fc_core.sh(c, wt, timeout=900, check=False, env=fc_core.clean_env())
                    out = fc_core.scrub(p.stdout + p.stderr)[-3000:]
                except subprocess.TimeoutExpired:
                    p, out = subprocess.CompletedProcess(c, 124), "timed out after 900s"
                if not (p.returncode and attempt == 1 and fc_jev.tool_error(out)):
                    break
                fc_core.say(f"layers tool error; retrying once  {c}")
            fc_core.say(f"layers {'ok  ' if p.returncode == 0 else 'FAIL'} {fc_core.fmt(time.time() - t1):>8}  {name}  {c}")
            if p.returncode:
                return (f"{name} fails `{c}` on its own tree" + (f":\n{out[-800:]}\n" if out.strip() else ". ") +
                        f"Nothing was pushed. A layer must pass without the layers above it: put what it needs in this layer or below "
                        f"(a task's `after`), fix it, then run `compose stack --submit` again")
        seen[l["branch"]] = f"{tip}:{stamp}"
        fc_core.atomic_write(kept, json.dumps(seen, indent=2))
    return ""

def cmd_stack(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    trunk = a.trunk or fc_core.current_branch(repo)
    fc_update.refuse_while_verifying(proj, repo)
    if not fc_stack.register_stack(repo, proj, trunk, submit=a.submit, preview=not a.submit, gate=layer_checks):
        if fc_layers.STACK_STOP:
            sys.exit(1)  # the STOP line already said why and what to do
        print("stack  nothing to register: no unmerged task branches")

def layer_commits(repo, proj, trunk):
    """[(branch, [commit, ...])] bottom first: each layer's own commits, oldest first."""
    out, below = [], fc_stack.layer_base(repo, proj, trunk)
    for b in fc_layers.layer_branches(repo, proj):
        out.append((b, fc_core.sh(["git", "rev-list", "--reverse", f"{below}..{b}"], repo).stdout.split()))
        below = b
    return out

def cmd_reword(a):
    """List the stack's commits with the ones that break the commit rules flagged; with --set SHA=MESSAGE, choose a commit's
    message and rebuild the layers with it. The choice is kept by the commit (author, date, files), so every later rebuild
    applies it. Layers are rebuilt in compose's own worktree; nothing is pushed."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    trunk = a.trunk or fc_core.current_branch(repo)
    conv = fc_core.commit_convention(proj)
    layers = layer_commits(repo, proj, trunk)
    if not layers:
        fc_core.say("reword nothing to reword: no layers; `compose stack` builds them")
        sys.exit(1)
    subject = lambda c: fc_core.sh(["git", "show", "-s", "--format=%s", c], repo).stdout.strip()
    prefix = fc_layers.layer_prefix(repo, proj)
    show = lambda: [print(f"  {b.removeprefix(prefix)}  {c[:9]}  {subject(c)}"
                          + (f"   <- {why}" if (why := fc_layers.message_problem(fc_core.sh(['git', 'show', '-s', '--format=%B', c], repo).stdout, conv)) else ""))
                    for b, cs in layers for c in cs]
    if not a.set:
        show()
        print(f"reword set one with `compose reword --project {proj.name} --set <sha>=<message>`; `compose stack` also rewrites a flagged message on its own")
        return
    fc_update.refuse_while_verifying(proj, repo)
    every = [c for _, cs in layers for c in cs]
    chosen = dict(fc_layers.rewords(proj))
    for item in a.set:
        sha, _, message = item.partition("=")
        hits = [c for c in every if sha and c.startswith(sha)]
        if len(hits) != 1:
            fc_core.say(f"reword FAIL  {sha!r} names {len(hits)} commits of the stack; `compose reword --project {proj.name}` lists them")
            sys.exit(1)
        why = "" if a.as_is else fc_layers.message_problem(message, conv)
        if why:
            fc_core.say(f"reword FAIL  {message.splitlines()[0] if message.strip() else '(empty)'!r}: {why}")
            sys.exit(1)
        chosen[fc_layers.commit_key(repo, hits[0])] = {"message": message.strip(), "was": subject(hits[0])}
    fc_core.atomic_write(Path(proj) / "rewords.json", json.dumps(chosen, indent=2))
    if not fc_stack.register_stack(repo, proj, trunk):
        fc_core.say("reword the choice is kept, but the layers were not rebuilt" + (f": {fc_layers.STACK_STOP}" if fc_layers.STACK_STOP else ""))
        sys.exit(1)
    layers = layer_commits(repo, proj, trunk)
    show()
    print("reword layers rebuilt, nothing pushed. A layer that already has a PR is pushed with its new commits by the next `compose stack --submit`")

def gh(args, cwd):
    """A gh call that can never stop to ask: no prompt, no stdin."""
    return subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          env={**os.environ, "GH_PROMPT_DISABLED": "1"})

def pr_info(which, cwd):
    """The pull request for a PR number or a head branch, or None."""
    p = gh(["pr", "view", str(which), "--json", "number,baseRefName,state,isDraft,headRefOid,url,mergeStateStatus"], cwd)
    try:
        return json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        return None

def required_checks(n, cwd):
    """'pass' | 'pending' | 'none' (no required checks) | 'fail: <names>' | 'error: <gh's words>' for a PR's required checks."""
    p = gh(["pr", "checks", str(n), "--required", "--json", "name,bucket"], cwd)
    try:
        rows = json.loads(p.stdout)
    except ValueError:
        text = (p.stdout + p.stderr).strip()
        return "none" if "no required checks" in text.lower() or "no checks reported" in text.lower() else f"error: {text[-200:]}"
    bad = [r.get("name", "?") for r in rows if r.get("bucket") in ("fail", "cancel")]
    if bad:
        return "fail: " + ", ".join(bad)
    return "pending" if any(r.get("bucket") == "pending" for r in rows) else ("pass" if rows else "none")

def wait(probe, deadline):
    """probe() until it returns something but None, LAND_POLL seconds apart; None once the deadline passes."""
    while True:
        r = probe()
        if r is not None:
            return r
        if time.time() >= deadline:
            return None
        time.sleep(LAND_POLL)

def land_layer(repo, wt, i, b, prev, rec, base, method, minutes):
    """Land layer b (index i). "" when it is merged, else why it stopped. A layer above the first has lost its parent to the
    merge: it is rebased onto the base (from the tip its parent had when the land began), its PR retargeted, and pushed with a
    lease on the commit compose last saw there. Every remote change waits for the layer's own required checks."""
    n, deadline = rec["pr"][b], time.time() + minutes * 60
    tip = lambda: fc_core.sh(["git", "rev-parse", b], repo).stdout.strip()
    info = pr_info(n, repo)
    if not info:
        return f"{b}: gh cannot read PR #{n}"
    if info["state"] == "MERGED":
        fc_core.say(f"land   skip  #{n} {b} is already merged")
        return ""
    if info["state"] != "OPEN":
        return f"PR #{n} ({b}) is {info['state'].lower()}, not open"
    old, pushed = tip(), False
    if prev:
        if fc_core.sh(["git", "merge-base", "--is-ancestor", prev, old], repo, check=False).returncode == 0:  # not rebased yet
            fc_core.sh(["git", "fetch", "-q", "origin", base], wt)
            fc_core.sh(["git", "checkout", "-q", "--detach", b], wt)
            r = fc_core.sh(["git", "rebase", "-q", "--onto", f"origin/{base}", prev], wt, check=False)
            if r.returncode:
                files = fc_core.sh(["git", "diff", "--name-only", "--diff-filter=U"], wt, check=False).stdout.split()
                fc_core.sh(["git", "rebase", "--abort"], wt, check=False)
                return f"{b} conflicts with {base} in {', '.join(files) or 'files git does not name'} after its parent merged; resolve it by hand, nothing of it was pushed"
            fc_core.sh(["git", "branch", "-f", b, fc_core.sh(["git", "rev-parse", "HEAD"], wt).stdout.strip()], repo)
    new = tip()
    if info["headRefOid"] not in (old, new):
        return f"PR #{n} ({b}) has commits compose did not push ({info['headRefOid'][:9]}, local {new[:9]}); `compose stack --submit` first"
    if prev and info["baseRefName"] != base:
        fc_core.say(f"land   edit  #{n} base {info['baseRefName']} -> {base}")
        q = gh(["pr", "edit", str(n), "--base", base], repo)
        if q.returncode:
            return f"gh pr edit #{n}: {(q.stderr or q.stdout).strip()[-200:]}"
    if info["headRefOid"] != new:
        fc_core.say(f"land   push  {b} {new[:9]} (was {info['headRefOid'][:9]})")
        q = fc_core.sh(["git", "push", "-q", f"--force-with-lease={b}:{info['headRefOid']}", "origin", f"{b}:{b}"], repo, check=False)
        if q.returncode:
            return f"push of {b} refused: {q.stderr.strip()[-200:]}"
        pushed = True
    if info["isDraft"]:
        fc_core.say(f"land   ready #{n}")
        gh(["pr", "ready", str(n)], repo)
    for _ in range(2):  # a second round when the base moved on while the checks ran
        if wait(lambda: True if (pr_info(n, repo) or {}).get("headRefOid") == new else None, deadline) is None:
            return f"PR #{n} ({b}) never showed {new[:9]} as its head"
        if pushed:
            time.sleep(LAND_SETTLE)
        status = wait(lambda: None if (s := required_checks(n, repo)) == "pending" else s, deadline)
        if status is None:
            return f"required checks on #{n} ({b}) still pending after {minutes} minutes; re-run to resume"
        if status.startswith(("fail", "error")):
            return f"required checks on #{n} ({b}): {status}"
        fc_core.say(f"land   checks #{n} {status}")
        if (pr_info(n, repo) or {}).get("mergeStateStatus") != "BEHIND":
            break
        fc_core.say(f"land   update #{n} is behind {base}; gh pr update-branch")
        q = gh(["pr", "update-branch", str(n), "--rebase"], repo)
        if q.returncode:
            return f"gh pr update-branch #{n}: {(q.stderr or q.stdout).strip()[-200:]}"
        moved = lambda: (h if (h := (pr_info(n, repo) or {}).get("headRefOid")) != new else None)
        new = wait(moved, deadline) or new
        pushed = True
    q = gh(["pr", "merge", str(n), f"--{method}"], repo)
    if q.returncode:
        return f"gh pr merge #{n} ({b}): {(q.stderr or q.stdout).strip()[-300:]}"
    if wait(lambda: True if (pr_info(n, repo) or {}).get("state") == "MERGED" else None, deadline) is None:
        return f"#{n} ({b}) was asked to merge but is not merged after {minutes} minutes; re-run to resume"
    fc_core.say(f"land   merged #{n} {b} ({method})")
    return ""

def cmd_land(a):
    """Merge the submitted stack into its base, bottom up, one `gh pr merge` per PR. It pushes and merges on GitHub, so without
    --yes it only prints the plan."""
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    trunk = a.trunk or fc_core.current_branch(repo)
    method = a.method or fc_core.project_config(proj).get("land_method") or "squash"
    names = fc_layers.layer_branches(repo, proj)
    stop = lambda why: (fc_core.say(f"land   STOP  {why}"), sys.exit(1))
    if not names:
        stop("no layers: `compose stack --submit` builds and submits them")
    base = fc_stack.layer_base(repo, proj, trunk)
    kept = Path(proj) / "results" / "land.json"
    rec = json.loads(kept.read_text()) if kept.exists() else {}
    if set(rec.get("orig", {})) != set(names):
        rec = {"orig": {b: fc_core.sh(["git", "rev-parse", b], repo).stdout.strip() for b in names}, "pr": {}}
    infos = {b: pr_info(rec["pr"].get(b) or b, repo) for b in names}
    missing = [b for b in names if not infos[b]]
    if missing:
        stop(f"{', '.join(missing)} has no pull request: `compose stack --submit` first")
    rec["pr"] = {b: infos[b]["number"] for b in names}
    print(f"land   plan  {len(names)} layer(s) into {base} by {method}, bottom up:")
    for i, b in enumerate(names, 1):
        i_ = infos[b]
        print(f"  {i}  {b}  #{i_['number']}  {i_['state'].lower()}{' (draft)' if i_['isDraft'] else ''}  {i_['url']}")
    print(f"  for each: mark it ready, wait up to {a.timeout:g} min for its required checks, `gh pr merge --{method}`;\n"
          f"  after each: rebase the next layer onto origin/{base}, retarget its PR to {base}, push it with --force-with-lease")
    if not a.yes:
        print(f"land   nothing was merged or pushed. Re-run with --yes once the user has said to land this stack")
        return
    fc_update.refuse_while_verifying(proj, repo)
    wt = fc_worktree.stack_worktree(repo, proj, trunk)
    fc_core.atomic_write(kept, json.dumps(rec, indent=2))
    try:
        for i, b in enumerate(names):
            if why := land_layer(repo, wt, i, b, rec["orig"][names[i - 1]] if i else None, rec, base, method, a.timeout):
                stop(f"{why}. Layers below it are merged; re-run `compose land` to resume")
    finally:
        fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
    kept.unlink(missing_ok=True)
    print(f"land   done  {len(names)} layer(s) merged into {base}\nnext: compose clean --project {proj.name}")
