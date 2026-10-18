import json, re, sys
from pathlib import Path
import fc_core, fc_tasks, fc_herdr, fc_status


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
        sys.exit("no tasks on Linear under this feature carry a compose block")
    print(f"project {proj.name}   {len(tasks)} tasks   stack order (bottom first): {' <- '.join(m['id'] for m in tasks)}")
    print(f"  {'id':4} {'title':40} {'after':10} {'linear':9} files | protected | test")
    for m in tasks:
        after = str(m.get("after") or "").strip() or "-"
        linear = str(m.get("linear") or "").strip() or "-"
        owned = ', '.join(m['nodes']) if m.get('kind') == 'design' else ', '.join(m['files'])
        print(f"  {m['id']:4} {m.get('title', '')[:40]:40} {after:10} {linear:9} {owned or '-'} | {', '.join(m['protected']) or '-'} | {m['test']}")
    # Only tasks still to run can clash; a later wave may legitimately touch a file an already-merged task owned.
    trunk_head = fc_status.project_head(repo, proj)
    facts = fc_status.branch_facts(repo, proj, trunk_head)
    open_tasks = [m for m in tasks if fc_status.task_state(repo, proj, m, trunk_head, facts)["state"].split(" ")[0] not in ("merged", "hand_done", "already_green")]
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
    # Waves are what `run` still dispatches: an unmerged passed layer can still clash above, but it never runs again.
    to_run = [m for m in open_tasks if not fc_tasks.task_finished(proj, m)]
    waves = run_waves(to_run)
    if waves:
        print(f"\n  run waves (each wave in parallel): {'  then  '.join(', '.join(w) for w in waves)}")
    if len(to_run) >= 3 and len(waves) > len(to_run) / 2:
        print(f"\n  WARNING SERIAL CHAIN: {len(to_run)} tasks run in {len(waves)} waves, mostly one after another. Keep an `after:` "
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
    to_run = [t for t in tasks if (t["linear_state"] or "").lower() not in ("in review", "done")]  # a passed or merged layer never runs again
    waves = run_waves(to_run)
    if len(to_run) >= 3 and len(waves) > len(to_run) / 2:
        gaps.append(f"serial chain: {len(to_run)} tasks run in {len(waves)} waves, mostly one after another")
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
            if not meta["files"] and not meta["delete"]:
                gaps.append("empty `files:`")
            if not meta["protected"]:
                gaps.append("empty `protected:`")
            if re.search(r"(?i)contract\.md|\b(?:from|in|per|see) the (?:groundwork )?contract\b", desc):
                gaps.append("the brief points at the contract, which implementers never see: state its signatures and exact lines in the brief")
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
