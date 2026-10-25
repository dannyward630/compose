"""A task's context pack from the repo's trail graph, with trail's own banners and learning blocks dropped."""
import re, shutil
import fc_core, fc_worktree


LEARNING_RE = re.compile(r"^from (a learning|.+'s learning)")  # heads a trail learning block in `trail ask` output
BANNERS = ("[trail]", "⬆ trail", "· no learnings")  # trail's own notes there, not code

def trail_pack(wt, query, repo=None, limit=6, cap=12000):
    """Context pack from a trail graph, $0 and no model. The graph is git-ignored, so a worktree gets its own graph:
    the main repo's graph is copied in as a cache, at the same place (graft/ or .trail/cache/), and rebuilt from the
    worktree's files (so a bench reset is not leaked)."""
    src = repo and fc_worktree.graph_dir(repo)
    if src and not fc_worktree.graph_dir(wt):
        shutil.copytree(src, wt / src.relative_to(repo), dirs_exist_ok=True)
        (wt / ".trail" / "cache").mkdir(parents=True, exist_ok=True)
        fc_core.sh(["trail", "build", "--no-gitignore", "--no-ignore", str(wt)], wt, timeout=600, check=False)
    if not fc_worktree.graph_dir(wt):
        return ""
    p = fc_core.sh(["trail", "ask", query, "--source", "-n", str(limit), "--no-refresh", str(wt)], wt, timeout=60, check=False)
    if p.returncode:
        return ""
    lines, skip = [], None  # "learning": inside a learning block, which runs to a blank line; "blank": right after a banner
    for l in p.stdout.splitlines():
        if LEARNING_RE.match(l) or l.startswith(BANNERS):
            skip = "learning" if LEARNING_RE.match(l) else "blank"
        elif not l.strip() and skip:
            skip = None  # the blank line closing what was dropped goes with it
        elif skip != "learning":
            skip = None
            lines.append(l)
    return "\n".join(lines).strip()[:cap]
