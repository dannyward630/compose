"""Green check results kept by the git tree they ran on, so the same command on the same files is not run twice.
Imports only lower modules."""
import hashlib, json, os, tempfile, time
from pathlib import Path
import fc_core

def tree_of(repo, rev=None):
    """The git tree sha of a branch tip (`rev`) or of the files in `repo` right now, uncommitted edits included; "" when it
    cannot be told (not a git folder). The checkout's own index is left alone."""
    if rev:
        p = fc_core.sh(["git", "rev-parse", "--verify", "-q", f"{rev}^{{tree}}"], repo, check=False)
        return p.stdout.strip() if p.returncode == 0 else ""
    index = fc_core.sh(["git", "rev-parse", "--git-path", "index"], repo, check=False)
    if index.returncode:
        return ""
    real = Path(repo) / index.stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if real.exists():
            (Path(tmp) / "index").write_bytes(real.read_bytes())
        if fc_core.sh(["git", "add", "-A"], repo, check=False, env=env).returncode:
            return ""
        p = fc_core.sh(["git", "write-tree"], repo, check=False, env=env)
    return p.stdout.strip() if p.returncode == 0 else ""

def path_of(proj, tree, cmd):
    return Path(proj) / "results" / "green" / f"{tree}-{hashlib.sha1(cmd.encode()).hexdigest()[:12]}.json"

def record(proj, tree, cmd, code):
    """Keep a green result for `cmd` on `tree`; a red one takes back the green it had, so it is never reused."""
    if not tree:
        return
    path = path_of(proj, tree, cmd)
    if code == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        fc_core.atomic_write(path, json.dumps({"tree": tree, "cmd": cmd, "at": time.strftime("%Y-%m-%d %H:%M"), "exit": 0}))
    else:
        path.unlink(missing_ok=True)

def taken(proj, tree, cmd, fresh=False):
    """The line saying `cmd` is green on `tree` and is not rerun, or None when there is no green result to take (or `fresh`)."""
    if not tree or fresh:
        return None
    try:
        got = json.loads(path_of(proj, tree, cmd).read_text())
    except (OSError, ValueError):
        return None
    if got.get("exit") != 0 or got.get("tree") != tree or got.get("cmd") != cmd:
        return None
    return f"{cmd} green on tree {tree[:12]} at {got.get('at', '?')}, not rerun"
