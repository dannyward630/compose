import atexit, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, time
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
    """The project's branch: `branch` in its verify.json (`init --branch`), else `compose/<name>`."""
    return project_config(proj).get("branch") or f"compose/{Path(proj).name}"

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
    (`compose-<name>` on the project's branch, `compose/<name>` unless `init --branch` chose one), created by `init`; older projects may sit in the main checkout."""
    found = {}
    for wt in worktrees(repo):
        root = wt / ".compose"
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
            sys.exit(f"no project {a.project!r}; `compose init --project {a.project}` creates one. Known: {sorted(projects)}")
        wt, proj = projects[a.project]
    else:
        if len(projects) != 1:
            sys.exit(f"pass --project; found {sorted(projects)}")
        wt, proj = next(iter(projects.values()))
    a.repo = str(wt)
    return proj


def atomic_write(path, text, keep_secrets=False):
    """Write a state file so a reader sees the old file or the new one, never a half-written or empty one. Secrets are
    scrubbed unless the file is the one that holds them (keep_secrets)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text if keep_secrets else scrub(text))
    os.replace(tmp, path)


# ---------- secrets: never in the env of project code, never in a text the CLI sends to a model or keeps ----------
# apply_config exports keys for the CLI's own callers (pi, OpenCode, the text model, jev). A test that prints its env must not
# find them, and nothing it prints may carry them to a model or into results/.
SECRET_VARS = {"OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "TYPESAFE_API_KEY", "OPENCODE_CONFIG_CONTENT"}  # apply_config adds the config env's *_API_KEY names
SECRET_VALUES = set()  # apply_config adds the workspace's keys and those in ~/.compose/.env
REDACTED = "<redacted>"

def clean_env(env=None):
    """`env` (the process env by default) without the secret vars, and with a scratch COMPOSE_CONFIG: for every process that
    runs project code, a model's tools included."""
    return {**{k: v for k, v in (os.environ if env is None else env).items() if k not in SECRET_VARS}, "COMPOSE_CONFIG": scratch_config()}

# ---------- the user's ~/.compose: project code gets its own, and a write to the user's is flagged ----------
# When the project is compose itself, the code under test is a compose that reads and writes its config, keys, and caches.
# HOME stays as it is: git's identity and the toolchains' caches (rustup, uv, npm, gh) live there and tests need them.
SCRATCH_CONFIGS = []  # removed when the CLI exits
CLI_OWN = {"model-probe.json", "skill-seen", "tool-bugs", "tool-bugs.jsonl", "test-slots"}  # what other compose processes write there at any time

def scratch_config():
    """A COMPOSE_CONFIG in a fresh, empty directory of its own."""
    if not SCRATCH_CONFIGS:
        atexit.register(remove_scratch)
    SCRATCH_CONFIGS.append(tempfile.mkdtemp(prefix="compose-config-"))
    return str(Path(SCRATCH_CONFIGS[-1]) / "config.json")

def remove_scratch():
    """Remove every scratch config this process made: at exit, and on a SIGTERM or SIGHUP, which would skip exit otherwise."""
    while SCRATCH_CONFIGS:
        shutil.rmtree(SCRATCH_CONFIGS.pop(), ignore_errors=True)

def home_state():
    """name -> (size, mtime) of each entry of the user's ~/.compose, the CLI's own logs and caches left out."""
    home = Path.home() / ".compose"
    entries = [p for p in home.iterdir() if p.name not in CLI_OWN and not p.name.endswith(".tmp")] if home.is_dir() else []
    return {p.name: (st.st_size, st.st_mtime_ns) for p in entries for st in [p.lstat()]}

def flag_home(before, what):
    """Say which entries of the user's ~/.compose changed since `before` (a home_state()) while `what` ran, if any."""
    after = home_state()
    changed = sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))
    if changed:
        say(f"WARNING: ~/.compose changed while {what} ran: {', '.join(changed)}. Project code gets its own COMPOSE_CONFIG, "
            "so this one wrote the user's by its own path; check those files")

def scrub(text):
    """text with the value of every secret var in the process env, and every key apply_config collected, as <redacted>."""
    values = {os.environ.get(k) or "" for k in SECRET_VARS} | SECRET_VALUES
    for v in sorted((v for v in values if len(v) >= 8), key=len, reverse=True):  # a short value would redact ordinary text
        text = text.replace(v, REDACTED)
    return text

class Scrubbed:
    """A text stream that scrubs what it writes: the CLI's stdout and stderr, which a detached run writes to results/<cmd>.log."""
    def __init__(self, stream):
        self.stream = stream
    def write(self, text):
        return self.stream.write(scrub(text))
    def __getattr__(self, name):
        return getattr(self.stream, name)


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

def session_id():
    """This session's identity: the herdr pane it runs in (herdr never reuses a pane id), else None outside herdr. The engineering
    manager stays in the pane it was started in, so a Claude session resumed there is the same one."""
    return os.environ.get("HERDR_PANE_ID") or None


# ---------- init / clean ----------

def project_after(proj):
    """The project this one is built on (`init --after`), or None. Its branch is the review base in verify.json."""
    cfg = project_config(proj)
    base = cfg.get("review_base", "")
    return cfg.get("after") or (base.removeprefix("compose/") if base.startswith("compose/") else None)


# ---------- showing paths ----------

def tilde(text):
    """text (a path or a line) with the home directory followed by / shown as ~/."""
    return str(text).replace(str(Path.home()) + "/", "~/")
