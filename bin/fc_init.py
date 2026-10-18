import json, os, re, shutil, subprocess, sys
from pathlib import Path
import fc_auth, fc_config, fc_core, fc_steps, fc_tasks, fc_linear, fc_herdr, fc_worktree, fc_layers, fc_crew


TRAIL_INIT = ["trail", "init", "--no-agents", "--no-global", "--no-build"]  # Claude Code wiring only, nothing outside the repo

def existing_repo(wt):
    """True when the repository already has code: a tracked file beyond a README, a license, or git's own dotfiles."""
    files = fc_core.sh(["git", "ls-files"], wt, check=False).stdout.split()
    return any(not re.match(r"(?i)(readme|licen[cs]e|\.git)", Path(f).name) for f in files)

def setup_trail(wt):
    """An existing repo gets trail before anyone reads its code: wired for Claude Code (unless that would touch a tracked
    file) and built. trail's files stay out of git through info/exclude. Safe to run again."""
    if os.environ.get("COMPOSE_NO_TRAIL"):
        return fc_core.say("trail    skipped: COMPOSE_NO_TRAIL is set")
    if not existing_repo(wt):
        return fc_core.say("trail    skipped: a new repository has no code to map yet")
    if not shutil.which("trail"):
        return fc_core.say(f"trail    not installed: `{TRAIL_INSTALL}`, then `compose trail --project <slug>`")
    if not (wt / ".trail" / "hook.cjs").exists():
        p = fc_core.sh(TRAIL_INIT + ["--dry-run", str(wt)], wt, timeout=120, check=False)
        dry = p.stdout + p.stderr  # trail prints the list on stderr
        section = dry.split("this repo:", 1)[1].split("\n\n", 1)[0] if "this repo:" in dry else ""
        paths = sorted(set(re.findall(r"^\s+(\S+)", section, re.M)))
        tracked = [f for f in paths if fc_core.sh(["git", "ls-files", "--error-unmatch", f], wt, check=False).returncode == 0]
        if tracked:
            fc_core.say(f"trail    init skipped: it would edit tracked {', '.join(tracked)}; building the graph only")
        else:
            fc_core.sh(TRAIL_INIT + [str(wt)], wt, timeout=300, check=False)
            fc_worktree.exclude_paths(wt, ["/" + f for f in paths])
            fc_core.say(f"trail    wired for Claude Code ({len(paths)} files, kept out of git)")
    fc_worktree.exclude_paths(wt, ["/graft/", "/.trail/", "/.claude/settings.json", "/.claude/settings.local.json"])  # the graph and wiring, also when trail runs without init
    fc_worktree.stamp_trail_wiring(wt)
    (wt / ".trail" / "cache").mkdir(parents=True, exist_ok=True)  # trail build puts the map in graft/ unless .trail/cache/ exists first
    fc_core.sh(["trail", "build", "--no-gitignore", "--no-ignore", str(wt)], wt, timeout=600, check=False)
    fc_core.say("trail    graph built")

def cmd_trail(a):
    """Set trail up in the project's worktree again (after installing trail, or to rebuild the graph)."""
    setup_trail(fc_herdr.project_worktree(fc_core.project_dir(a)))

TRAIL_INSTALL = "npm i -g @trailhq/trail-code"

def check_deps(role=None):
    """Print one `MISSING: <name>[: <detail>] (install: <command>)` line per setup step that is not ok, without any network call;
    a key row names the key and its fix, never a value. herdr's config is one more row (loud toasts or sounds are the detail),
    optional, fixed by `compose setup`. While `claude` itself is missing, the rows that need it share one `waiting on Claude Code:`
    line instead of a MISSING line each (they still count as missing when required). Returns the required steps that are missing:
    those stop `init`; the optional ones only warn. With no role the designer rows are opt-in: a miss among them gets one
    `designer extras not set up: compose setup, choose the designer rows` line instead, never the waiting line, never returned.
    With a role, only what that role needs is checked, and it is required (Framelink stops the designer's start)."""
    bad, waiting, designer = [], [], False
    checkout = Path(__file__).resolve().parents[1]
    claude = bool(shutil.which("claude"))
    for row in (*fc_steps.STEPS, ("herdr config", lambda co: herdr_loud(), "compose setup", "default", False, "run")):
        name, _, install, needed, needs_claude, mode = row
        if role and needed != role:
            continue
        required = needed == "required" or (role is not None and needed == role)
        ok, detail = fc_steps.check(row, checkout)
        if not ok:
            if needed == "designer" and role is None:
                designer = True
                continue
            if needs_claude and not claude:
                waiting.append(name)
                if required:
                    bad.append(name)
                continue
            note = "" if required else " - optional"
            why = "" if mode == "key" else f": {detail}" if detail else ""
            print(f"MISSING: {name}{why} (install: {install}){note}")
            if required:
                bad.append(name)
    if designer:
        print("designer extras not set up: compose setup, choose the designer rows")
    if waiting:
        print("waiting on Claude Code: " + ", ".join(waiting))
    return bad

def herdr_toml(path):
    """The `[section] key = value` pairs of herdr's config.toml as {"section.key": "value"}, quotes stripped: the few flat keys
    compose reads, without tomllib (the Python 3.9 macOS ships has none). Unreadable is empty."""
    vals, section = {}, ""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return vals
    for line in lines:
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        if m := re.match(r"\[([\w.-]+)\]$", line):
            section = m.group(1)
        elif m := re.match(r"([\w.-]+)\s*=\s*(.+)$", line):
            vals[f"{section}.{m.group(1)}".lstrip(".")] = m.group(2).strip().strip("\"'")
    return vals

def herdr_loud():
    """(ok, detail) for the herdr config row: not ok when herdr's own toasts or sounds would reach the product owner from every
    agent, with the loud keys as the detail; `[ui.toast] delivery` off is herdr's default, `[ui.sound] enabled` false is not, and an
    absent file counts as the defaults."""
    cfg = herdr_toml(Path.home() / ".config" / "herdr" / "config.toml")
    loud = [(key, cfg.get(key, default)) for key, quiet, default in (("ui.toast.delivery", "off", "off"), ("ui.sound.enabled", "false", "true"))
            if cfg.get(key, default) != quiet]
    return (False, ", ".join(f"{k}={v}" for k, v in loud)) if loud else (True, "")

def herdr_toast_warning():
    """One line when herdr's own toasts or sounds are on, for the product owner to read: herdr then alerts them for every agent
    that finishes or needs input, in every pane, while compose already sends the engineering manager's one alert itself
    (desktop_notify). None when quiet."""
    ok, loud = herdr_loud()
    if ok:
        return None
    return ("WARNING: herdr alerts the product owner for every agent, not only the engineering manager (" + loud
            + '): set [ui.toast] delivery = "off" and [ui.sound] enabled = false in ~/.config/herdr/config.toml; '
            "compose sends the engineering manager's alert itself")

def cmd_doctor(a):
    """Check every tool and skill file compose depends on; print every line first, then exit 1 when a required one is missing.
    Warns, never stops, when a key still sits in config.json or .env: it differs from the key auth.json holds, so it was left
    there - remove the one you do not want. herdr's loud toasts or sounds are one optional row of check_deps, fixed by `compose setup`."""
    bad = check_deps()
    if shutil.which("gh") and fc_core.sh(["gh", "auth", "status"], Path.home(), check=False, timeout=20).returncode != 0:
        print("WARNING: gh is not logged in: compose bug reports are saved, not filed on GitHub (run: gh auth login)")
    for name, path in fc_auth.old_keys(fc_config.CONFIG_PATH, fc_config.ENV_FILE):
        print(f"WARNING: {name} in {fc_core.tilde(path)} differs from the key auth.json holds, so it was kept: remove the one you do not want")
    if bad:
        modes = {row[0]: row[5] for row in fc_steps.STEPS}  # setup fixes every mode but manual
        print(f"{len(bad)} required step{'s' if len(bad) > 1 else ''} missing"
              + (": run compose setup" if any(modes.get(n) != "manual" for n in bad) else ""))
        sys.exit(1)
    print("every step compose needs is ready")

def move_onto(wt, proj, after, after_name):
    """Build an existing project on another project's branch (`init --after`): allowed while the project has no commits of its own
    (init's own "Ignore local tool directories" one aside) and its worktree is clean, then its branch is reset to `after` and
    verify.json stores the review base and `after`. Exits with the reason otherwise, so the flag is never silently ignored."""
    cfg = fc_core.project_config(proj)
    if cfg.get("review_base") == after:
        return
    branch = fc_core.project_branch(proj)
    base = cfg.get("review_base", "main")
    if fc_core.sh(["git", "branch", "--show-current"], wt, check=False).stdout.strip() != branch:
        sys.exit(f"{wt} is not on {branch}: check it out, then run init --after again")
    log = fc_core.sh(["git", "log", "--format=%s", f"{base}..{branch}"], wt, check=False)
    if log.returncode != 0:
        sys.exit(f"cannot tell what {branch} holds beyond {base}, so --after {after_name} cannot move it: {log.stderr.strip()}")
    own = [s for s in log.stdout.splitlines() if not s.endswith("Ignore local tool directories")]
    if own:
        sys.exit(f"project {proj.name} has {len(own)} commit{'s' if len(own) > 1 else ''} of its own on {branch}, so --after {after_name} cannot move it: "
                 f"rebase it onto {after} yourself, or start the project again")
    if fc_core.sh(["git", "status", "--porcelain"], wt, check=False).stdout.strip():
        sys.exit(f"{wt} has uncommitted changes, so --after {after_name} cannot move {branch}: commit or discard them first")
    fc_core.sh(["git", "reset", "-q", "--hard", after], wt)
    fc_core.atomic_write(proj / "verify.json", json.dumps({**cfg, "review_base": after, "after": after_name}, indent=2))
    print(f"branch {branch} moved onto {after}")

def cmd_init(a):
    """Create the project's worktree `../compose-<name>` on its branch (`compose/<name>`, or --branch; from the branch the user is on,
    or with --after from another project's branch, for a feature that needs that feature's code), with the
    `.compose/<name>/` config beside it, ignored and never committed. The user's checkout is never touched again by this project."""
    bad = check_deps()  # before anything is created: a missing required tool stops here
    tools = {row[0] for row in fc_steps.STEPS if not callable(row[1])}  # a tool row: command, command list, or file under home
    if stop := [n for n in bad if n in tools]:
        sys.exit(f"init stopped: {', '.join(stop)} missing; install what is missing above, then run it again (`compose doctor` checks again)")
    here = Path(a.repo).resolve()
    name = a.project
    prefix = fc_config.settings(fc_config.read_config())[1].get("branch_prefix", "compose/")
    branch = a.branch or prefix + name
    if a.branch and fc_core.sh(["git", "check-ref-format", "--branch", a.branch], here, check=False).returncode != 0:
        sys.exit(f"{a.branch!r} is not a valid branch name")
    if a.branch and a.here:
        sys.exit("--branch names the project's own worktree branch; it does not combine with --here")
    other = fc_core.all_projects(here).get(a.after) if a.after else None
    after = fc_core.project_branch(other[1]) if other else (prefix + a.after if a.after else None)
    if after and a.here:
        sys.exit("--after builds a project on another project's branch in its own worktree; it does not combine with --here")
    if after and fc_core.sh(["git", "rev-parse", "--verify", "-q", after], here, check=False).returncode != 0:
        sys.exit(f"no branch {after}: `compose init --project {a.after}` that project first")
    existing = fc_core.all_projects(here).get(name)
    if existing:
        wt, proj = existing
        print(f"project {name} already exists at {wt}")
        old = fc_core.project_branch(proj)
        if a.branch and a.branch != old:  # move the project to a new branch name: rename in git, store it, repoint projects built on it
            if fc_core.sh(["git", "rev-parse", "--verify", "-q", a.branch], wt, check=False).returncode == 0:
                sys.exit(f"branch {a.branch} exists already")
            fc_core.sh(["git", "branch", "-m", old, a.branch], wt)
            for _, (_, p) in fc_core.all_projects(here).items():
                cfg = fc_core.project_config(p)
                if p == proj or cfg.get("review_base") == old:
                    fc_core.atomic_write((p / "verify.json"), json.dumps({**cfg, **({"branch": a.branch} if p == proj else {"review_base": a.branch, "after": fc_core.project_after(p)})}, indent=2))
            print(f"branch {old} renamed to {a.branch}")
        if after:
            move_onto(wt, proj, after, a.after)
    elif a.here:
        wt, proj = here, here / ".compose" / name
    else:
        base = after or fc_core.current_branch(here)
        if fc_core.sh(["git", "rev-parse", "--verify", "-q", branch], here, check=False).returncode != 0:
            fc_core.sh(["git", "branch", branch, after or "HEAD"], here)
        if fc_worktree.use_treehouse():
            wt = fc_worktree.slot_on(here, branch, f"compose:{name}:project")
        else:
            if not shutil.which("treehouse"):
                print(f"treehouse is not installed, so the project gets a plain git worktree; for a reusable pool install it: {fc_worktree.TREEHOUSE_INSTALL}")
            wt = here.parent / f"compose-{name}"
            if wt.exists():
                sys.exit(f"{wt} exists already; remove it or pass --here")
            fc_core.sh(["git", "worktree", "add", "-q", str(wt), branch], here)
        proj = wt / ".compose" / name
        print(f"worktree {wt}  branch {branch} (from {base})")
    if fc_worktree.ignore_tool_files(wt):
        fc_core.sh(["git", "add", ".gitignore"], wt)
        fc_core.sh(["git", "commit", "-qm", fc_core.typed("Ignore local tool directories", "deps", fc_core.commit_convention(proj))], wt, check=False)
    (proj / "results").mkdir(parents=True, exist_ok=True)
    setup_trail(wt)
    repo_link = here / ".compose" / "linear.json"  # the repo's Linear project, written in the user's checkout (step 0)
    if repo_link.exists() and not (wt / ".compose" / "linear.json").exists():
        (wt / ".compose" / "linear.json").write_text(repo_link.read_text())
    if not (proj / "verify.json").exists():
        fc_core.atomic_write((proj / "verify.json"), json.dumps({
            "checks": [], "docs": ["README.md"], "e2e": [],
            "review": True, "perspectives": ["correctness", "security", "spec", "docs"],
            "jev_acceptance": True, "acceptance_threshold": 0.6, "review_base": after or "main",
            **({"after": a.after} if a.after else {}), "branch": branch}, indent=2))
    if fc_herdr.herdr_space(proj):
        print(f"herdr space {fc_herdr.HERDR_SPACES[name]} with tabs {fc_herdr.tab_label(proj, 'shell')!r} and {fc_herdr.tab_label(proj, 'status')!r}")
    print(f"initialised {proj}\nwork in {wt} from now on: tests and every command with --repo {wt} (or any checkout with --project {name}); "
          + f"the plan and tasks live on Linear: write {proj / 'linear.json'} as {{\"feature\": \"<issue id>\"}}")

def merge_evidence(repo, branch, targets, has_remote):
    """Why a branch counts as merged, or None. Three independent signals, any suffices:
    git ancestry (fast-forward and merge-commit merges), every commit's patch in the target (`git cherry`: a target
    fast-forwarded to a layer built locally, which holds cherry-picked copies), or a merged pull request for the branch on
    GitHub (covers squash and rebase merges, where the commits are rewritten and ancestry says nothing). Any doubt means not merged."""
    for t in targets:
        if fc_core.sh(["git", "rev-parse", "--verify", "-q", t], repo, check=False).returncode:
            continue
        if fc_core.sh(["git", "merge-base", "--is-ancestor", branch, t], repo, check=False).returncode == 0:
            return f"contained in {t}"
        p = fc_core.sh(["git", "cherry", t, branch], repo, check=False)
        if p.returncode == 0 and p.stdout.strip() and all(l.startswith("-") for l in p.stdout.splitlines()):
            return f"contained in {t} by patch"
        p = fc_core.sh(["git", "merge-tree", "--write-tree", t, branch], repo, check=False)
        if p.returncode == 0 and p.stdout.split("\n", 1)[0] == fc_core.sh(["git", "rev-parse", "-q", f"{t}^{{tree}}"], repo, check=False).stdout.strip():
            return f"merging it into {t} changes nothing"
    if has_remote:
        p = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "merged", "--json", "number,mergedAt", "--limit", "1"],
                           cwd=repo, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if p.returncode == 0:
            try:
                prs = json.loads(p.stdout or "[]")
            except json.JSONDecodeError:
                prs = []
            if prs:
                return f"PR #{prs[0]['number']} merged {str(prs[0].get('mergedAt', ''))[:10]}"
    return None

def merged_into(repo, branch, targets, has_remote=False):
    return merge_evidence(repo, branch, targets, has_remote) is not None

def first_unmatched(repo, branch, targets):
    """The first commit on the branch with no patch in the first target that resolves, as a line for clean's kept output, or None."""
    for t in targets:
        if fc_core.sh(["git", "rev-parse", "--verify", "-q", t], repo, check=False).returncode == 0:
            break
    else:
        return None
    plus = [l for l in fc_core.sh(["git", "cherry", "-v", t, branch], repo, check=False).stdout.splitlines() if l.startswith("+")]
    if not plus:
        return None
    _, sha, subject = plus[0].split(" ", 2)
    short = fc_core.sh(["git", "rev-parse", "--short", sha], repo).stdout.strip()
    return f"first unmatched commit {short} {subject}" + (f" and {len(plus) - 1} more" if len(plus) > 1 else "")

def own_commits(repo, branch):
    """False when the branch never got a commit of its own: it still sits where it was created (an empty or design-only project),
    so ancestry says nothing about it being merged. Unknown (no reflog) counts as having commits."""
    log = fc_core.sh(["git", "reflog", "show", "--format=%H", f"refs/heads/{branch}"], repo, check=False).stdout.split()
    return not log or log[-1] != fc_core.sh(["git", "rev-parse", f"refs/heads/{branch}"], repo, check=False).stdout.strip()

def live_crew(proj):
    """Why the project still has people working: teammates whose last report is not done and whose tab is not closed, or agents
    alive in its herdr space. The team lead (orchestrator) is the one running the post-merge clean, so it does not count."""
    lead, why = fc_herdr.agent_name(proj.name, "orchestrator"), []
    listed = fc_herdr.herdr("agent", "list")
    agents = None if listed is None else listed.get("agents", [])
    for f in sorted(fc_crew.crew_dir(proj).glob("*.json")):
        c = json.loads(f.read_text())
        last = (fc_crew.crew_reports(proj, c["name"]) or [{}])[-1]
        if c["name"] != lead and not c.get("closed") and last.get("state") != "done" and not fc_crew.tab_closed(c, agents):
            why.append(f"{c['name']} last reported {last.get('state', 'nothing')}")
    space = fc_herdr.herdr_project_space(proj) if fc_herdr.herdr_env() else None
    tabs = {t["tab_id"] for t in fc_herdr.herdr_project_tabs(proj, space)} if space else set()  # a shared space's other agents are not this project's
    why += [f"{ag.get('name')} is alive in its herdr space" for ag in agents or [] if ag.get("tab_id") in tabs and ag.get("name") != lead]
    return why

def close_space(proj, name):
    """Close what the project holds in herdr: its tabs in a space it shares, or the space of its own.
    A tab whose crew record's last report is not done stays open, one line saying so; the team lead gets no exception."""
    space = fc_herdr.herdr_project_space(proj)
    if not space:
        return
    crew = {c["tab"]: c for c in (json.loads(f.read_text()) for f in sorted(fc_crew.crew_dir(proj).glob("*.json"))) if c.get("tab")}
    kept, closed = [], []
    for t in fc_herdr.herdr_project_tabs(proj, space):
        c = crew.get(t["tab_id"])
        if c:
            last = (fc_crew.crew_reports(proj, c["name"]) or [{}])[-1]
            if last.get("state") != "done":
                print(f"clean left {c['name']} open (last report: {last.get('state', 'nothing')})")
                kept.append(t["tab_id"])
                continue
        closed.append(t["tab_id"])
    if fc_herdr.space_record(proj).exists():
        for tid in closed:
            fc_herdr.herdr("tab", "close", tid)
    elif fc_herdr.herdr_space_is(space, name):
        if kept:
            for tid in closed:
                fc_herdr.herdr("tab", "close", tid)
        else:
            fc_herdr.herdr("workspace", "close", space)

def clean_project(main_repo, name, wt, proj, delete_unmerged=False, explicit=False, force=False):
    """The post-merge step. Fetch, then remove what the reviewer's merges made redundant: task clones and the CLI's stack
    worktree always; task branches merged into the project branch (locally or on the remote); and, once every layer and the
    project branch itself are merged, the project worktree and branch. Unmerged work is kept and named."""
    import shutil
    repo = wt
    crew = live_crew(proj)
    if crew and not (force and explicit):
        print(f"clean  {name}: kept, it has live crew ({'; '.join(crew)}); --project {name} --force overrides")
        return
    has_remote = bool(fc_core.sh(["git", "remote"], repo, check=False).stdout.strip())
    if has_remote:
        fc_core.sh(["git", "fetch", "-q", "--prune"], repo, check=False)
    trunk = fc_core.current_branch(repo)
    for held in fc_worktree.slots(proj).values():  # test-writing teammates' slots and stack slots go back to the pool
        fc_worktree.release_slot(repo, held)
    fc_worktree.slots(proj, {r: None for r in fc_worktree.slots(proj)})
    for w in list((proj / "worktrees").iterdir()) if (proj / "worktrees").exists() else []:  # iterdir: .stackroot is a dotfile
        fc_core.sh(["git", "worktree", "remove", "--force", str(w)], repo, check=False)
        if w.exists():
            shutil.rmtree(w, ignore_errors=True)
    fc_core.sh(["git", "worktree", "prune"], repo, check=False)
    targets = [trunk, f"origin/{trunk}", "main", "origin/main", "master", "origin/master"]
    review = fc_core.project_config(proj).get("review_base")
    targets = list(dict.fromkeys([*([review, f"origin/{review}"] if review else []), *targets]))
    kept, merged = [], []  # merged: the tasks whose branches this clean proved merged
    link = json.loads((proj / "linear.json").read_text()) if (proj / "linear.json").exists() else {}
    metas = {m["id"]: m for m in fc_tasks.load_tasks(proj) if m.get("linear")}  # read now: a merged project's files go with its worktree
    prefix = fc_layers.layer_prefix(repo, proj)
    rec_file = proj / "layers.json"
    held = json.loads(rec_file.read_text()) if rec_file.exists() else {}  # layer branch -> the tasks it held
    remote_layers = {}  # layer branch -> remotes still carrying it
    for ref in fc_core.sh(["git", "for-each-ref", "--format=%(refname:short)", f"refs/remotes/*/{prefix}layer-*"], repo, check=False).stdout.split():
        remote, _, lb = ref.partition("/")
        remote_layers.setdefault(lb, []).append(remote)
    layer_why = {}  # layers proven merged: squash and rebase merges rewrite commits, so this is the PR (or ancestry), never the tasks' own
    for lb in dict.fromkeys([*held, *remote_layers, *fc_core.sh(["git", "branch", "--list", f"{prefix}layer-*"], repo, check=False).stdout.split()]):
        why = merge_evidence(repo, lb, targets, has_remote)
        if why:
            layer_why[lb] = why
    for lb, remotes in remote_layers.items():  # a push, but clean is the post-merge step: only layers proven merged lose their remote branch
        for remote in remotes if lb in layer_why else []:
            if fc_core.sh(["git", "push", "-q", remote, "--delete", lb], repo, check=False).returncode == 0:
                print(f"clean  deleted {remote}/{lb} on the remote: {layer_why[lb]}")
            else:
                print(f"clean  could not delete {remote}/{lb} on the remote; left in place")
    for b in [*fc_worktree.own_branches(repo, proj), *fc_core.sh(["git", "branch", "--list", f"{prefix}layer-*"], repo, check=False).stdout.split()]:
        if "-bench-" in b:  # bench runs are measurements, never work to keep
            fc_core.sh(["git", "branch", "-D", b], repo, check=False)
            continue
        why = merge_evidence(repo, b, targets, has_remote)
        holders = [lb for lb, tasks in held.items() if b.removeprefix(fc_worktree.task_prefix(repo, proj)) in tasks]
        if not why and holders and all(lb in layer_why for lb in holders):
            why = f"held by {', '.join(holders)}, merged: {layer_why[holders[0]]}"
        if why or delete_unmerged:
            print(f"clean  {b}: {why if why else 'UNMERGED, deleted on --delete-unmerged; any PR on GitHub is unaffected'}")
            fc_core.sh(["git", "branch", "-D", b], repo, check=False)
            if why and b.removeprefix(fc_worktree.task_prefix(repo, proj)) in metas:
                merged.append(b.removeprefix(fc_worktree.task_prefix(repo, proj)))
        else:
            kept.append(b)
            fu = first_unmatched(repo, b, targets)
            print(f"clean  {b}: kept unmerged" + (f", {fu}" if fu else ""))
    merged += [t for t in metas if t not in merged and any(t in ts for ts in held.values())
               and all(lb in layer_why for lb, ts in held.items() if t in ts)]
    if (proj / "verify.json").exists() and "layer_prefix" in fc_core.project_config(proj) \
            and not fc_core.sh(["git", "branch", "--list", f"{fc_core.project_config(proj)['layer_prefix']}layer-*"], repo, check=False).stdout.strip():
        fc_core.atomic_write(proj / "verify.json", json.dumps({k: v for k, v in fc_core.project_config(proj).items() if k != "layer_prefix"}, indent=2))  # merged and cleaned: a later stack names afresh
    if (proj / "verify.json").exists() and "task_prefix" in fc_core.project_config(proj) and not fc_worktree.own_branches(repo, proj):
        fc_core.atomic_write(proj / "verify.json", json.dumps({k: v for k, v in fc_core.project_config(proj).items() if k != "task_prefix"}, indent=2))  # merged and cleaned: a later stack names afresh
    line = f"clean  {name}: task branches " + (f"kept unmerged: {', '.join(kept)}" if kept else "all merged and removed")
    pbranch, project_merged = fc_core.project_branch(proj), False
    if wt != main_repo and not kept and trunk == pbranch:
        on = [fc_core.project_config(proj)["review_base"]] if fc_core.project_after(proj) else []  # merged into the project it was built on counts
        ptargets = [*on, "main", "origin/main", "master", "origin/master", fc_core.current_branch(main_repo)]
        why = merge_evidence(main_repo, pbranch, ptargets, has_remote)
        if why and not own_commits(main_repo, pbranch) and not (explicit or delete_unmerged):
            line += f"; project branch {pbranch} has no commits of its own (empty or design-only), so nothing was merged: kept; name it with --project {name} to remove it"
            why = None
        elif not why and held and all(lb in layer_why for lb in held):  # layers squash the project branch's commits: its merge is theirs
            why = f"every layer built from it is merged ({', '.join(held)})"
            project_merged = True
        elif not why and delete_unmerged:
            why = "UNMERGED, removed on --delete-unmerged"
        else:
            project_merged = bool(why)
        if why:
            fc_crew.stop_listeners_under(wt)
            close_space(proj, name)  # while its record is still in the worktree
            if fc_worktree.is_slot(main_repo, wt):  # back to the pool with its installs; the branch is let go first so it can be deleted
                fc_core.sh(["git", "checkout", "-q", "--detach"], wt, check=False)
                fc_worktree.release_slot(main_repo, wt)
            else:
                fc_core.sh(["git", "worktree", "remove", "--force", str(wt)], main_repo, check=False)
            if wt.exists() and not fc_worktree.is_slot(main_repo, wt):
                shutil.rmtree(wt, ignore_errors=True)
            fc_core.sh(["git", "worktree", "prune"], main_repo, check=False)
            fc_core.sh(["git", "branch", "-D", pbranch], main_repo, check=False)
            refs = fc_core.sh(["git", "for-each-ref", "--format=delete %(refname)", f"refs/compose/{name}/", f"refs/compose/replaced/{name}/"],
                      main_repo, check=False).stdout  # its change-of-course and replaced-tip records: nothing left to undo or replay
            if refs.strip():
                subprocess.run(["git", "update-ref", "--stdin"], cwd=main_repo, input=refs, text=True, capture_output=True)
            line += f"; project branch {why}: removed worktree {wt} and branch {pbranch}"
        elif "no commits of its own" not in line:
            line += f"; project branch {pbranch} not merged yet" + (
                f" (layers not merged: {', '.join(lb for lb in held if lb not in layer_why)})" if held else " (no recorded layers to prove it)"
            ) + f": worktree kept; --delete-unmerged removes it anyway"
            fu = first_unmatched(main_repo, pbranch, ptargets)
            print(f"clean  {pbranch}: kept unmerged" + (f", {fu}" if fu else ""))
    print(line)
    fc_linear.linear_merged(link.get("feature"), [metas[t] for t in merged], project_merged)

def cmd_clean(a):
    main_repo = Path(a.repo).resolve()
    main_repo = fc_core.worktrees(main_repo)[0]
    projects = fc_core.all_projects(main_repo)
    if a.project:
        projects = {a.project: projects[a.project]} if a.project in projects else {}
    if not projects:
        sys.exit("no projects to clean")
    for name, (wt, proj) in projects.items():
        clean_project(main_repo, name, wt, proj, delete_unmerged=a.delete_unmerged, explicit=bool(a.project), force=a.force)
