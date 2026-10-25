import json, shutil, subprocess, time
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

CARRY_NOTE = "WORK KEPT FROM BEFORE A PLAN CHANGE: {files} already hold edits made under the old brief. Keep what still fits the brief below and change what does not.\n\n"

def carry_note(files):
    return CARRY_NOTE.format(files=", ".join(files)) if files else ""

def _apply_one(wt, base, name):
    """One kept file's change onto the fresh clone; False (and the file back as HEAD has it) when it does not apply."""
    made = subprocess.run(["git", "diff", "--binary", base, "FETCH_HEAD", "--", name], cwd=wt, capture_output=True)
    if made.returncode or not made.stdout or subprocess.run(["git", "apply", "--3way", "--index"], cwd=wt, input=made.stdout, capture_output=True).returncode:
        subprocess.run(["git", "checkout", "HEAD", "--", name], cwd=wt, capture_output=True)
        return False
    return True

def carried(last):
    """The paused block a released task keeps in its `running` result, so a stopped run still carries its edits next start."""
    data = json.loads(last) if last else {}
    block = data.get("paused") if data.get("status") == "paused" else data.get("kept_from")
    return {"kept_from": block} if block else {}

def carry_over(repo, wt, meta, last):
    """Start a released task from the edits its pause kept: those the new brief still owns, that the chosen `keep` allows
    and that apply to the fresh clone. Returns the files kept; the rest stay on the ref."""
    paused = last.get("paused") if last.get("status") == "paused" else last.get("kept_from")
    choice = (paused or {}).get("choice") or "keep"
    if not paused or choice == "discard":
        return []
    ref, base = paused["ref"], paused["base"]
    wanted = [f for f in paused["files"] if choice != "part" or f in paused.get("keep", [])]
    if not wanted:
        return []
    if subprocess.run(["git", "fetch", "-q", str(repo), ref], cwd=wt, capture_output=True).returncode:
        fc_core.say(f"{meta['id']} kept    nothing; the ref {ref} could not be fetched")
        return []
    kept, dropped = [], []
    for f in wanted:
        (kept if f in meta["files"] and _apply_one(wt, base, f) else dropped).append(f)
    fc_core.say(f"{meta['id']} kept    {', '.join(kept) or 'nothing'}" + (f"; dropped {', '.join(dropped)}: they stay on {ref}" if dropped else ""))
    return kept
