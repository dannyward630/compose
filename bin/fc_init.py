import json, os, re, shutil, subprocess, sys
from pathlib import Path
import fc_core, fc_tasks, fc_linear, fc_herdr, fc_worktree, fc_layers, fc_crew


FRAMELINK_ENV = Path.home() / ".config" / "figma-context-mcp" / ".env"
FRAMELINK_ADD = f"claude mcp add framelink-figma --scope user -- npx -y figma-developer-mcp --stdio --env {FRAMELINK_ENV} --no-telemetry"

GRAFT_INIT = ["graft", "init", "--no-agents", "--no-global", "--no-build"]  # Claude Code wiring only, nothing outside the repo

def existing_repo(wt):
    """True when the repository already has code: a tracked file beyond a README, a license, or git's own dotfiles."""
    files = fc_core.sh(["git", "ls-files"], wt, check=False).stdout.split()
    return any(not re.match(r"(?i)(readme|licen[cs]e|\.git)", Path(f).name) for f in files)

def setup_graft(wt):
    """An existing repo gets graft before anyone reads its code: wired for Claude Code (unless that would touch a tracked
    file) and built. graft's files stay out of git through info/exclude. Safe to run again."""
    if os.environ.get("COMPOSE_NO_GRAFT"):
        return fc_core.say("graft    skipped: COMPOSE_NO_GRAFT is set")
    if not existing_repo(wt):
        return fc_core.say("graft    skipped: a new repository has no code to map yet")
    if not shutil.which("graft"):
        return fc_core.say(f"graft    not installed: `{GRAFT_INSTALL}`, then `compose graft --project <slug>`")
    if not (wt / ".claude" / "helpers" / "graft-hooks.cjs").exists():
        p = fc_core.sh(GRAFT_INIT + ["--dry-run", str(wt)], wt, timeout=120, check=False)
        dry = p.stdout + p.stderr  # graft prints the list on stderr
        section = dry.split("this repo:", 1)[1].split("\n\n", 1)[0] if "this repo:" in dry else ""
        paths = sorted(set(re.findall(r"^\s+(\S+)", section, re.M)))
        tracked = [f for f in paths if fc_core.sh(["git", "ls-files", "--error-unmatch", f], wt, check=False).returncode == 0]
        if tracked:
            fc_core.say(f"graft    init skipped: it would edit tracked {', '.join(tracked)}; building the graph only")
        else:
            fc_core.sh(GRAFT_INIT + [str(wt)], wt, timeout=300, check=False)
            fc_worktree.exclude_paths(wt, ["/" + f for f in paths])
            fc_core.say(f"graft    wired for Claude Code ({len(paths)} files, kept out of git)")
    fc_worktree.exclude_paths(wt, ["/graft/"])  # the graph itself, also when `compose graft` runs without init
    fc_worktree.stamp_graft_wiring(wt)
    fc_core.sh(["graft", "build", "--no-gitignore", "--no-ignore", str(wt)], wt, timeout=600, check=False)
    fc_core.say("graft    graph built")

def cmd_graft(a):
    """Set graft up in the project's worktree again (after installing graft, or to rebuild the graph)."""
    setup_graft(fc_herdr.project_worktree(fc_core.project_dir(a)))

HERDR_MIN = "0.9.3"  # `herdr agent start` and `agent prompt` (herdr_start_crew, pi_herdr_turn): the version they were proven on
TREEHOUSE_MIN = "3.1.2"  # `treehouse get --lease --json --lease-holder` (slot_on): the version it was proven on
GRAFT_INSTALL = "npm i -g @nanonets/graft"
DEPS = (  # (name, how it is found, install, required, version floor); every tool and skill file the CLI and the skill text use.
    # required is True, False, or the one role that needs it: doctor and init only warn about that one, and that role's start stops
    ("herdr", "herdr", "see https://herdr.dev", True, HERDR_MIN),
    ("treehouse", "treehouse", fc_worktree.TREEHOUSE_INSTALL, False, TREEHOUSE_MIN),
    ("graft", "graft", GRAFT_INSTALL, False, None),
    ("gh", "gh", "brew install gh", True, None),
    ("gh stack", ["gh", "stack", "--version"], "gh extension install github/gh-stack", True, None),
    ("claude", "claude", "curl -fsSL https://claude.ai/install.sh | bash", True, None),
    ("npx", "npx", "brew install node", True, None),  # lavish-axi and figma-developer-mcp run through it
    ("pi", "pi", "npm i -g @earendil-works/pi-coding-agent", False, None),
    ("bp", "bp", "ln -s <compose checkout>/bp/bin/bp.mjs ~/.local/bin/bp", False, None),
    ("herdr skill", ".claude/skills/herdr/SKILL.md", "mkdir -p ~/.claude/skills/herdr && herdr --skill > ~/.claude/skills/herdr/SKILL.md", True, None),
    ("i-have-adhd skill", ".claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md", "claude plugin marketplace add ayghri/i-have-adhd", True, None),
    ("framelink-figma", lambda: "framelink-figma" in user_mcp_servers(), FRAMELINK_ADD, "designer", None),  # every Figma read (0d, figma check/tree)
    ("framelink-figma token", ".config/figma-context-mcp/.env",
     "put a Figma personal access token in ~/.config/figma-context-mcp/.env as one line FIGMA_API_KEY=<token>, chmod 600", "designer", None),
    ("writing-plans skill", ".claude/plugins/cache/*/superpowers/*/skills/writing-plans/SKILL.md", "claude plugin install superpowers@claude-plugins-official", False, None),
)

def user_mcp_servers():
    """The MCP servers Claude Code has at user scope (`claude mcp add --scope user`), read from ~/.claude.json without starting any."""
    try:
        return json.loads((Path.home() / ".claude.json").read_text()).get("mcpServers") or {}
    except (OSError, ValueError):
        return {}

def version_of(tool):
    """`<tool> --version` as a tuple of ints, or None when it prints nothing that looks like one."""
    p = fc_core.sh([tool, "--version"], None, timeout=20, check=False)
    m = re.search(r"\d+(?:\.\d+)+", p.stdout + p.stderr)
    return tuple(map(int, m.group().split("."))) if m else None

def check_deps(role=None):
    """Print one `MISSING: <name> (install: <command>)` line per tool or skill file that is absent (or below its floor), without
    any network call. Returns the required ones among them: those stop `init`; the optional ones (pi, bp, treehouse, graft) only warn.
    With a role, only what that role needs is checked, and it is required (Framelink stops the designer's start)."""
    bad = []
    for name, how, install, needed, floor in DEPS:
        if role and needed != role:
            continue
        required = needed is True or (role is not None and needed == role)
        if callable(how):
            ok = how()
        elif isinstance(how, list):
            ok = shutil.which(how[0]) and fc_core.sh(how, None, timeout=20, check=False).returncode == 0
        elif "/" in how:
            ok = any(Path.home().glob(how)) if "*" in how else (Path.home() / how).exists()
        else:
            ok = shutil.which(how)
        why = ""
        if ok and floor:
            v = version_of(how)
            if v and v < tuple(map(int, floor.split("."))):
                ok, why = False, f" {'.'.join(map(str, v))} is older than {floor}"
        if not ok:
            note = "" if required else f" - needed for the {needed}" if needed else " - optional"
            print(f"MISSING: {name}{why} (install: {install}){note}")
            if required:
                bad.append(name)
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

def herdr_toast_warning():
    """One line when herdr's own toasts or sounds are on, for the product owner to read: herdr then alerts them for every agent
    that finishes or needs input, in every pane, while compose already sends the engineering manager's one alert itself
    (desktop_notify). None when `[ui.toast] delivery` is off (herdr's default) and `[ui.sound] enabled` is false (not the default)."""
    cfg = herdr_toml(Path.home() / ".config" / "herdr" / "config.toml")
    loud = [(key, cfg.get(key, default)) for key, quiet, default in (("ui.toast.delivery", "off", "off"), ("ui.sound.enabled", "false", "true"))
            if cfg.get(key, default) != quiet]
    if not loud:
        return None
    return ("WARNING: herdr alerts the product owner for every agent, not only the engineering manager ("
            + ", ".join(f"{k}={v}" for k, v in loud) + '): set [ui.toast] delivery = "off" and [ui.sound] enabled = false in '
            "~/.config/herdr/config.toml; compose sends the engineering manager's alert itself")

def cmd_doctor(a):
    """Check every tool and skill file compose depends on; exit 1 when a required one is missing. Warns, never stops, when
    herdr's own agent toasts or sounds would reach the product owner from every agent."""
    if check_deps():
        sys.exit(1)
    if warning := herdr_toast_warning():
        print(warning)
    print("every tool compose needs is installed")

def cmd_init(a):
    """Create the project's worktree `../compose-<name>` on its branch (`compose/<name>`, or --branch; from the branch the user is on,
    or with --after from another project's branch, for a feature that needs that feature's code), with the
    `.compose/<name>/` config beside it, ignored and never committed. The user's checkout is never touched again by this project."""
    if check_deps():  # before anything is created: a missing required tool stops here
        sys.exit("init stopped: install what is missing above, then run it again (`compose doctor` checks again)")
    here = Path(a.repo).resolve()
    name = a.project
    branch = a.branch or f"compose/{name}"
    if a.branch and fc_core.sh(["git", "check-ref-format", "--branch", a.branch], here, check=False).returncode != 0:
        sys.exit(f"{a.branch!r} is not a valid branch name")
    if a.branch and a.here:
        sys.exit("--branch names the project's own worktree branch; it does not combine with --here")
    other = fc_core.all_projects(here).get(a.after) if a.after else None
    after = fc_core.project_branch(other[1]) if other else (f"compose/{a.after}" if a.after else None)
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
    setup_graft(wt)
    repo_link = here / ".compose" / "linear.json"  # the repo's Linear project, written in the user's checkout (step 0)
    if repo_link.exists() and not (wt / ".compose" / "linear.json").exists():
        (wt / ".compose" / "linear.json").write_text(repo_link.read_text())
    if not (proj / "verify.json").exists():
        fc_core.atomic_write((proj / "verify.json"), json.dumps({
            "checks": [], "docs": ["README.md"], "e2e": [],
            "review": True, "perspectives": ["correctness", "security", "spec", "docs"],
            "jev_acceptance": True, "acceptance_threshold": 0.6, "review_base": after or "main",
            **({"after": a.after} if a.after else {}), **({"branch": a.branch} if a.branch else {})}, indent=2))
    if fc_herdr.herdr_space(proj):
        print(f"herdr space {name!r} ({fc_herdr.HERDR_SPACES[name]}) with a status tab")
    print(f"initialised {proj}\nwork in {wt} from now on: tests and every command with --repo {wt} (or any checkout with --project {name}); "
          + f"the plan and tasks live on Linear: write {proj / 'linear.json'} as {{\"feature\": \"<issue id>\"}}")

def merge_evidence(repo, branch, targets, has_remote):
    """Why a branch counts as merged, or None. Two independent signals, either suffices:
    git ancestry (fast-forward and merge-commit merges), or a merged pull request for the branch on GitHub (covers squash
    and rebase merges, where the commits are rewritten and ancestry says nothing). Any doubt means not merged."""
    for t in targets:
        if fc_core.sh(["git", "rev-parse", "--verify", "-q", t], repo, check=False).returncode == 0 \
                and fc_core.sh(["git", "merge-base", "--is-ancestor", branch, t], repo, check=False).returncode == 0:
            return f"contained in {t}"
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

def own_commits(repo, branch):
    """False when the branch never got a commit of its own: it still sits where it was created (an empty or design-only project),
    so ancestry says nothing about it being merged. Unknown (no reflog) counts as having commits."""
    log = fc_core.sh(["git", "reflog", "show", "--format=%H", f"refs/heads/{branch}"], repo, check=False).stdout.split()
    return not log or log[-1] != fc_core.sh(["git", "rev-parse", f"refs/heads/{branch}"], repo, check=False).stdout.strip()

def live_crew(proj, wt):
    """Why the project still has people working: teammates whose last report is not done, or agents alive in its herdr space.
    The team lead (orchestrator) is the one running the post-merge clean, so it does not count."""
    lead, why = fc_herdr.agent_name(proj.name, "orchestrator"), []
    for f in sorted(fc_crew.crew_dir(proj).glob("*.json")):
        c = json.loads(f.read_text())
        last = (fc_crew.crew_reports(proj, c["name"]) or [{}])[-1]
        if c["name"] != lead and not c.get("closed") and last.get("state") != "done":
            why.append(f"{c['name']} last reported {last.get('state', 'nothing')}")
    space = fc_herdr.herdr_find_space(wt) if fc_herdr.herdr_env() else None
    why += [f"{ag.get('name')} is alive in its herdr space" for ag in fc_herdr.live_agents() if space and ag.get("workspace_id") == space and ag.get("name") != lead]
    return why

def clean_project(main_repo, name, wt, proj, delete_unmerged=False, explicit=False, force=False):
    """The post-merge step. Fetch, then remove what the reviewer's merges made redundant: task clones and the CLI's stack
    worktree always; task branches merged into the project branch (locally or on the remote); and, once every layer and the
    project branch itself are merged, the project worktree and branch. Unmerged work is kept and named."""
    import shutil
    repo = wt
    crew = live_crew(proj, wt)
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
    for b in fc_core.sh(["git", "branch", "--list", f"fast/{name}/*", f"{prefix}layer-*"], repo, check=False).stdout.split():
        if "-bench-" in b:  # bench runs are measurements, never work to keep
            fc_core.sh(["git", "branch", "-D", b], repo, check=False)
            continue
        why = merge_evidence(repo, b, targets, has_remote)
        holders = [lb for lb, tasks in held.items() if b.rsplit("/", 1)[-1] in tasks]
        if not why and holders and all(lb in layer_why for lb in holders):
            why = f"held by {', '.join(holders)}, merged: {layer_why[holders[0]]}"
        if why or delete_unmerged:
            print(f"clean  {b}: {why if why else 'UNMERGED, deleted on --delete-unmerged; any PR on GitHub is unaffected'}")
            fc_core.sh(["git", "branch", "-D", b], repo, check=False)
            if why and b.rsplit("/", 1)[-1] in metas:
                merged.append(b.rsplit("/", 1)[-1])
        else:
            kept.append(b)
    if (proj / "verify.json").exists() and "layer_prefix" in fc_core.project_config(proj) \
            and not fc_core.sh(["git", "branch", "--list", f"{fc_core.project_config(proj)['layer_prefix']}layer-*"], repo, check=False).stdout.strip():
        fc_core.atomic_write(proj / "verify.json", json.dumps({k: v for k, v in fc_core.project_config(proj).items() if k != "layer_prefix"}, indent=2))  # merged and cleaned: a later stack names afresh
    line = f"clean  {name}: task branches " + (f"kept unmerged: {', '.join(kept)}" if kept else "all merged and removed")
    pbranch, project_merged = fc_core.project_branch(proj), False
    if wt != main_repo and not kept and trunk == pbranch:
        on = [fc_core.project_config(proj)["review_base"]] if fc_core.project_after(proj) else []  # merged into the project it was built on counts
        why = merge_evidence(main_repo, pbranch, [*on, "main", "origin/main", "master", "origin/master", fc_core.current_branch(main_repo)], has_remote)
        if why and not own_commits(main_repo, pbranch) and not (explicit or delete_unmerged):
            line += f"; project branch {pbranch} has no commits of its own (empty or design-only), so nothing was merged: kept; name it with --project {name} to remove it"
            why = None
        elif not why and held and all(lb in layer_why for lb in held):  # layers squash the project branch's commits: its merge is theirs
            why = f"every layer built from it is merged ({', '.join(held)})"
        elif not why and delete_unmerged:
            why = "UNMERGED, removed on --delete-unmerged"
        else:
            project_merged = bool(why)
        if why:
            fc_crew.stop_listeners_under(wt)
            if fc_worktree.is_slot(main_repo, wt):  # back to the pool with its installs; the branch is let go first so it can be deleted
                space = fc_herdr.herdr_find_space(wt)
                if space and fc_herdr.herdr_space_is(space, name):
                    fc_herdr.herdr("workspace", "close", space)
                fc_core.sh(["git", "checkout", "-q", "--detach"], wt, check=False)
                fc_worktree.release_slot(main_repo, wt)
            else:
                fc_core.sh(["git", "worktree", "remove", "--force", str(wt)], main_repo, check=False)
            if wt.exists() and not fc_worktree.is_slot(main_repo, wt):
                space = fc_herdr.herdr_find_space(wt)
                if space and fc_herdr.herdr_space_is(space, name):
                    fc_herdr.herdr("workspace", "close", space)
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
