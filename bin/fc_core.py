import hashlib, json, os, re, subprocess, sys, threading, time
from pathlib import Path


# ---------- output and cost ledger ----------

def now():
    return time.strftime("%H:%M:%S")

def fmt(seconds):
    return f"{seconds:.1f}s" if seconds < 90 else f"{int(seconds // 60)}m{seconds % 60:04.1f}s"

def say(msg):
    print(f"[{now()}] {msg}", flush=True)

class Ledger:
    """Tokens and dollars per provider. cost=None means tokens are known but no price is configured."""
    def __init__(self):
        self.lock, self.rows = threading.Lock(), {}
    def add(self, provider, tokens_in=0, tokens_out=0, cost=None, calls=1):
        with self.lock:
            r = self.rows.setdefault(provider, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0, "priced": True})
            r["calls"] += calls; r["tokens_in"] += tokens_in; r["tokens_out"] += tokens_out
            if cost is None:
                r["priced"] = False
            else:
                r["cost"] += cost
    def total(self):
        return sum(r["cost"] for r in self.rows.values())
    def line(self):
        parts = [f"{p} ${r['cost']:.4f}" + ("" if r["priced"] else "+?") + f" ({r['calls']} calls, {r['tokens_in']}in/{r['tokens_out']}out)"
                 for p, r in sorted(self.rows.items())]
        return "cost  " + "  ".join(parts) + f"  total ${self.total():.4f}" if parts else "cost  none"
    def snapshot(self):
        return {**{p: dict(r) for p, r in self.rows.items()}, "total": round(self.total(), 6)}

LEDGER = Ledger()

def sh(cmd, cwd, timeout=None, check=True, env=None):
    p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                       timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    if check and p.returncode:
        raise RuntimeError(f"{cmd}\n{p.stdout}\n{p.stderr}")
    return p

def worktrees(repo):
    """Every checkout of this repository (main plus linked worktrees), as paths."""
    out = []
    for line in sh(["git", "worktree", "list", "--porcelain"], repo, check=False).stdout.splitlines():
        if line.startswith("worktree "):
            out.append(Path(line[len("worktree "):]))
    return out or [Path(repo).resolve()]

def project_config(proj):
    f = Path(proj) / "verify.json"
    return json.loads(f.read_text()) if f.exists() else {}

def project_branch(proj):
    """The project's branch: `branch` in its verify.json (`init --branch`), else `fast-coding/<name>`."""
    return project_config(proj).get("branch") or f"fast-coding/{Path(proj).name}"

def commit_convention(proj):
    """A repo's commit convention, declared once as `commit_convention` in verify.json: {"types": [...], "example": "feat: ..."}.
    verify.json is where the CLI already reads per-repo settings, and it needs no parsing of prose in AGENTS.md. None when undeclared."""
    conv = project_config(proj).get("commit_convention")
    return conv if isinstance(conv, dict) and conv.get("types") else None

COMMIT_TYPES = {"feat": ["feat"], "fix": ["fix", "feat"], "test": ["test"], "deps": ["chore", "build"], "docs": ["docs", "chore"]}  # kind -> allowed types, best first


def typed(message, kind, conv):
    """`message` with the convention's type prefix for what the commit is (feat, fix, test, deps, docs); plain when no convention
    is declared or it allows none of the kind's types."""
    t = next((t for t in COMMIT_TYPES[kind] if conv and t in conv["types"]), None)
    return f"{t}: {message}" if t else message

def commit_rule(conv):
    """The sentence a brief carries so whoever commits follows the repo's convention; empty when none is declared."""
    if not conv:
        return ""
    return (f"Start every commit message with a type prefix, one of {', '.join(conv['types'])} (for example `{conv.get('example') or conv['types'][0] + ': ...'}`): "
            "tests are test, dependencies and config are chore or build, docs are docs, the rest feat or fix. ")


def all_projects(repo):
    """{project name: (worktree path, project dir)} over every worktree. A project lives in its own worktree
    (`fast-coding-<name>` on the project's branch, `fast-coding/<name>` unless `init --branch` chose one), created by `init`; older projects may sit in the main checkout."""
    found = {}
    for wt in worktrees(repo):
        root = wt / ".fast-coding"
        if not root.exists():
            continue
        on_branch = sh(["git", "branch", "--show-current"], wt, check=False).stdout.strip()
        for p in sorted(root.iterdir()):
            if not (p.is_dir() and (p / "verify.json").exists()):
                continue
            # Once a project branch is merged, its folder shows up in other checkouts too; the project's own worktree
            # (checked out on its branch) wins, so clean and status keep pointing at the right place.
            if p.name not in found or on_branch == project_branch(p):
                found[p.name] = (wt, p)
    return found

def project_dir(a):
    """Resolve --project to its directory, and point a.repo at the worktree that holds it, so every git command runs there."""
    repo = Path(a.repo).resolve()
    projects = all_projects(repo)
    if a.project:
        if a.project not in projects:
            sys.exit(f"no project {a.project!r}; `fast-coding init --project {a.project}` creates one. Known: {sorted(projects)}")
        wt, proj = projects[a.project]
    else:
        if len(projects) != 1:
            sys.exit(f"pass --project; found {sorted(projects)}")
        wt, proj = next(iter(projects.values()))
    a.repo = str(wt)
    return proj


def atomic_write(path, text):
    """Write a state file so a reader sees the old file or the new one, never a half-written or empty one."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def digests(root, files):
    return {f: hashlib.sha256((root / f).read_bytes()).hexdigest() if (root / f).exists() else None for f in files}


def figma_key(text):
    """The Figma file key in a figma.com URL or a bare key, else None."""
    m = re.search(r"figma\.com/(?:design|board|slides)/([A-Za-z0-9]+)(/branch/([A-Za-z0-9]+))?", text)
    if m:
        return m.group(3) or m.group(1)
    return text if re.fullmatch(r"[A-Za-z0-9]{10,40}", text) else None


def current_branch(repo):
    """The branch the user is on: the stack's trunk. A detached HEAD falls back to main."""
    return sh(["git", "branch", "--show-current"], repo).stdout.strip() or "main"


# ---------- verify ----------

def load_env(path):
    """KEY=value lines of an env file; a missing file is an empty env (keys may all come from the process env)."""
    env = {}
    path = Path(path).expanduser()
    for line in (path.read_text() if path.exists() else "").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def port_listening(port):
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def report_time(at):
    return time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S"))


# ---------- init / clean ----------

def project_after(proj):
    """The project this one is built on (`init --after`), or None. Its branch is the review base in verify.json."""
    cfg = project_config(proj)
    base = cfg.get("review_base", "")
    return cfg.get("after") or (base.removeprefix("fast-coding/") if base.startswith("fast-coding/") else None)
