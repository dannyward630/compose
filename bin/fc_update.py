"""`compose update`: pull the CLI's own checkout --ff-only (rebasing commits only it has onto upstream), relink what compose owns, run doctor.
A run or verify live on this machine freezes the CLI: updating mid-work changes the code under it."""
import atexit, json, os, shlex, sys, time
from pathlib import Path
import fc_core, fc_config, fc_tasks, fc_init, fc_links


def live_dir():
    return fc_config.CONFIG_PATH.parent / "live"

def hold(kind, project, repo):
    """Record that this process is running `kind` (run, verify, resume) on `project` until it exits, where every project of this
    machine can see it: `compose update` refuses while one is live. A process that dies without exiting leaves a file whose pid is dead."""
    f = live_dir() / f"{os.getpid()}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(f, json.dumps({"pid": os.getpid(), "kind": kind, "project": project, "repo": str(Path(repo).resolve()),
                                        "since": time.strftime("%H:%M")}))
    atexit.register(f.unlink, missing_ok=True)

def live_work():
    """The runs and verifies alive on this machine, each {pid, kind, project, repo, since}; the files of dead processes are removed."""
    found = []
    for f in sorted(live_dir().glob("*.json")) if live_dir().exists() else []:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and fc_tasks.pid_alive(d.get("pid")):
            found.append(d)
        else:
            f.unlink(missing_ok=True)
    return found

def refuse_while_verifying(proj, repo):
    """Exit when another process is running `verify` on this project: it stands in the CLI worktree at the stack top, and anything
    that checks other branches out there (stack, top, reword, land) would make its stages judge other code. The hold file is
    matched by project name and by the repository, whichever of its checkouts the verify was started from."""
    common = lambda path: fc_core.sh(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], path, check=False).stdout.strip()
    mine = common(repo)
    for w in live_work():
        if w.get("kind") == "verify" and w.get("project") == Path(proj).name and w["pid"] != os.getpid() and mine and common(w["repo"]) == mine:
            sys.exit(f"STOP  verify is running on {w['project']} (pid {w['pid']}, since {w['since']}) and holds the stack top in the CLI worktree: "
                     "this would check other branches out under it. Wait for it to end, then re-run")

def local_commits(checkout):
    """(branch, upstream, [(mark, sha, subject)]) for the commits the checkout's branch has that its upstream lacks, None when it has none.
    `git cherry` marks each one `-` when its patch is already upstream under another hash, `+` when it is only here."""
    git = lambda *args: fc_core.sh(["git", *args], checkout, check=False)
    branch, upstream = (git("rev-parse", "--abbrev-ref", ref).stdout.strip() for ref in ("HEAD", "@{u}"))
    cherry = git("cherry", "-v", upstream, "HEAD")
    if not upstream or cherry.returncode or not cherry.stdout.strip():
        return None
    return branch, upstream, [tuple(line.split(" ", 2)) for line in cherry.stdout.splitlines()]

def listing(commits, upstream):
    return [f"  {mark} {sha[:12]} {subject} ({'already on ' + upstream if mark == '-' else 'only here'})" for mark, sha, subject in commits]

def diverged(checkout):
    """The state and the way out when the checkout's branch has commits its upstream lacks, else None."""
    found = local_commits(checkout)
    if not found:
        return None
    branch, upstream, commits = found
    n = len(commits)
    if all(mark == "-" for mark, _, _ in commits):
        fix = f"git -C {shlex.quote(str(checkout))} reset --hard {upstream}"
        why = "Every change is already upstream, so drop the local copies:"
    else:
        fix = f"git -C {shlex.quote(str(checkout))} rebase {upstream}"
        why = "Replay them on top of it by hand (changes already upstream are skipped), then continue the rebase:"
    return "\n".join([f"{checkout}: {branch} has {n} commit{'s' if n > 1 else ''} that {upstream} does not, so it cannot fast-forward:",
                      *listing(commits, upstream), why, f"  {fix}", "Then run compose update again."])

def rebase_local(checkout):
    """Replay the commits only this checkout has onto its upstream (git drops the ones already there). The lines to print and
    whether the checkout now sits on top of upstream; a rebase that conflicts is aborted, leaving the checkout as it was."""
    found = local_commits(checkout)
    if not found:
        return [], False
    branch, upstream, commits = found
    before = fc_core.sh(["git", "rev-parse", "--short", "HEAD"], checkout).stdout.strip()
    r = fc_core.sh(["git", "rebase", upstream], checkout, check=False)
    if r.returncode:
        fc_core.sh(["git", "rebase", "--abort"], checkout, check=False)
        said = [l.strip() for l in (r.stdout + r.stderr).splitlines() if l.startswith("CONFLICT") or l.startswith("error:")]
        err = "; ".join(said or (r.stdout + r.stderr).split("\n")[:2])
        return [f"{checkout}: rebasing {branch} onto {upstream} stopped ({err[:300]}); the rebase was aborted and {branch} is back at {before}", diverged(checkout)], False
    kept = [c for c in commits if c[0] == "+"]
    return [f"{checkout}: {branch} had {len(commits)} commit{'s' if len(commits) > 1 else ''} {upstream} lacked; rebased onto it, "
            f"{len(commits) - len(kept)} already upstream dropped:", *listing(commits, upstream),
            *([f"{len(kept)} commit{'s' if len(kept) > 1 else ''} stay only in this checkout: put them on a branch and open a PR, "
               "or they will block the next machine that pulls from here"] if kept else [])], True


def cmd_update(a):
    """Exits 1 while a run or verify is live (unless --force), on local changes, or a failed pull or rebase, else with doctor's code."""
    checkout = Path(__file__).resolve().parents[1]
    live = live_work()
    if live and not a.force:
        sys.exit("\n".join(["compose update stopped: updating the CLI changes the code under work that is running now:",
                            *(f"  {w['project']}: {w['kind']} live since {w['since']} (pid {w['pid']}) in {w['repo']}" for w in live),
                            "Wait for it to end, or run compose update --force to update anyway."]))
    if fc_core.sh(["git", "status", "--porcelain"], checkout, check=False).stdout.strip():
        sys.exit(f"{checkout} has local changes: commit or stash them, then run compose update again")
    p = fc_core.sh(["git", "pull", "--ff-only"], checkout, check=False)
    if p.returncode:
        fetched = fc_core.sh(["git", "fetch", "-q"], checkout, check=False).returncode == 0  # a failed fetch says nothing about upstream
        lines, ok = rebase_local(checkout) if fetched else ([], False)
        if not lines:
            sys.exit(" ".join((p.stdout + p.stderr).split()))
        if not ok:
            sys.exit("\n".join(lines))
        print("\n".join(lines))
    for line in fc_links.relink_owned(checkout):
        print(line)
    sys.exit(fc_init.cmd_doctor(a))
