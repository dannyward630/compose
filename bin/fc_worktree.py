import json, os, re, shutil, sys, threading
from pathlib import Path
import fc_core, fc_config, fc_tasks


# ---------- stacks (gh stack) ----------

def replace_branch(repo, proj, branch):
    """Delete a task branch that is about to be rebuilt. Its old tip is kept under a ref: layers stacked above still carry the
    old commits, and the chain rebase must drop them instead of replaying them onto the new layer."""
    tip = fc_core.sh(["git", "rev-parse", "--verify", "-q", branch], repo, check=False).stdout.strip()
    if tip:
        fc_core.sh(["git", "update-ref", f"refs/fast-coding/replaced/{proj.name}/{branch.rsplit('/', 1)[1]}/{tip}", tip], repo)
    fc_core.sh(["git", "branch", "-D", branch], repo, check=False)

def replaced_tips(repo, proj):
    """[(branch, old tip)] for the project's replaced task branches (see replace_branch)."""
    out = fc_core.sh(["git", "for-each-ref", "--format=%(refname) %(objectname)", f"refs/fast-coding/replaced/{proj.name}/"], repo, check=False).stdout
    return [(f"fast/{proj.name}/{ref.split('/')[-2]}", tip) for ref, tip in (l.split() for l in out.splitlines())]

def task_branches(repo, proj):
    """Unmerged task branches with their base branch: {branch: base}. Base is the task branch (if any) the branch was built on."""
    head = fc_core.sh(["git", "rev-parse", "HEAD"], repo).stdout.strip()
    branches = [b for b in fc_core.sh(["git", "branch", "--list", f"fast/{proj.name}/*"], repo, check=False).stdout.split()
                if re.fullmatch(rf"fast/{re.escape(proj.name)}/\d+", b)  # task branches only, not bench tags
                and fc_core.sh(["git", "merge-base", "--is-ancestor", b, head], repo, check=False).returncode != 0]
    out = {}
    for b in branches:
        tid = b.rsplit("/", 1)[1]
        res = proj / "results" / f"{tid}.json"
        base = json.loads(res.read_text()).get("base", "HEAD") if res.exists() else "HEAD"
        out[b] = base if base in branches else None
    return out

def stack_order(repo, proj):
    """All unmerged task branches of the project as one chain, bottom to top: a task after its `after:` tasks, then by id.
    One feature, one stack: every task is a layer, so a reviewer reads one layer's diff at a time. Once tasks are synced, a
    branch whose task is gone from the sync (canceled by a re-plan or an undo) is no layer; its branch is left alone."""
    bases = task_branches(repo, proj)
    metas = {m["id"]: m for m in fc_tasks.code_tasks(fc_tasks.load_tasks(proj))}
    synced = (proj / "results" / "tasks.json").exists()
    ids = sorted(t for t in (b.rsplit("/", 1)[1] for b in bases) if t in metas or not synced)
    order, placed = [], set()
    while len(order) < len(ids):
        progressed = False
        for tid in ids:
            if tid in placed:
                continue
            deps = [d.strip() for d in str(metas.get(tid, {}).get("after") or "").split(",") if d.strip() in ids]
            if all(d in placed for d in deps):
                order.append(tid)
                placed.add(tid)
                progressed = True
        if not progressed:  # a dependency cycle in `after:`; fall back to id order for the rest
            order += [t for t in ids if t not in placed]
            break
    return [f"fast/{proj.name}/{t}" for t in order]

TREEHOUSE_INSTALL = "curl -fsSL https://kunchenguid.github.io/treehouse/install.sh | sh"

def use_treehouse():
    """Slots come from a treehouse pool when treehouse is installed (FAST_CODING_NO_TREEHOUSE=1 turns it off), else from plain
    git worktrees. The pool lives inside the repository (`.treehouse/`, git-ignored): a teammate started in a slot then sits under
    a folder Claude Code already trusts, where a slot under ~/.treehouse would stop at the trust prompt."""
    return bool(shutil.which("treehouse")) and os.environ.get("FAST_CODING_NO_TREEHOUSE") != "1"

def treehouse(repo, *args, check=True):
    return fc_core.sh(["treehouse", "--root", ".", *args], repo, check=check)

def slot_on(repo, branch, holder, detach=False):
    """Lease a treehouse slot and check `branch` out in it (detached for a read-and-rebase worktree). The branch must exist:
    the work lives on branches, a slot is only a place to stand, and returning it keeps the branch.
    The lease is cut from the default branch, never from `branch`: `return` resets a slot to its lease's base, and treehouse
    reuses a slot only when its commit is an ancestor of the next base, so a slot returned onto a task or test branch was
    "in use or dirty" for every lease after it and the pool ran dry while `status` showed it free."""
    exclude_paths(repo, ["/.treehouse/"])
    p = treehouse(repo, "get", "--lease", "--json", "--no-fetch", "--base", default_branch(repo) or branch, "--lease-holder", holder, check=False)
    if p.returncode and "in use or dirty" in p.stdout + p.stderr:
        sys.exit(f"{holder}: " + (pool_shortfall(repo, 1) or p.stderr.strip().splitlines()[-1]))
    if p.returncode:
        raise RuntimeError(f"treehouse get for {holder}\n{p.stdout}\n{p.stderr}")
    path = Path(json.loads(p.stdout)["path"])
    fc_core.sh(["git", "checkout", "-q", *(["--detach"] if detach else []), branch], path)
    return path

def pool_shortfall(repo, need):
    """None when the pool can lease `need` more slots, else one line: how many it needs, how many are free, who holds the rest.
    Free is an available slot, or room under max_trees (treehouse.toml in the main checkout, else treehouse's default 16)."""
    if need <= 0:
        return None
    entries = json.loads(treehouse(repo, "status", "--json", check=False).stdout or "[]")
    cfg = Path(fc_core.sh(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], repo).stdout.strip()).parent / "treehouse.toml"
    m = re.search(r"^\s*max_trees\s*=\s*(\d+)", cfg.read_text(), re.M) if cfg.exists() else None
    cap = int(m.group(1)) if m else 16
    free = sum(e.get("status") == "available" for e in entries) + max(0, cap - len(entries))
    if free >= need:
        return None
    holders = [e.get("lease_holder") or f"slot {e.get('name')} ({e.get('status')})" for e in entries if e.get("status") != "available"]
    return (f"needs {need} worktree slot(s), {free} free of max_trees = {cap}; held by {', '.join(holders)}. "
            "Free slots (fast-coding testcrews --collect, fast-coding clean, treehouse return) or raise max_trees in treehouse.toml")

def is_slot(repo, path):
    """Whether a path is a treehouse slot of this repository's pool, asked of treehouse rather than guessed from the path."""
    if not use_treehouse():
        return False
    p = treehouse(repo, "status", "--json", check=False)
    try:
        return any(Path(e["path"]).resolve() == Path(path).resolve() for e in json.loads(p.stdout or "[]"))
    except (json.JSONDecodeError, KeyError, TypeError):
        return False

def default_branch(repo):
    """The repository's default branch, as treehouse infers it: the remote's HEAD, else main, else master."""
    p = fc_core.sh(["git", "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], repo, check=False)
    for b in ([p.stdout.strip().split("/", 1)[-1]] if p.returncode == 0 else []) + ["main", "master"]:
        if fc_core.sh(["git", "rev-parse", "--verify", "-q", f"refs/heads/{b}"], repo, check=False).returncode == 0:
            return b
    return None

def release_slot(repo, path):
    """Hand a slot back to the pool with its installs intact. fast-coding's own leftovers go first: `return` keeps ignored
    files, so a project's `.fast-coding/` results or graph would otherwise reach the next agent that leases the slot."""
    for d in (".fast-coding", "graft"):
        t = Path(path) / d
        if t.is_symlink() or t.is_file():
            t.unlink()
        elif t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
    treehouse(repo, "return", "--force", str(path), check=False)

def slots(proj, update=None):
    """The project's leased slots by role (`stackroot`, `tests-NNN`), kept in results so later commands find them."""
    f = Path(proj) / "results" / "slots.json"
    have = json.loads(f.read_text()) if f.exists() else {}
    if update is not None:
        have = {k: v for k, v in {**have, **update}.items() if v}
        f.parent.mkdir(parents=True, exist_ok=True)
        fc_core.atomic_write(f, json.dumps(have, indent=2))
    return have

def stack_worktree(repo, proj, trunk):
    """A detached worktree the CLI owns for every gh stack operation, so the user's checkout is never switched.
    Detached because a branch checked out in the user's tree cannot be checked out again elsewhere."""
    with STACK_LOCK:
        held = slots(proj).get("stackroot")
        if held and (Path(held) / ".git").exists():
            wt = Path(held)
            fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
        elif use_treehouse():
            wt = slot_on(repo, trunk, f"fast-coding:{proj.name}:stackroot", detach=True)
            slots(proj, {"stackroot": str(wt)})
        else:
            wt = proj / "worktrees" / ".stackroot"
            if not (wt / ".git").exists():
                fc_core.sh(["git", "worktree", "prune"], repo, check=False)
                fc_core.sh(["git", "worktree", "add", "-q", "--detach", str(wt), trunk], repo)
            else:
                fc_core.sh(["git", "checkout", "-q", "--detach", trunk], wt, check=False)
        ready_checkout(repo, wt)
        tools, link = repo / ".fast-coding", wt / ".fast-coding"  # e2e scripts live there, and verify points them at this worktree
        if tools.is_dir() and not link.exists() and not link.is_symlink():
            link.symlink_to(tools)
            exclude_paths(wt, ["/.fast-coding"])  # the `/.fast-coding/` rule does not cover a link
    return wt

def exclude_paths(wt, rules):
    """Add git ignore rules to the checkout's info/exclude, which no commit carries. A linked worktree shares the main
    checkout's file, so one call covers every checkout of the repository."""
    exclude = Path(fc_core.sh(["git", "rev-parse", "--git-path", "info/exclude"], wt).stdout.strip())
    exclude = exclude if exclude.is_absolute() else wt / exclude
    have = exclude.read_text().splitlines() if exclude.exists() else []
    add = [l for l in rules if l not in have]
    if add:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("".join(l + "\n" for l in have + add))

TOOL_DIRS = ("graft/", ".fast-coding/")

def ignore_tool_files(wt):
    """Keep fast-coding's and graft's own files out of the repository, before anything else is written: every checkout
    ignores them through info/exclude (also graft's `.ignore`), and an existing `.gitignore` gets the two lines, so a clone
    of the delivered branch ignores them too. Returns True when `.gitignore` changed (the caller commits it)."""
    exclude_paths(wt, ["/" + d for d in TOOL_DIRS] + ["/.ignore"])
    gi = wt / ".gitignore"
    if not gi.exists():
        return False
    lines = gi.read_text().splitlines()
    have = {l.strip().strip("/") for l in lines}
    add = [d for d in TOOL_DIRS if d.strip("/") not in have]
    if add:
        gi.write_text("\n".join(lines + add) + "\n")
    return bool(add)

def dep_dirs(wt):
    ignored = fc_core.sh(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"], wt, check=False).stdout.splitlines()
    return [d.rstrip("/") for d in ignored if d.endswith("/") and Path(d.rstrip("/")).name in fc_config.DEP_DIRS]

def stamp_graft_wiring(wt):
    """graft's session-start hook rewrites the wired files whenever graft/.cache/wiring-stamp.json is missing or names another
    version, and graft/ is git-ignored, so every fresh worktree or clone would get a tracked .claude/settings.json edited.
    A stamp at the installed version makes the hook leave tracked wiring alone."""
    if not shutil.which("graft") or fc_core.sh(["git", "ls-files", "--error-unmatch", ".claude/helpers/graft-hooks.cjs"], wt, check=False).returncode:
        return
    version = fc_core.sh(["graft", "--version"], wt, check=False).stdout.strip()
    stamp = wt / "graft" / ".cache" / "wiring-stamp.json"
    if version and not (stamp.exists() and json.loads(stamp.read_text() or "{}").get("version") == version):
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(json.dumps({"version": version, "hosts": ["claude"], "opts": {"global": False, "mcp": True, "hooks": True, "statusline": True}}))

def ready_checkout(repo, wt, borrow=True, install=None):
    """Make a task clone or the CLI's worktree runnable like the main checkout: symlink each git-ignored dependency install
    (node_modules at any depth, vendor, .venv) from it, and keep those links and graft's graph out of git status through
    the checkout's info/exclude. A link is a file to git, so a `node_modules/` rule would not cover it; `/client/node_modules` does.
    `borrow=False` (a task that rewrites a lockfile) links nothing: an install there would write through the link into everyone's.
    `install` (verify.json `install`) runs in the checkout instead of linking: bundlers write a dependency's real path into
    unminified output, so a borrowed install builds different bytes than the project worktree's own. Links from an earlier
    borrow are removed first, so the command never writes through one. Call it with `install` once the checkout sits on the
    commit whose checks will run; it installs again only when that commit's lockfiles differ from the last install's."""
    deps = dep_dirs(repo)
    exclude_paths(wt, ["/graft/", "/.ignore", *("/" + d for d in deps)])
    stamp_graft_wiring(wt)
    if install and borrow:
        stamp = Path(fc_core.sh(["git", "rev-parse", "--path-format=absolute", "--git-path", "fast-coding-install"], wt).stdout.strip())
        locks = "".join(l + "\n" for l in fc_core.sh(["git", "ls-tree", "-r", "HEAD"], wt, check=False).stdout.splitlines()
                        if l.rsplit("/", 1)[-1].split("\t")[-1] in LOCKFILES)
        if stamp.exists() and stamp.read_text() == locks:
            return
        for d in deps:
            if (wt / d).is_symlink():
                (wt / d).unlink()
        fc_core.sh(install, wt)
        stamp.write_text(locks)
        return
    for d in deps if borrow else ():
        link = wt / d
        if link.parent.is_dir() and not link.exists() and not link.is_symlink():
            link.symlink_to(repo / d)

def names_lockfile(meta):
    return any(GENERATED_RE.search(f) for f in meta["files"])

def adopt_installs(repo, wt):
    """A passed task that rewrote a lockfile installed fresh in its own clone. Move that install into the project worktree so
    later tasks and verify borrow the new dependencies; each directory is swapped in with one rename."""
    import shutil
    for d in dep_dirs(wt):
        new, old = wt / d, repo / d
        if new.is_symlink() or not new.is_dir() or not old.parent.is_dir():
            continue
        tmp = old.with_name(old.name + ".adopt")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(new, tmp, symlinks=True)
        aside = old.with_name(old.name + ".old")  # the path is never missing: old moves aside, the copy moves in, then the slow delete
        if aside.is_symlink():
            aside.unlink()
        else:
            shutil.rmtree(aside, ignore_errors=True)
        if os.path.lexists(old):
            old.rename(aside)
        tmp.rename(old)
        if aside.is_symlink():
            aside.unlink()
        else:
            shutil.rmtree(aside, ignore_errors=True)

def mirror_stack_state(repo, wt):
    """gh stack writes its state into the working tree's own git dir. Copy the worktree's stacks into the main checkout's
    file so `gh stack view` works from the user's tree too; stacks sharing a branch are replaced, others kept."""
    src = Path(fc_core.sh(["git", "rev-parse", "--git-dir"], wt).stdout.strip()) / "gh-stack"
    if not src.is_absolute():
        src = wt / src
    if not src.exists():
        return
    mine = json.loads(src.read_text())
    names = {b["branch"] for st in mine.get("stacks", []) for b in st.get("branches", [])}
    targets = set()
    for flag in ("--git-common-dir", "--git-dir"):  # the main checkout and the project worktree both get to see the stack
        d = Path(fc_core.sh(["git", "rev-parse", flag], repo).stdout.strip())
        targets.add((d if d.is_absolute() else repo / d) / "gh-stack")
    for dst in targets:
        if dst.resolve() == src.resolve():
            continue
        theirs = json.loads(dst.read_text()) if dst.exists() else {"schemaVersion": mine.get("schemaVersion", 1), "repository": mine.get("repository", ""), "stacks": []}
        kept = [st for st in theirs.get("stacks", []) if not any(b["branch"] in names for b in st.get("branches", []))]
        theirs["stacks"] = kept + mine.get("stacks", [])
        fc_core.atomic_write(dst, json.dumps(theirs, indent=2))


STACK_LOCK = threading.RLock()  # parallel tasks share one stack worktree; git there must run one thread at a time

GENERATED_RE = re.compile(r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|bun\.lockb?|go\.sum|[^/]+\.lock)$")

LOCKFILE_RE = re.compile(r"(^|/)(bun\.lockb?|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock|uv\.lock|go\.sum)$")

LOCKFILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb", "go.sum", "Cargo.lock", "poetry.lock", "uv.lock",
             "Pipfile.lock", "Gemfile.lock", "composer.lock")
