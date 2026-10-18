import json, os, re, subprocess, sys, tempfile, time
from pathlib import Path
import fc_core, fc_config, fc_herdr, fc_tasks, fc_worktree


CONFIG_FILE_RE = re.compile(r"(^|/)(package(-lock)?\.json|[^/]*\.lock|pnpm-lock\.yaml|go\.(mod|sum)|requirements[^/]*\.txt|[^/]*\.(ya?ml|toml|ini)|\.[^/]*rc(\.\w+)?|[^/]*\.config\.\w+)$")

def layer_prefix(repo, proj):
    """Review layer branches are `<prefix>layer-NN`, named from the task prefix: the prefix recorded in verify.json (written when
    layers are first built) wins, else `fc_worktree.task_prefix(repo, proj)`, so a project whose `fast/<project>/` task branches
    exist, locally or as remote-tracking refs, keeps `fast/<project>/layer-NN`, and a new project names its layers from its
    stored branch."""
    cfg = fc_core.project_config(proj)
    if cfg.get("layer_prefix"):
        return cfg["layer_prefix"]
    return fc_worktree.task_prefix(repo, proj)


def commit_message(meta, conv=None):
    """A task's commit says what changed, in the task title's words: no tool name, task id, or process. With a commit convention it
    starts with the type of the change: docs or dependency/config files only, else fix for a "Fix ..." title, else feat."""
    title = re.sub(r"^\s*\d{3}[:.\s-]*", "", meta.get("title") or "").strip()
    msg = title or "Update " + ", ".join(meta.get("files") or ["files"])
    files = meta.get("files") or []
    kind = ("docs" if files and all(fc_config.DOC_RE.search(f) for f in files) else "deps" if files and all(CONFIG_FILE_RE.search(f) for f in files)
            else "fix" if re.match(r"fix\b", title, re.I) else "feat")
    return fc_core.typed(msg, kind, conv)


def chain_order(repo, proj):
    """Branches bottom to top, in stack_order (deps, then id), except that ancestry wins: a branch whose tip already contains
    another's sits above it (a rebase can never move a commit below history it contains). Only real ancestry counts: a task
    based on a low layer has as many commits as the layer above its base, and is not on that layer's line."""
    order = fc_worktree.stack_order(repo, proj)
    tip = {b: fc_core.sh(["git", "rev-parse", b], repo).stdout.strip() for b in order}
    below = {b: set() for b in order}  # b -> the other branches its tip contains; one at the same tip is no constraint
    prefix = fc_worktree.task_prefix(repo, proj)
    for a in order:
        held = fc_core.sh(["git", "for-each-ref", "--contains", tip[a], "--format=%(refname)", f"refs/heads/{prefix}*"], repo).stdout.split()
        for b in (r.removeprefix("refs/heads/") for r in held):
            if b in below and tip[b] != tip[a]:
                below[b].add(a)
    out = []
    while order:  # ancestry has no cycles, so some branch always has everything it contains placed
        b = next(b for b in order if below[b] <= set(out))
        out.append(b)
        order.remove(b)
    return out

STACK_STOP = ""  # why the last linearize stopped short, with the commands that resolve it; empty when the chain is whole

def linearize(repo, proj, trunk, wt):
    with fc_worktree.STACK_LOCK:
        return _linearize(repo, proj, trunk, wt)

def _linearize(repo, proj, trunk, wt):
    """Rebase the project's unmerged task branches into one chain on the current trunk tip, layer on layer, inside the CLI's
    worktree. Returns the branches that now form a clean chain; a conflict stops the chain there and is reported."""
    global STACK_STOP
    STACK_STOP = ""
    chain = chain_order(repo, proj)
    linear, prev = [], trunk
    replaced = fc_worktree.replaced_tips(repo, proj)
    prefix = fc_worktree.task_prefix(repo, proj)
    tips = list(replaced)  # (branch, a tip it no longer has): rebuilt layers, plus every layer this pass rebases
    contains = lambda anc, b: fc_core.sh(["git", "merge-base", "--is-ancestor", anc, b], repo, check=False).returncode == 0
    for b in chain:
        if not contains(prev, b):
            # b still carries the old commits of what it was built on: a layer below that was rebuilt or rebased, a layer still
            # chained as it was but now below a new one, or the trunk itself when it was rewritten (rebased onto a moved main).
            # Replay only b's own commits: start above the deepest tip it was built on whose work the chain already holds: one
            # recorded in this pass (a rebuilt layer, or a layer rebased just now), a chained layer as it is now, or one in the
            # reflog of the layer below (fork-point), which holds a rewrite made before this pass, by hand or by a redo whose
            # replaced ref is gone. Else one in the trunk's reflog; without any, a plain rebase is the best guess.
            old = [(t, "the old base recorded in this pass") for rb, t in tips if rb in linear and contains(t, b)]
            old += [(x, f"{x}, the chained layer it sits on") for x in linear if contains(x, b)]
            fork = fc_core.sh(["git", "merge-base", "--fork-point", prev, b], repo, check=False).stdout.strip()
            old += [(fork, f"the old base from the reflog of {prev}")] if fork else []
            upstream, source = max(old, key=lambda o: int(fc_core.sh(["git", "rev-list", "--count", f"{trunk}..{o[0]}"], repo).stdout)) if old else ("", "")
            if not upstream:
                upstream = fc_core.sh(["git", "merge-base", "--fork-point", trunk, b], repo, check=False).stdout.strip()
                source = f"the old base from the reflog of {trunk}"
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
            fc_core.sh(["git", "update-ref", "-d", f"refs/compose/replaced/{proj.name}/{rb.removeprefix(prefix)}/{t}"], repo, check=False)
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
    commit) is never split, so one bigger than the budget is a layer of its own; groundwork and a task never share a layer."""
    layers = []
    for u in units:
        if layers and (layers[-1][-1]["name"] == "groundwork") == (u["name"] == "groundwork") \
                and sum(x["lines"] for x in layers[-1]) + u["lines"] <= budget:
            layers[-1].append(u)
        else:
            layers.append([u])
    return layers

def test_writers(proj, tasks):
    """(task id, first report, last report) of each task's test-writing teammate `tests-NNN`, in epoch seconds, the latest started
    first: it made its commits between its first and last report. Writers of one test file never run at once, and a later one
    starts only once the earlier one's commits are collected, so the latest whose span holds a commit's author date made it."""
    spans = []
    for t in tasks:
        f = Path(proj) / "results" / "crew" / f"{fc_herdr.agent_name(proj.name, f'tests-{t}')}.status"
        ats = [time.mktime(time.strptime(json.loads(l)["at"], "%Y-%m-%d %H:%M:%S")) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
        if ats:
            spans.append((t, min(ats), max(ats)))
    return sorted(spans, key=lambda s: -s[1])

def applies_without(repo, c, drop, files):
    """Whether commit c applies to its parent with the earlier commits `drop` taken out of `files` first: what a cherry-pick of c
    meets in a layer below theirs. Checked on a scratch index, so the repo's own index and tree are untouched."""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(d, "index")}
        git = lambda *a, patch=None: subprocess.run(["git", *a], cwd=repo, input=patch, capture_output=True, env=env).returncode == 0
        diff = lambda x, *paths: subprocess.run(["git", "diff", "--binary", f"{x}^", x, "--", *paths], cwd=repo, capture_output=True, check=True).stdout
        return git("read-tree", f"{c}^") and all(git("apply", "--cached", "-R", patch=diff(p, *sorted(files))) for p in reversed(drop)) \
            and git("apply", "--cached", patch=diff(c))

def review_units(repo, proj, base, trunk, chain):
    """The project's work as ordered units: every commit the project branch carries over `base` that no task owns (groundwork,
    one unit per commit), then each chain task with its acceptance-test commits first and its own commits after. A test commit
    is a task's when every file it touches is in that task's `protected:`; when its author date falls in the span of a test
    writer whose task protects its files, it is that writer's task's alone. The tests of a task not in the chain yet ride with
    the last one. The layers must apply: an owned commit goes to its writer's task, or without one to the first task that
    protects its files, as long as it applies there without the earlier commits on its files placed higher (a test written in
    its own part of a shared file skips them; one written on top of them does not). Else it goes no lower than the highest of
    them, to the first task at or above it that protects its files; one no task owns is a groundwork unit of its own right
    above the highest one's unit, never inside it."""
    protected = {m["id"]: set(m["protected"]) for m in fc_tasks.code_tasks(fc_tasks.load_tasks(proj))}
    ids = [b.removeprefix(fc_worktree.task_prefix(repo, proj)) for b in chain]
    def unit(name, commits, key=None):
        facts = [commit_facts(repo, c) for c in commits]
        gen = {}
        for _, _, g in facts:
            for f, n in g.items():
                gen[f] = gen.get(f, 0) + n
        return {"name": name, "key": key or name, "commits": commits, "lines": sum(n for _, n, _ in facts), "generated": gen}
    # slot 2i is task i's unit, 2i+1 the groundwork right above it; placed: (commit, slot, files) of each commit placed in one
    ground, slots, placed, writers = [], {}, [], test_writers(proj, protected)
    for c, at in (l.split() for l in fc_core.sh(["git", "log", "--reverse", "--no-merges", "--format=%H %at", f"{base}..{trunk}"], repo).stdout.splitlines()):
        files = set(commit_facts(repo, c)[0])
        writer = next((t for t, a, b in writers if a <= int(at) <= b and files and files <= protected[t]), None)
        owners = [i for i, t in enumerate(ids) if files and files <= protected.get(t, set()) and writer in (None, t)]
        if not owners and files and any(files <= protected[t] for t in set(protected) - set(ids)):
            owners = [len(ids) - 1]
        on = [(p, s) for p, s, f in placed if f & files]
        floor = max((s for _, s in on), default=None)
        fits = lambda slot: floor is None or slot >= floor or applies_without(repo, c, [p for p, s in on if s > slot], files)
        if owners:
            slot = next((2 * i for i in owners if fits(2 * i)), floor)
        else:
            slot = None if floor is None else floor | 1
        if slot is None:
            ground.append(unit("groundwork", [c]))
        else:
            slots.setdefault(slot, []).append(c)
            placed.append((c, slot, files))
    units, prev = ground, trunk
    for i, (b, t) in enumerate(zip(chain, ids)):
        units.append(unit(t, slots.get(2 * i, []) + fc_core.sh(["git", "rev-list", "--reverse", "--no-merges", f"{prev}..{b}"], repo).stdout.split()))
        units += [unit("groundwork", [c], f"groundwork after {t}") for c in slots.get(2 * i + 1, [])]
        prev = b
    return units

def cherry_pick_same(wt, c):
    """Cherry-pick keeping the original committer and date, so a layer rebuilt from unchanged commits gets the same hashes and
    a resubmit pushes nothing new. None when it applied, else the files it conflicts in (aborted, so the tree is as before)."""
    who = fc_core.sh(["git", "show", "-s", "--format=%cn%n%ce%n%cI", c], wt).stdout.splitlines()
    env = {**os.environ, "GIT_COMMITTER_NAME": who[0], "GIT_COMMITTER_EMAIL": who[1], "GIT_COMMITTER_DATE": who[2]}
    p = fc_core.sh(["git", "cherry-pick", "--allow-empty", c], wt, check=False, env=env)
    if p.returncode == 0:
        return None
    conflicts = fc_core.sh(["git", "diff", "--name-only", "--diff-filter=U"], wt, check=False).stdout.split()
    fc_core.sh(["git", "cherry-pick", "--abort"], wt, check=False)
    return conflicts

def record_layers(proj, layers):
    """Remember which tasks each layer holds once the stack is submitted: from then on a layer has a PR, so its tasks stay in it."""
    fc_core.atomic_write(Path(proj) / "layers.json", json.dumps({l["branch"]: list(dict.fromkeys(l.get("keys", l["tasks"]))) for l in layers}, indent=2))

def group_by_record(proj, units, budget, max_prs=None):
    """Groups of units: each recorded layer keeps its own tasks (groundwork commits go to the layer that held groundwork, or
    groundwork above that task), and
    units no layer holds yet are grouped as usual into new layers above. `max_prs` caps the groups (None: no cap): while the
    groups outnumber it, the adjacent unrecorded pair of the same kind (both all-groundwork, or both holding tasks) with the
    fewest combined lines folds, the lower pair on a tie, else the adjacent pair of any kind with the fewest; recorded layers
    never fold.
    [(recorded branch or None, units, folded)]."""
    rec_file = Path(proj) / "layers.json"
    rec = json.loads(rec_file.read_text()) if rec_file.exists() else {}
    groups, seen = [], set()
    for b, keys in rec.items():
        held = [i for i, u in enumerate(units) if i not in seen and u.get("key", u["name"]) in keys]
        seen.update(held)
        if held:
            groups.append((b, [units[i] for i in held], False))
    groups += [(None, g, False) for g in group_units([u for i, u in enumerate(units) if i not in seen], budget)]
    kind = lambda g: "groundwork" if all(u["name"] == "groundwork" for u in g[1]) else "task"
    while max_prs is not None and len(groups) > max_prs:
        pairs = [(0 if kind(a) == kind(b) else 1, sum(u["lines"] for u in a[1]) + sum(u["lines"] for u in b[1]), i)
                 for i, (a, b) in enumerate(zip(groups, groups[1:])) if a[0] is None and b[0] is None]
        if not pairs:
            break
        i = min(pairs)[2]
        groups[i:i + 2] = [(None, groups[i][1] + groups[i + 1][1], True)]
    return groups

def build_layers(repo, proj, base, trunk, chain, wt, budget, max_prs=None):
    """Cut the project into review layers on `base`: branches `<layer_prefix>layer-NN`, each at most `budget` counted lines
    (groundwork first, then tasks with their tests), rebuilt from the commits every time. Returns [{branch, tasks, lines,
    generated, commits, units}] (units: the commits of each entry of tasks, in order). The layers are built on a detached HEAD and
    the layer branches move only once all of them are built and add up to the same tree as the task chain; else nothing is
    changed, STACK_STOP says why, and it returns None."""
    units = review_units(repo, proj, base, trunk, chain)  # groundwork is layers of its own, never mixed into a task's
    groups = group_by_record(proj, units, budget, max_prs)
    layers, tips, prev, prefix = [], [], base, layer_prefix(repo, proj)
    cfg_file = Path(proj) / "verify.json"
    if cfg_file.exists() and fc_core.project_config(proj).get("layer_prefix") != prefix:  # recorded once, so later stacks never have to guess
        fc_core.atomic_write(cfg_file, json.dumps({**fc_core.project_config(proj), "layer_prefix": prefix}, indent=2))
    kept = "the layers and the stack are left as they were"
    def stop(why):
        global STACK_STOP
        fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
        STACK_STOP = why
        fc_core.say(f"stack  STOP  {why}")
    for i, (rec_branch, g, folded) in enumerate(groups, 1):
        branch = rec_branch or f"{prefix}layer-{i:02d}"
        fc_core.sh(["git", "checkout", "-q", "--detach", prev], wt)
        units = []
        for u in g:
            units.append([])
            for c in u["commits"]:
                conflicts = cherry_pick_same(wt, c)
                if conflicts is not None:
                    files = ", ".join(conflicts) or "no file git names"
                    if fc_core.sh(["git", "merge-base", "--is-ancestor", base, trunk], repo, check=False).returncode:  # trunk is behind base
                        at = fc_core.sh(["git", "rev-parse", "--short", base], repo).stdout.strip()
                        stop(f"{c[:7]} does not apply on layer {i}: {trunk} conflicts with {base} {at} in {files}; {kept}. "
                             f"Rebase {trunk} onto {base}, then re-run")
                    else:
                        stop(f"{c[:7]} does not apply on layer {i} (conflicts in {files}); {kept}")
                    return None
                units[-1].append(fc_core.sh(["git", "rev-parse", "HEAD"], wt).stdout.strip())
        gen = {}
        for u in g:
            for f, n in u["generated"].items():
                gen[f] = gen.get(f, 0) + n
        layers.append({"branch": branch, "tasks": [u["name"] for u in g], "keys": [u["key"] for u in g], "lines": sum(u["lines"] for u in g), "generated": gen,
                       "commits": [c for cs in units for c in cs], "units": units,
                       **({"fold_cap": max_prs} if folded else {})})
        prev = fc_core.sh(["git", "rev-parse", "HEAD"], wt).stdout.strip()
        tips.append(prev)
    fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
    if layers and fc_core.sh(["git", "merge-base", "--is-ancestor", base, chain[-1]], repo, check=False).returncode == 0:
        differ = fc_core.sh(["git", "diff", "--name-only", prev, chain[-1]], repo).stdout.split()
        if differ:
            stop(f"the layers differ from {chain[-1]} in {', '.join(differ)}; {kept}")
            return None
    for l, tip in zip(layers, tips):
        fc_core.sh(["git", "branch", "-f", l["branch"], tip], repo)
    for old in fc_core.sh(["git", "branch", "--list", f"{prefix}layer-*", "--format=%(refname:short)"], repo).stdout.split():
        if old not in {l["branch"] for l in layers}:
            fc_core.sh(["git", "branch", "-D", old], repo, check=False)
    return layers

def layer_note(l, budget):
    """One layer as a line for the log: what it holds, its size, and the generated files kept out of the count."""
    names = [t for t in l["tasks"] if t != "groundwork"]
    held = ([f"groundwork x{l['tasks'].count('groundwork')}"] if "groundwork" in l["tasks"] else []) + ([f"task {', '.join(names)}"] if names else [])
    gen = "".join(f"; generated, not counted: {f} ({n} lines)" for f, n in l["generated"].items())
    over = ""
    if l["lines"] > budget:
        over = (f"; over the {budget}-line budget to stay within {l['fold_cap']} PRs" if l.get("fold_cap")
                else f"; over the {budget}-line budget, a {'commit' if l['tasks'] == ['groundwork'] else 'task'} is never split" if len(l["tasks"]) == 1 else "")
    return f"{' + '.join(held)}: {l['lines']} lines{over}{gen}"

def layer_title(repo, proj, l, n, metas):
    """A layer's PR title names its change: the feature's title for a one-PR stack, the story's for a layer that holds every
    task of one story and no other story's, else its one commit's subject, or its first task's title or first commit's subject
    plus ` and N more`. With the Jira-key prefix, and the ` (i/n)` suffix only when the stack has more than one PR."""
    cache = fc_tasks.linear_cache(proj)
    feature, issues = cache.get("feature") or {}, cache.get("issues") or {}
    held = {m["id"] for m in metas if m["id"] in l["tasks"]}
    stories = {story_of(issues, m) for m in metas if m["id"] in held}
    whole = len(stories) == 1 and None not in stories and all(m["id"] in held for m in metas if story_of(issues, m) in stories)
    subjects = [fc_core.sh(["git", "log", "-1", "--format=%s", c], repo).stdout.strip() for c in l["commits"]]
    if n == 1 and feature.get("title"):
        first, more = title_text(feature["title"]), 0
    elif whole and issues[next(iter(stories))].get("title"):
        first, more = title_text(issues[next(iter(stories))]["title"]), 0
    elif len(subjects) == 1:
        first, more = subjects[0], 0
    else:
        tasks = [t for t in l["tasks"] if t != "groundwork"]
        if tasks:
            names = {m["id"]: commit_message(m) for m in metas}
            first, more = names.get(tasks[0], tasks[0]), len(tasks) - 1
        else:
            first, more = subjects[0], len(subjects) - 1
    key = re.match(r"([A-Za-z]+-\d+)-", fc_core.project_config(proj).get("branch") or "")
    idx = int(l["branch"].rsplit("layer-", 1)[1])
    return f"{key.group(1).upper() + ': ' if key else ''}{first}{f' and {more} more' if more else ''}{f' ({idx}/{n})' if n > 1 else ''}"

WHY_CHARS = 400
GITHUB_ISSUE_RE = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)|(?<![\w/.-])([\w.-]+/[\w.-]+)#(\d+)")

def plain(text):
    """Linear markdown as plain text: its escapes (`r\\["x"\\]`) undone and links reduced to their text."""
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>~\"'])", r"\1", text or "")
    return re.sub(r"\[([^\]]*)\]\(<?[^)>]*>?\)", r"\1", text).strip()

def title_text(text):
    """A Linear title as plain text, without the decision cards it cites, as `(C3)` or `(C3, C4)`."""
    return re.sub(r"\s*\((?:C\d+[,/ ]*(?:and )?)+\)", "", plain(text)).strip()

def sentence(text):
    """A title as a sentence (title_text, ending in a full stop)."""
    text = title_text(text)
    return text + ("" if not text or text[-1] in ".!?" else ".")

def first_sentence(desc, key):
    """The first sentence of a description's opening prose that says something about the product, or "": nothing past the
    first heading, no list or next-action line, and no sentence that cites a decision card (C3), a ticket (`<key>-12`), or an
    issue it fixes, so no process text and no brief reaches a reader."""
    cites = re.compile(r"\bC\d+\b|^(Fixes|Closes|Resolves|Card|Decisions?)\b" + (rf"|\b{re.escape(key)}-\d+\b" if key else ""))
    for para in re.split(r"\n\s*\n", plain(desc)):
        para = " ".join(para.split())
        if para.startswith("#"):
            break
        if not para or re.match(r"([-*+]|\d+\.)\s|Next:", para):
            continue
        for s in re.split(r"(?<=[.!?])\s+", para):
            if not cites.search(s) and not GITHUB_ISSUE_RE.search(s) and "github.com/" not in s:
                return sentence(s)
    return ""

def issue_refs(text):
    """The GitHub issues a text names, as `owner/repo#N`, in order: issue URLs and `owner/repo#N` references."""
    return list(dict.fromkeys(f"{a or c}#{b or d}" for a, b, c, d in GITHUB_ISSUE_RE.findall(text or "")))

def linear_url(proj, ident):
    """A Linear issue's link, in the workspace of the repo's `.compose/linear.json` project; the bare id when that is unknown."""
    f = Path(proj).parent / "linear.json"
    m = re.match(r"https://linear\.app/([^/]+)/", json.loads(f.read_text()).get("project") or "" if f.exists() else "")
    return f"[{ident}](https://linear.app/{m.group(1)}/issue/{ident})" if m else ident

def story_of(issues, m):
    """The Linear id of the story a task sits under, or None when its parent is not a cached story (the feature)."""
    parent = (issues.get(m.get("linear")) or {}).get("parentId")
    return parent if parent in issues else None

def layer_why(proj, l, metas, layers):
    """A layer's `## Why`: what its stories are for, in at most three sentences (their titles, and for a one-story layer the
    first sentence of its description; the feature's when its tasks sit under no story), then the GitHub issues they name:
    `Fixes owner/repo#N` on the layer that holds the last of the issue's tasks, `Part of owner/repo#N` below it. An issue
    belongs to the story that names it, else to the feature and all its tasks. A groundwork layer says what it prepares.
    At most WHY_CHARS characters, the issue lines kept whole."""
    cache = fc_tasks.linear_cache(proj)
    feature, issues = cache.get("feature") or {}, cache.get("issues") or {}
    if not any(t != "groundwork" for t in l["tasks"]):
        return [sentence(f"Groundwork for {feature.get('title') or 'the tasks above'}")[:WHY_CHARS]]
    story = lambda m: story_of(issues, m)
    stories = list(dict.fromkeys(story(m) for m in metas if m["id"] in l["tasks"]))
    text = lambda s: issues[s] if s else feature
    said = [sentence(text(s).get("title", "")) for s in stories]
    if len(stories) == 1:
        said.append(first_sentence(text(stories[0]).get("description", ""), (feature.get("id") or "").split("-")[0]))
    owner = {}
    for s in [*dict.fromkeys(story(m) for m in metas if story(m)), None]:
        for ref in issue_refs(text(s).get("title", "") + "\n" + text(s).get("description", "")):
            owner.setdefault(ref, s)
    here = [x for x in layers if x["branch"] == l["branch"]]
    landed = {t for x in layers[:layers.index(here[0]) + 1] for t in x["tasks"]} if here else set(l["tasks"])
    later = {m["id"] for m in metas if m["id"] not in landed and not fc_tasks.linear_done(m)}
    refs = []
    for ref, s in owner.items():
        held = {m["id"] for m in metas if s is None or story(m) == s}
        if held & set(l["tasks"]):
            refs.append(f"- {'Part of' if held & later else 'Fixes'} {ref}")
    room, why = WHY_CHARS - sum(len(r) + 1 for r in refs), []
    for s in filter(None, said[:3]):
        if len(" ".join([*why, s])) <= room:
            why.append(s)
    if not why and said and room > 3:
        why = [said[0][:room - 3].rsplit(" ", 1)[0] + "..."]
    return [" ".join(why), *refs] if why else refs

def layer_body(repo, proj, l, metas, layers=()):
    """A layer's PR body: `## Why` (layer_why), `## What changed` (one line per task, the subject of its first commit that is
    not one of its test commits, else its title; one per groundwork commit), `## How it was tested` (each test command and
    passing verify check once, then whether compose verify passed) and `## Tickets` (its tasks' Linear links), each left out
    when empty. `layers` is the whole stack, bottom first, so an issue's `Fixes` lands on the layer that completes it; without
    it, every task not in this layer is still to come. The layer's size stays on its `layer` line, out of the body."""
    res = Path(proj) / "results"
    read = lambda name: json.loads((res / f"{name}.json").read_text()) if (res / f"{name}.json").exists() else {}
    by_id = {m["id"]: m for m in metas}
    tasks = [by_id[t] for t in dict.fromkeys(l["tasks"]) if t in by_id]
    subject = lambda c: fc_core.sh(["git", "log", "-1", "--format=%s", c], repo).stdout.strip()
    changed = []
    for t, commits in zip(l["tasks"], l["units"]):
        m = by_id.get(t)
        if not m:  # groundwork: one line per commit
            changed += [subject(c) for c in commits]
            continue
        own = [c for c in commits if not set(commit_facts(repo, c)[0]) <= set(m["protected"])]
        changed.append(subject(own[0]) if own else commit_message(m))
    verify = read("verify")
    checks = [c["cmd"] for c in ((verify.get("rounds") or [{}])[-1].get("checks") or []) if c.get("exit") == 0]
    how = list(dict.fromkeys(f"`{t}`" for t in [*(m["test"] for m in tasks), *checks]))
    if verify:
        how.append("compose verify passed" if verify.get("passed") else "compose verify failed")
    sections = [("Why", layer_why(proj, l, metas, list(layers))), ("What changed", [f"- {x}" for x in changed]),
                ("How it was tested", [f"- {x}" for x in how]), ("Tickets", [f"- {linear_url(proj, m['linear'])}" for m in tasks])]
    return "\n\n".join(f"## {h}\n" + "\n".join(lines) for h, lines in sections if lines)

def layer_pr(repo, proj, l, n, metas, layers=()):
    """A layer's PR title and body. The title comes from the layer's commits (`JS-2888: ... (1/4)` when the project branch starts
    with a Jira key); the body says why the layer exists, what changed, and how it was tested (layer_body)."""
    return layer_title(repo, proj, l, n, metas), layer_body(repo, proj, l, metas, layers)

def gh_pr_text(wt, b):
    """The title and body of the PR on branch b, or None when it has none."""
    v = subprocess.run(["gh", "pr", "view", b, "--json", "title,body"], cwd=wt, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return json.loads(v.stdout) if v.returncode == 0 else None

def write_pr_text(proj, wt, b, before, title, body):
    """Write a layer's generated title and body on its PR only when the CLI owns the text: the PR was just created (before is None),
    or its text still equals what the CLI wrote last time (recorded in pr_text.json). A person's or reviewer's edit, and any PR
    from before the record existed, keeps its text; the whole text is regenerated or none of it."""
    rec_file = Path(proj) / "pr_text.json"
    rec = json.loads(rec_file.read_text()) if rec_file.exists() else {}
    last = rec.get(b)
    if before is not None and not (last and (before["title"], before["body"].strip()) == (last["title"], last["body"].strip())):
        return False
    r = subprocess.run(["gh", "pr", "edit", b, "--title", title, "--body", body], cwd=wt, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode == 0:
        fc_core.atomic_write(rec_file, json.dumps({**rec, b: {"title": title, "body": body}}, indent=2))
    return r.returncode == 0

def register_stack(repo, proj, trunk, submit=False, preview=False):
    """Make the project's passed task branches one gh stack, layer by layer, without touching the user's checkout. Branches built
    in parallel from trunk are rebased onto the layer below (tasks own disjoint files, so this is normally clean; a conflict
    stops the chain there and is reported). The stack itself is review layers on the real base (`review_base`, else the default
    branch), not one PR per task and not the project branch as a PR: groundwork and each task's tests are cut into the layers
    too, so the project branch carries nothing the layers do not; when they cannot be built (build_layers' STOP), the layers and
    the registered stack stay as they were. Nothing is pushed unless submit=True; preview=True prints each layer's
    PR title and body as submit would write them, with no gh call. A project whose fast/<project>/ branches were never pushed
    first moves onto the names a new project gets (fc_worktree.rename_legacy_branches)."""
    fc_worktree.rename_legacy_branches(repo, proj)
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
    cap = int(cfg.get("max_stack_prs") or fc_config.settings(fc_config.read_config())[1].get("max_stack_prs") or 10)
    layers = build_layers(repo, proj, base, trunk, linear, wt, budget, cap)
    if layers is None:
        return []
    stack, stack_base = ([l["branch"] for l in layers], base) if layers else (linear, trunk)
    # A stack from an earlier wave is rebuilt with the grown chain: every existing stack that holds any of these branches is
    # unstacked locally (GitHub side untouched), then one init registers the whole chain.
    for b in linear + stack:
        fc_core.sh(["git", "checkout", "-q", b], wt, check=False)
        if gh("view", "--json").returncode == 0:
            gh("unstack", "--local")
    # gh stack 0.2+ refuses to init from a detached HEAD ("finding current branch: not on any branch"), and the trunk is often
    # checked out in the user's tree, so init runs from one of the stack's own branches, which it adopts in place.
    for b in stack:
        if fc_core.sh(["git", "checkout", "-q", b], wt, check=False).returncode == 0:
            break
    p = gh("init", "--base", stack_base, *stack)
    if p.returncode:
        fc_core.say(f"stack  FAIL  {' <- '.join(stack)}: {(p.stderr or p.stdout).strip()[-300:]}")
        fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
        return []
    fc_core.say(f"stack  ok    ({stack_base}) <- {' <- '.join(stack)}")
    for l in layers or []:
        fc_core.say(f"layer  {l['branch'].removeprefix(layer_prefix(repo, proj))}  {layer_note(l, budget)}")
    for l in layers if preview and layers else []:
        title, body = layer_pr(repo, proj, l, len(layers), fc_tasks.code_tasks(fc_tasks.load_tasks(proj)), layers)
        fc_core.say(f"pr     {l['branch']}  {title}\n" + "\n".join(f"    {x}" if x else "" for x in body.splitlines()))
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
                title, body = layer_pr(repo, proj, lay, len(layers), fc_tasks.code_tasks(fc_tasks.load_tasks(proj)), layers)
                write_pr_text(proj, wt, b, before[b], title, body)
    fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)  # free the branches for the user's checkout
    return [stack]

def cmd_stack(a):
    proj = fc_core.project_dir(a); repo = Path(a.repo).resolve()
    trunk = a.trunk or fc_core.current_branch(repo)
    if not register_stack(repo, proj, trunk, submit=a.submit, preview=not a.submit):
        if STACK_STOP:
            sys.exit(1)  # the STOP line already said why and what to do
        print("stack  nothing to register: no unmerged task branches")
