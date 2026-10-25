import json, shutil, time
from pathlib import Path
import fc_core, fc_readguard

def snapshot(repo, proj, tid, wt, base):
    """Commit the whole state of a task's worktree (tracked, new and deleted files) on top of `base` and fetch it into `repo` as
    refs/compose/<project>/paused/<id>. Returns (that ref, the files the state changes against `base`)."""
    ident = ["-c", "user.name=compose", "-c", "user.email=compose@localhost"]
    fc_core.sh(["git", "add", "-A"], wt)
    tree = fc_core.sh(["git", "write-tree"], wt).stdout.strip()
    commit = fc_core.sh(["git", *ident, "commit-tree", tree, "-p", base, "-m", f"paused {tid}"], wt).stdout.strip()
    fc_core.sh(["git", "update-ref", f"refs/compose/paused/{tid}", commit], wt)
    ref = f"refs/compose/{Path(proj).name}/paused/{tid}"
    fc_core.sh(["git", "fetch", "-q", str(wt), f"+refs/compose/paused/{tid}:{ref}"], repo)
    return ref, fc_core.sh(["git", "diff", "--name-only", base, commit], wt).stdout.split()

def paused_result(repo, proj, meta, wt, base, base_name, log, attempts, cost, started, reason):
    """A task a hold stopped mid-flight: its work kept on a ref, its worktree removed, the result written as `paused`
    (the run treats it as pending again). `attempts` is the count spent and `cost` what the turns cost."""
    try:
        ref, files = snapshot(repo, proj, meta["id"], wt, base)
    except RuntimeError as e:  # the edits could not be kept: the clone stays as they are, and the result says why
        log.append({"error": f"pause snapshot failed: {str(e)[-500:]}"})
        failed = {"id": meta["id"], "title": meta.get("title"), "status": "failed", "model": meta["model"], "attempts": attempts,
                  "seconds": round(time.time() - started, 1), "cost": round(cost, 6), "branch": "-", "base": base_name, "worktree": str(wt), "log": log}
        fc_core.say(f"{meta['id']} ERROR   pause snapshot failed; the clone is kept at {wt}: {str(e)[-200:]}")
        fc_core.atomic_write(Path(proj) / "results" / f"{meta['id']}.json", json.dumps(failed, indent=2))
        return failed
    shutil.rmtree(wt, ignore_errors=True)
    fc_readguard.guard_file(wt).unlink(missing_ok=True)  # its read counts go with the clone
    total = round(time.time() - started, 1)
    fc_core.say(f"{meta['id']} paused  {reason}; work kept on {ref} ({len(files)} files)")
    result = {"id": meta["id"], "title": meta.get("title"), "status": "paused", "model": meta["model"], "attempts": attempts,
              "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), "seconds": total, "cost": round(cost, 6),
              "branch": "-", "base": base_name, "log": log,
              "paused": {"ref": ref, "base": base, "files": files, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "reason": reason}}
    (Path(proj) / "results").mkdir(exist_ok=True)
    fc_core.atomic_write(Path(proj) / "results" / f"{meta['id']}.json", json.dumps(result, indent=2))
    return result
