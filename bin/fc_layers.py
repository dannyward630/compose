import json, os, re, subprocess
from pathlib import Path
import fc_core, fc_config, fc_tasks, fc_worktree


CONFIG_FILE_RE = re.compile(r"(^|/)(package(-lock)?\.json|[^/]*\.lock|pnpm-lock\.yaml|go\.(mod|sum)|requirements[^/]*\.txt|[^/]*\.(ya?ml|toml|ini)|\.[^/]*rc(\.\w+)?|[^/]*\.config\.\w+)$")

def layer_prefix(repo, proj):
    """Review layer branches are `<prefix>layer-NN`. The prefix recorded in verify.json (written when layers are first built) wins; a project
    whose `fast/<project>/layer-NN` branches already exist, locally or as remote-tracking refs, keeps them; only a project with no layers
    yet gets `<stored branch>-` (`init --branch`), else `fast/<project>/`."""
    cfg, legacy = fc_core.project_config(proj), f"fast/{Path(proj).name}/"
    if cfg.get("layer_prefix"):
        return cfg["layer_prefix"]
    if fc_core.sh(["git", "for-each-ref", "--count=1", "--format=%(refname)", f"refs/heads/{legacy}layer-*", f"refs/remotes/*/{legacy}layer-*"], repo, check=False).stdout.strip():
        return legacy
    return f"{cfg['branch']}-" if cfg.get("branch") else legacy


def commit_message(meta, conv=None):
    """A task's commit says what changed, in the task title's words: no tool name, task id, or process. With a commit convention it
    starts with the type of the change: docs or dependency/config files only, else fix for a "Fix ..." title, else feat."""
    title = re.sub(r"^\s*\d{3}[:.\s-]*", "", meta.get("title") or "").strip()
    msg = title or "Update " + ", ".join(meta.get("files") or ["files"])
    files = meta.get("files") or []
    kind = ("docs" if files and all(fc_config.DOC_RE.search(f) for f in files) else "deps" if files and all(CONFIG_FILE_RE.search(f) for f in files)
            else "fix" if re.match(r"fix\b", title, re.I) else "feat")
    return fc_core.typed(msg, kind, conv)


def chain_order(repo, proj, trunk):
    """Branches bottom to top. Ancestry wins: a branch whose history already contains another sits above it (a rebase can never
    move a commit below history it contains). Ties, i.e. branches not on one line yet, follow stack_order (deps, then id)."""
    order = fc_worktree.stack_order(repo, proj)
    rank = {b: i for i, b in enumerate(order)}
    def depth(b):
        return int(fc_core.sh(["git", "rev-list", "--count", f"{trunk}..{b}"], repo, check=False).stdout.strip() or 0)
    return sorted(order, key=lambda b: (depth(b), rank[b]))

STACK_STOP = ""  # why the last linearize stopped short, with the commands that resolve it; empty when the chain is whole

def linearize(repo, proj, trunk, wt):
    with fc_worktree.STACK_LOCK:
        return _linearize(repo, proj, trunk, wt)

def _linearize(repo, proj, trunk, wt):
    """Rebase the project's unmerged task branches into one chain on the current trunk tip, layer on layer, inside the CLI's
    worktree. Returns the branches that now form a clean chain; a conflict stops the chain there and is reported."""
    global STACK_STOP
    STACK_STOP = ""
    chain = chain_order(repo, proj, trunk)
    linear, prev = [], trunk
    replaced = fc_worktree.replaced_tips(repo, proj)
    tips = list(replaced)  # (branch, a tip it no longer has): rebuilt layers, plus every layer this pass rebases
    contains = lambda anc, b: fc_core.sh(["git", "merge-base", "--is-ancestor", anc, b], repo, check=False).returncode == 0
    for b in chain:
        if not contains(prev, b):
            # b still carries the old commits of what it was built on: a layer below that was rebuilt or rebased, or the trunk
            # itself when it was rewritten (rebased onto a moved main). Replay only b's own commits: start above the old tip it
            # was built on. That tip is, in order: one recorded in this pass (a rebuilt layer, or a layer rebased just now); one
            # in the reflog of the layer below (fork-point), which holds a rewrite made before this pass, by hand or by a redo
            # whose replaced ref is gone; one in the trunk's reflog; without any, a plain rebase is the best guess.
            old = [t for rb, t in tips if rb in linear and contains(t, b)]
            upstream = max(old, key=lambda t: int(fc_core.sh(["git", "rev-list", "--count", f"{trunk}..{t}"], repo).stdout)) if old else ""
            source = "the old base recorded in this pass"
            for ref in dict.fromkeys((prev, trunk)):
                if upstream:
                    break
                upstream = fc_core.sh(["git", "merge-base", "--fork-point", ref, b], repo, check=False).stdout.strip()
                source = f"the old base from the reflog of {ref}"
            if not upstream:
                upstream, source = prev, "no old base found: a plain rebase"
            tips.append((b, fc_core.sh(["git", "rev-parse", b], repo).stdout.strip()))
            fc_core.sh(["git", "checkout", "-q", b], wt)
            r = fc_core.sh(["git", "rebase", "-q", "--onto", prev, upstream], wt, check=False)
            if r.returncode:
                fc_core.sh(["git", "rebase", "--abort"], wt, check=False)
                fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
                STACK_STOP = (f"{b} conflicts when rebased onto {prev}; the layers below it are kept. Resolve by hand: "
                              f"git checkout {b} && git rebase --onto {prev} {upstream} ({source}), then re-run")
                fc_core.say(f"stack  STOP  {STACK_STOP}")
                break
        linear.append(b)
        prev = b
    fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
    for rb, t in replaced:  # an old tip no layer carries any more is done with
        if not any(contains(t, b) for b in chain):
            fc_core.sh(["git", "update-ref", "-d", f"refs/compose/replaced/{proj.name}/{rb.rsplit('/', 1)[1]}/{t}"], repo, check=False)
    return linear

REVIEW_LAYER_LINES = 300  # verify.json `review_layer_lines` changes it
def commit_facts(repo, c):
    """(files, changed lines, {generated file: lines}) of one commit. Lockfiles are not counted: nobody reads them."""
    files, counted, generated = [], 0, {}
    for l in fc_core.sh(["git", "show", "--numstat", "--no-renames", "--format=", c], repo).stdout.splitlines():
        a, d, f = l.split("\t", 2)
        n = (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)  # a binary file shows "-"
        files.append(f)
        if fc_worktree.GENERATED_RE.search(f):
            generated[f] = generated.get(f, 0) + n
        else:
            counted += n
    return files, counted, generated

def group_units(units, budget):
    """Consecutive units into layers of at most `budget` counted lines, in order. A unit (a task with its tests, or one groundwork
    commit) is never split, so one bigger than the budget is a layer of its own."""
    layers = []
    for u in units:
        if layers and sum(x["lines"] for x in layers[-1]) + u["lines"] <= budget:
            layers[-1].append(u)
        else:
            layers.append([u])
    return layers

def review_units(repo, proj, base, trunk, chain):
    """The project's work as ordered units: every commit the project branch carries over `base` that no task owns (groundwork,
    one unit per commit), then each chain task with its acceptance-test commits first and its own commits after. A test commit
    is a task's when every file it touches is in that task's `protected:`; the tests of a task not in the chain yet ride with the
    last one. Two tasks can protect one file: a commit on it never goes to a task before the one that took an earlier commit on
    the same file, so every file's commits replay in the trunk's order and the layers apply."""
    protected = {m["id"]: set(m["protected"]) for m in fc_tasks.code_tasks(fc_tasks.load_tasks(proj))}
    ids = [b.rsplit("/", 1)[1] for b in chain]
    def unit(name, commits):
        facts = [commit_facts(repo, c) for c in commits]
        gen = {}
        for _, _, g in facts:
            for f, n in g.items():
                gen[f] = gen.get(f, 0) + n
        return {"name": name, "commits": commits, "lines": sum(n for _, n, _ in facts), "generated": gen}
    ground, owned, last = [], {t: [] for t in ids}, {}  # last: file -> position in the chain of the task that took its latest commit
    for c in fc_core.sh(["git", "rev-list", "--reverse", "--no-merges", f"{base}..{trunk}"], repo).stdout.split():
        files = set(commit_facts(repo, c)[0])
        owner = next((t for t in ids + sorted(set(protected) - set(ids)) if files and files <= protected.get(t, set())), None)
        pos = None if owner is None else ids.index(owner) if owner in owned else len(ids) - 1
        floor = max((last[f] for f in files if f in last), default=None)
        if floor is not None and (pos is None or pos < floor):
            pos = floor
        if pos is None:
            ground.append(unit("groundwork", [c]))
        else:
            owned[ids[pos]].append(c)
            last.update(dict.fromkeys(files, pos))
    units, prev = ground, trunk
    for b, t in zip(chain, ids):
        units.append(unit(t, owned[t] + fc_core.sh(["git", "rev-list", "--reverse", "--no-merges", f"{prev}..{b}"], repo).stdout.split()))
        prev = b
    return units

def cherry_pick_same(wt, c):
    """Cherry-pick keeping the original committer and date, so a layer rebuilt from unchanged commits gets the same hashes and
    a resubmit pushes nothing new."""
    who = fc_core.sh(["git", "show", "-s", "--format=%cn%n%ce%n%cI", c], wt).stdout.splitlines()
    env = {**os.environ, "GIT_COMMITTER_NAME": who[0], "GIT_COMMITTER_EMAIL": who[1], "GIT_COMMITTER_DATE": who[2]}
    p = fc_core.sh(["git", "cherry-pick", "--allow-empty", c], wt, check=False, env=env)
    if p.returncode:
        fc_core.sh(["git", "cherry-pick", "--abort"], wt, check=False)
    return p.returncode == 0

def record_layers(proj, layers):
    """Remember which tasks each layer holds once the stack is submitted: from then on a layer has a PR, so its tasks stay in it."""
    fc_core.atomic_write(Path(proj) / "layers.json", json.dumps({l["branch"]: list(dict.fromkeys(l["tasks"])) for l in layers}, indent=2))

def group_by_record(proj, units, budget):
    """Groups of units: each recorded layer keeps its own tasks (groundwork commits go to the layer that held groundwork), and
    units no layer holds yet are grouped as usual into new layers above. [(recorded branch or None, units)]."""
    rec_file = Path(proj) / "layers.json"
    rec = json.loads(rec_file.read_text()) if rec_file.exists() else {}
    groups, seen = [], set()
    for b, names in rec.items():
        held = [u for u in units if u["name"] in names and u["name"] not in seen]
        seen |= {u["name"] for u in held}
        if held:
            groups.append((b, held))
    new = [u for u in units if u["name"] not in seen]
    return groups + [(None, g) for g in group_units([u for u in new if u["name"] == "groundwork"], budget) + group_units([u for u in new if u["name"] != "groundwork"], budget)]

def build_layers(repo, proj, base, trunk, chain, wt, budget):
    """Cut the project into review layers on `base`: branches `<layer_prefix>layer-NN`, each at most `budget` counted lines
    (groundwork first, then tasks with their tests), rebuilt from the commits every time. Returns [{branch, tasks, lines,
    generated}], or None when the layers do not add up to the same tree as the task chain (the caller then stacks the tasks)."""
    units = review_units(repo, proj, base, trunk, chain)  # groundwork is layers of its own, never mixed into a task's
    groups = group_by_record(proj, units, budget)
    layers, prev, prefix = [], base, layer_prefix(repo, proj)
    cfg_file = Path(proj) / "verify.json"
    if cfg_file.exists() and fc_core.project_config(proj).get("layer_prefix") != prefix:  # recorded once, so later stacks never have to guess
        fc_core.atomic_write(cfg_file, json.dumps({**fc_core.project_config(proj), "layer_prefix": prefix}, indent=2))
    for i, (rec_branch, g) in enumerate(groups, 1):
        branch = rec_branch or f"{prefix}layer-{i:02d}"
        fc_core.sh(["git", "checkout", "-q", "-B", branch, prev], wt)
        for c in (c for u in g for c in u["commits"]):
            if not cherry_pick_same(wt, c):
                fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
                fc_core.say(f"stack  STOP  {c[:7]} does not apply on layer {i}; stacking task branches as they are")
                return None
        gen = {}
        for u in g:
            for f, n in u["generated"].items():
                gen[f] = gen.get(f, 0) + n
        layers.append({"branch": branch, "tasks": [u["name"] for u in g], "lines": sum(u["lines"] for u in g), "generated": gen})
        prev = branch
    fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
    if layers and fc_core.sh(["git", "merge-base", "--is-ancestor", base, chain[-1]], repo, check=False).returncode == 0 \
            and fc_core.sh(["git", "diff", "--quiet", layers[-1]["branch"], chain[-1]], repo, check=False).returncode != 0:
        fc_core.say(f"stack  STOP  the layers differ from {chain[-1]}; stacking task branches as they are")
        return None
    for old in fc_core.sh(["git", "branch", "--list", f"{prefix}layer-*", "--format=%(refname:short)"], repo).stdout.split():
        if old not in {l["branch"] for l in layers}:
            fc_core.sh(["git", "branch", "-D", old], repo, check=False)
    return layers

def layer_note(l, budget):
    """One layer as a line for the log and the PR body: what it holds, its size, and the generated files kept out of the count."""
    names = [t for t in l["tasks"] if t != "groundwork"]
    held = ([f"groundwork x{l['tasks'].count('groundwork')}"] if "groundwork" in l["tasks"] else []) + ([f"task {', '.join(names)}"] if names else [])
    gen = "".join(f"; generated, not counted: {f} ({n} lines)" for f, n in l["generated"].items())
    over = f"; over the {budget}-line budget, a task is never split" if l["lines"] > budget and len(l["tasks"]) == 1 else ""
    return f"{' + '.join(held)}: {l['lines']} lines{over}{gen}"

def layer_pr(proj, l, n, budget, metas):
    """A layer's PR title and body. The title is the layer's tasks (`JS-2888: add a, add b (1/4)` when the project branch starts with a
    Jira key); the body lists the tasks and the layer's size."""
    names = {m["id"]: commit_message(m) for m in metas}
    held = [names.get(t, t) if t != "groundwork" else "groundwork" for t in l["tasks"]]
    held = list(dict.fromkeys(held))
    key = re.match(r"([A-Za-z]+-\d+)-", fc_core.project_config(proj).get("branch") or "")
    idx = int(l["branch"].rsplit("layer-", 1)[1])
    title = f"{key.group(1).upper() + ': ' if key else ''}{', '.join(held)} ({idx}/{n})"
    return title, "\n".join([*(f"- {h}" for h in held), "", layer_note(l, budget)])

def gh_pr_text(wt, b):
    """The title and body of the PR on branch b, or None when it has none."""
    v = subprocess.run(["gh", "pr", "view", b, "--json", "title,body"], cwd=wt, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return json.loads(v.stdout) if v.returncode == 0 else None

def write_pr_text(proj, wt, b, before, title, body):
    """Write a layer's generated title and body on its PR only when the CLI owns the text: the PR was just created (before is None),
    or its text still equals what the CLI wrote last time (recorded in pr_text.json). A person's or reviewer's edit, and any PR
    from before the record existed, keeps its text; the size line is regenerated with the rest or not at all."""
    rec_file = Path(proj) / "pr_text.json"
    rec = json.loads(rec_file.read_text()) if rec_file.exists() else {}
    last = rec.get(b)
    if before is not None and not (last and (before["title"], before["body"].strip()) == (last["title"], last["body"].strip())):
        return False
    r = subprocess.run(["gh", "pr", "edit", b, "--title", title, "--body", body], cwd=wt, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode == 0:
        fc_core.atomic_write(rec_file, json.dumps({**rec, b: {"title": title, "body": body}}, indent=2))
    return r.returncode == 0

def register_stack(repo, proj, trunk, submit=False):
    """Make the project's passed task branches one gh stack, layer by layer, without touching the user's checkout. Branches built
    in parallel from trunk are rebased onto the layer below (tasks own disjoint files, so this is normally clean; a conflict
    stops the chain there and is reported). The stack itself is review layers on the real base (`review_base`, else the default
    branch), not one PR per task and not the project branch as a PR: groundwork and each task's tests are cut into the layers
    too, so the project branch carries nothing the layers do not. Nothing is pushed unless submit=True."""
    if not fc_worktree.stack_order(repo, proj):
        return []
    wt = fc_worktree.stack_worktree(repo, proj, trunk)
    gh = lambda *args: subprocess.run(["gh", "stack", *args], cwd=wt, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    linear = linearize(repo, proj, trunk, wt)
    if not linear:
        return []
    cfg = fc_core.project_config(proj)
    base = cfg.get("review_base") or fc_worktree.default_branch(repo) or trunk
    if trunk != fc_core.project_branch(proj) or fc_core.sh(["git", "rev-parse", "--verify", "-q", base], repo, check=False).returncode:
        base = trunk
    budget = int(cfg.get("review_layer_lines") or REVIEW_LAYER_LINES)
    layers = build_layers(repo, proj, base, trunk, linear, wt, budget)
    stack, stack_base = ([l["branch"] for l in layers], base) if layers else (linear, trunk)
    # A stack from an earlier wave is rebuilt with the grown chain: every existing stack that holds any of these branches is
    # unstacked locally (GitHub side untouched), then one init registers the whole chain.
    for b in linear + stack:
        fc_core.sh(["git", "checkout", "-q", b], wt, check=False)
        if gh("view", "--json").returncode == 0:
            gh("unstack", "--local")
    fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
    p = gh("init", "--base", stack_base, *stack)
    if p.returncode:
        fc_core.say(f"stack  FAIL  {' <- '.join(stack)}: {(p.stderr or p.stdout).strip()[-300:]}")
        fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
        return []
    fc_core.say(f"stack  ok    ({stack_base}) <- {' <- '.join(stack)}")
    for l in layers or []:
        fc_core.say(f"layer  {l['branch'].removeprefix(layer_prefix(repo, proj))}  {layer_note(l, budget)}")
    if submit:
        fc_core.sh(["git", "checkout", "-q", stack[-1]], wt, check=False)
        before = {b: gh_pr_text(wt, b) for b in stack}  # which PRs exist, and their text, before this submit touches anything
        q = gh("submit", "--auto")
        fc_core.say(f"submit {'ok  ' if q.returncode == 0 else 'FAIL'}  {(q.stdout + q.stderr).strip()[-400:]}")
        if q.returncode == 0 and layers:
            record_layers(proj, layers)
        for b in stack if q.returncode == 0 else []:  # a real GitHub stack is one PR per layer, each on the layer below
            v = subprocess.run(["gh", "pr", "view", b, "--json", "number,baseRefName,url"], cwd=wt, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            pr = json.loads(v.stdout) if v.returncode == 0 else None
            fc_core.say(f"submit {'PR #%d on %s  %s' % (pr['number'], pr['baseRefName'], pr['url']) if pr else 'NO PR for'}  {b}")
            lay = next((l for l in layers or [] if l["branch"] == b), None)
            if pr and lay:
                title, body = layer_pr(proj, lay, len(layers), budget, fc_tasks.code_tasks(fc_tasks.load_tasks(proj)))
                write_pr_text(proj, wt, b, before[b], title, body)
    fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)  # free the branches for the user's checkout
    fc_worktree.mirror_stack_state(repo, wt)
    return [stack]

def cmd_stack(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    trunk = a.trunk or fc_core.current_branch(repo)
    if not register_stack(repo, proj, trunk, submit=a.submit):
        print("stack  nothing to register: no unmerged task branches")
