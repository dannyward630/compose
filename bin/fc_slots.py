import json, time
from pathlib import Path
import fc_core, fc_worktree


# ---------- the treehouse slots of teammates started with --cwd or --work-repo ----------

def crew_slot(c):
    """The worktree a teammate's record says it works in on its own branch (`--work-repo`'s, else `--cwd`'s), None for a session
    that runs in the project worktree."""
    return c.get("worktree") or (c.get("cwd") if c.get("branch") else None)

def release_slots(files, closed):
    """Give the slot of each teammate record in `files` (crew json) back to the pool once `closed(record)` says its session ended
    and nothing in the slot is uncommitted; its branch stays. A slot with uncommitted paths stays leased, one line naming them.
    Returns the slots returned."""
    freed = []
    for f in files:
        c = json.loads(f.read_text())
        if not isinstance(c, dict) or not crew_slot(c) or c.get("released") or not closed(c):
            continue
        slot = Path(crew_slot(c))
        top = fc_worktree.common_dir(slot)
        if not top or not fc_worktree.is_slot(top.parent, slot):
            continue
        if dirty := fc_worktree.dirty_paths(slot):
            fc_core.say(f"slot  {c['name']}'s {slot} stays leased: {len(dirty)} uncommitted path(s), {', '.join(dirty[:3])}")
            continue
        fc_core.sh(["git", "checkout", "-q", "--detach"], slot, check=False)  # the branch stays; the slot no longer holds it
        if fc_worktree.release_slot(top.parent, slot):
            freed.append(slot)
            c["released"] = time.strftime("%Y-%m-%d %H:%M:%S")
            fc_core.atomic_write(f, json.dumps(c, indent=2))
    return freed
