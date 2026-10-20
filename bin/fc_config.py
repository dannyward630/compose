import json, os, re, sys
from pathlib import Path
import fc_auth, fc_core


# ---------- global config and workspaces ----------
# ~/.compose/config.json: top-level settings, and `workspaces` whose active entry (`workspace`) overrides them. It never
# holds a key: every key lives in auth.json (fc_auth), and old ones are moved there on the next apply_config.
#   {"workspace": "work",
#    "models": {"implementer": "pi:...", "fallback": "pi:..." or null, "fallback_after": 2, "test_reader": "claude:<id>" or null, "fix": "pi:...",
#               "crew": {"orchestrator": "claude:<id>", "<role>": "claude:<id>", "default": "claude:<id>", "small": "claude:<id>"}},
#    "env": {"OTHER_VAR": "..."},
#    "parallel": 20,
#    "workspaces": {"work": {}, "personal": {"models": {...}}}}
# `default` is the top level itself; it always exists and is active when `workspace` is unset.
# `parallel` is how many agents start at once: the tasks of run and resume (else 3) and testcrews' writers (else all at once).
# A command's own flag wins. designcrews never reads it: Figma's per-minute write rate limit caps its builders.
# A model id names its harness: `pi:<provider/model>` runs pi, `claude:<model-id>` runs Claude Code with that model, bare
# `claude` runs Claude Code with its default model, anything else is an OpenCode model id. Teammate sessions run in pi or Claude Code.

DEFAULT_MODEL = "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast"  # pi harness; the OpenRouter preset pins Together, then CoreWeave
# Takes over after FALLBACK_AFTER failed attempts (misses, errors, timeouts) on a task's model, or at once on a rate limit. None by
# default: GLM passes where gpt-oss kept missing, so a second model is opt-in (`models.fallback` in the config).
FALLBACK_MODEL = None
FALLBACK_AFTER = 2
# Reads a failed test run and writes the implementer's short fix brief, in Claude Code with read-only tools. None sends the raw tail alone.
TEST_READER = "claude:claude-haiku-5-5"
JEV_DIR = Path(__file__).resolve().parent.parent / "jev"  # the browser agent verify's e2e cases drive: its own uv project
# Harness-reported cost is wrong when a request is pinned to a specific host: OpenCode prices by OpenRouter's catalog default, not
# the pinned provider's rate. These override the reported cost (dollars per million input, output) for the models we pin.
PRICES = {"openrouter/openai/gpt-oss-120b": (0.35, 0.75), "openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras": (0.35, 0.75),
          "openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast": (0.15, 0.50)}
CONFIG_PATH = Path(os.environ.get("COMPOSE_CONFIG", Path.home() / ".compose" / "config.json"))
ENV_FILE = CONFIG_PATH.parent / ".env"  # TEXT_MODEL* (Mercury review, jev's text helper) and TYPESAFE_MODEL; keys live in auth.json; the process env wins
AUTH_PATH = CONFIG_PATH.parent / "auth.json"  # every key: see fc_auth; mode 600 in a 700 directory
OPENROUTER_KEY = None  # the active workspace's key; None leaves each harness on its own auth store
MAX_DIFF_LINES = 350          # per task branch, added plus deleted, against its base; a reviewer reads one layer at a time
DOC_RE = re.compile(r"(^|/)(docs?|documentation)/|\.(md|mdx|rst|txt|adoc)$", re.I)  # implementers never add documents
DEP_DIRS = ("node_modules", "vendor", ".venv")  # git-ignored installs a task clone borrows from the main checkout
# trail otherwise appends /graft/ to the tracked .gitignore and writes .ignore in every clone it builds or refreshes, which
# the scope check rightly reads as an edit outside the task. Children (pi, OpenCode, their trail calls) inherit this.
os.environ.setdefault("GRAFT_NO_GITIGNORE", "1")
os.environ.setdefault("GRAFT_NO_IGNORE", "1")

CREW_MODELS = {}  # models.crew from the config: role (or default, small) -> claude:<model-id>
PARALLEL = None  # `parallel` from the config; None keeps each command's own default
LINEAR_KEY = None  # the active workspace's Linear API key, set by apply_config; never printed or passed in argv
WORKSPACE = "default"
CREW_EFFORT = {}  # the same keys -> Claude Code --effort, for entries written as {"model": ..., "effort": ...}
CREW_FALLBACK = {}  # the same keys -> [(model, effort), ...] to try in order when the entry's own model fails its availability probe
PLANNING_ROLES = ("wayfinder",)  # the product owner and the engineering manager plan through it; the team lead delegates, so it never gets `planner`
CREW_DEFAULTS = {"designer": ("claude:claude-opus-5-5", "high")}  # role -> (model, effort) used when models.crew has no entry for it
PROBE_CACHE = CONFIG_PATH.parent / "model-probe.json"


def read_config():
    return json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

def write_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(CONFIG_PATH, json.dumps(cfg, indent=2) + "\n", keep_secrets=True)  # a config env's *_API_KEY stays as it is
    CONFIG_PATH.chmod(0o600)  # settings stay private

def settings(cfg):
    """The active workspace's settings: the top level with the workspace's entry merged over it, one level deep."""
    name = cfg.get("workspace") or "default"
    if name != "default" and name not in cfg.get("workspaces", {}):
        sys.exit(f"{CONFIG_PATH}: active workspace {name!r} is not under \"workspaces\"")
    ws = cfg.get("workspaces", {}).get(name, {})
    out = {k: v for k, v in cfg.items() if k not in ("workspace", "workspaces")}
    for k, v in ws.items():
        out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return name, out

def apply_config(move=True):
    """Point models, keys, and env at the active workspace. Its key wins over the shell and the jev .env, and every
    OpenRouter caller (pi, OpenCode, the Mercury review, jev's e2e text helper) bills to it."""
    global DEFAULT_MODEL, FALLBACK_MODEL, FALLBACK_AFTER, TEST_READER, OPENROUTER_KEY, CREW_MODELS, CREW_EFFORT, CREW_FALLBACK, LINEAR_KEY, WORKSPACE, PARALLEL
    if move:
        for line in fc_auth.move_keys(CONFIG_PATH, ENV_FILE, AUTH_PATH):  # old keys leave config.json and .env first, stdout stays clean
            print(line, file=sys.stderr)
    name, st = settings(read_config())
    PARALLEL = st.get("parallel")
    if PARALLEL is not None and (type(PARALLEL) is not int or PARALLEL < 1):
        sys.exit(f"{CONFIG_PATH}: parallel must be a whole number of 1 or more, not {PARALLEL!r}")
    WORKSPACE = name
    auth = fc_auth.read_auth(AUTH_PATH)
    held = auth.get("workspaces", {})
    own = held.get(name, {}).get("openrouter")
    if own is not None and not own:  # the workspace's own empty key must not bill default's account
        sys.exit(f"{AUTH_PATH}: workspace {name!r} has an empty openrouter key")
    OPENROUTER_KEY = own if own is not None else held.get("default", {}).get("openrouter")
    LINEAR_KEY = fc_auth.workspace_key(auth, name, "linear") or None  # the CLI moves Linear states with it (full path only)
    models = st.get("models", {})
    crew = models.get("crew") or {}  # an entry is "claude:<id>" or {"model": "claude:<id>", "effort": "high"}
    CREW_MODELS = {k: (v.get("model") if isinstance(v, dict) else v) for k, v in crew.items()}
    CREW_EFFORT = {k: v["effort"] for k, v in crew.items() if isinstance(v, dict) and v.get("effort")}
    entry = lambda e: (e.get("model"), e.get("effort")) if isinstance(e, dict) else (e, None)
    CREW_FALLBACK = {k: [entry(f) for f in (v["fallback"] if isinstance(v["fallback"], list) else [v["fallback"]])]
                     for k, v in crew.items() if isinstance(v, dict) and v.get("fallback")}  # one entry or an ordered list
    DEFAULT_MODEL = models.get("implementer", DEFAULT_MODEL)
    FALLBACK_MODEL = models.get("fallback", FALLBACK_MODEL)
    FALLBACK_AFTER = int(models.get("fallback_after", FALLBACK_AFTER))
    TEST_READER = models.get("test_reader", TEST_READER)
    if "fix" in models:
        os.environ["COMPOSE_FIX_MODEL"] = models["fix"]
    os.environ.update({k: str(v) for k, v in st.get("env", {}).items()})
    fc_core.SECRET_VARS.update(k for k in st.get("env", {}) if k.endswith("_API_KEY"))
    if OPENROUTER_KEY:
        os.environ["OPENROUTER_API_KEY"] = os.environ["TEXT_MODEL_API_KEY"] = OPENROUTER_KEY
    if auth.get("typesafe"):
        os.environ["TYPESAFE_API_KEY"] = auth["typesafe"]
    dotenv = fc_core.load_env(ENV_FILE)
    fc_core.SECRET_VALUES.update(v for v in [OPENROUTER_KEY, LINEAR_KEY, auth.get("typesafe"), *(key for ws in held.values() for key in ws.values()),
                                             *(dotenv[k].strip('"') for k in dotenv if k in fc_core.SECRET_VARS or k.endswith("_API_KEY"))] if v)
    return name

def needs_linear_key(what):
    """The line `what` exits with when the active workspace has no Linear key. On a scratch config (a compose under `compose
    timed`) storing a key would only fill the scratch one: the fix is to run the command directly."""
    if fc_core.is_scratch(CONFIG_PATH):
        return (f"{what} needs a Linear key, but runs on a scratch config with no workspace and no keys, as every command under "
                f"`compose timed` does: run compose's own commands directly")
    return f"{what} needs a Linear key for workspace {WORKSPACE!r}: pbpaste | compose workspace key {WORKSPACE} --linear"

def typesafe_key(env, what):
    """The TypeSafe key in `env` (apply_config puts auth.json's there), for every Jev call. Missing, it raises the line saying
    why: on a scratch config (a compose under `compose timed`) there are no keys by design, so the fix is to run the command
    directly; otherwise the command that stores it in auth.json."""
    if key := env.get("TYPESAFE_API_KEY"):
        return key
    if fc_core.is_scratch(CONFIG_PATH):
        raise RuntimeError(f"{what} needs a TypeSafe key, but runs on a scratch config with no workspace and no keys, as every "
                           f"command under `compose timed` does: run compose's own commands directly")
    raise RuntimeError(f"{what} needs a TypeSafe key, and {AUTH_PATH} has none: pbpaste | compose workspace key {WORKSPACE} --typesafe")

def openrouter_key():
    """The OpenRouter key a harness bills to: the workspace's from auth.json, else the shell's. None leaves the harness on its own auth store."""
    return OPENROUTER_KEY or os.environ.get("OPENROUTER_API_KEY") or None

def key_file(key):
    """A 0600 file beside the config holding `key`, for a harness that reads its key from a file its config names, not from the env its tools inherit."""
    f = CONFIG_PATH.parent / "openrouter.key"
    if not (f.exists() and f.read_text() == key):
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
            out.write(key)
        fc_core.note_home_write(f, tmp)
        os.replace(tmp, f)  # parallel OpenCode turns never read a half-written key
    return f

WORKSPACE_ACTIONS = ("add", "key", "remove")

def read_key(name, kind="OpenRouter"):
    """The key from piped stdin (`pbpaste | compose workspace key personal`) or a hidden prompt; never an argument,
    so it stays out of shell history, the process list, and chat."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    import getpass
    return getpass.getpass(f"{kind} API key for {name} (empty to set later): ").strip()

def cmd_workspace(a):
    """`workspace` lists, `workspace <name>` switches, `workspace add|key|remove <name>` manages. `default` always exists:
    it is the config's top level, with no overrides."""
    cfg = read_config()
    spaces = cfg.setdefault("workspaces", {})
    action, name = (a.name, a.target) if a.name in WORKSPACE_ACTIONS else (None, a.name)
    if action and not name:
        sys.exit(f"usage: compose workspace {action} <name>")
    if name and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        sys.exit(f"workspace names are letters, digits, - and _: {name!r}")
    if name and name != "default" and action != "add" and name not in spaces:
        sys.exit(f"no workspace {name!r}; have: {', '.join(['default', *spaces])}. Create it: compose workspace add {name}")
    if action == "add":
        if name == "default" or name in WORKSPACE_ACTIONS or name in spaces:
            sys.exit(f"workspace {name!r} already exists" if name in spaces or name == "default" else f"{name!r} is a reserved word")
        key = read_key(name)
        spaces[name] = {}
        fc_auth.set_key(AUTH_PATH, name, "openrouter", key)  # empty fails loudly on use instead of billing another account
        print(f"added {name}" + ("" if key else f"; no key yet: pbpaste | compose workspace key {name}"))
    elif action == "key":
        linear = getattr(a, "linear", False)
        ts = getattr(a, "typesafe", False)
        key = read_key(name, "TypeSafe" if ts else "Linear" if linear else "OpenRouter")
        if not key:
            sys.exit("no key read; copy it, then: pbpaste | compose workspace key " + name + (" --typesafe" if ts else " --linear" if linear else ""))
        fc_auth.set_key(AUTH_PATH, name, "typesafe" if ts else "linear" if linear else "openrouter", key)
        print("TypeSafe key set (every workspace uses it)" if ts else f"{name}: {'Linear' if linear else 'OpenRouter'} key set")
    elif action == "remove":
        if name == "default":
            sys.exit("default always exists; clear its key in the config's top level instead")
        del spaces[name]
        auth = fc_auth.read_auth(AUTH_PATH)
        auth.get("workspaces", {}).pop(name, None)
        fc_auth.write_auth(AUTH_PATH, auth)
        if cfg.get("workspace") == name:
            cfg["workspace"] = "default"
            print(f"removed the active workspace {name}; now on default")
    elif name:
        cfg["workspace"] = name
    if action or name:
        write_config(cfg)
    auth = fc_auth.read_auth(AUTH_PATH)
    held = auth.get("workspaces", {})
    dlin = held.get("default", {}).get("linear")
    current = cfg.get("workspace") or "default"
    for n in ["default", *spaces]:
        entry = held.get(n, {})
        key = entry.get("openrouter")
        state = "…" + key[-4:] if key else "not set" if "openrouter" in entry else "harness auth stores" if n == "default" else "inherits default"
        lin = "set" if entry.get("linear") else "inherits default" if n != "default" and dlin else "not set"
        print(f"{'*' if n == current else ' '} {n:16} openrouter key {state}, linear key {lin}")
    _, st = settings(cfg)
    m = st.get("models", {})
    print(f"implementer {m.get('implementer', DEFAULT_MODEL)}\nfallback    {m.get('fallback', FALLBACK_MODEL)} after {m.get('fallback_after', FALLBACK_AFTER)} failed attempts\n"
          f"test reader {m.get('test_reader', TEST_READER)}\nfix         {m.get('fix', '(implementer)')}")
    show = lambda e: (f"{e.get('model')}" + (f" ({e['effort']} effort)" if e.get("effort") else "")) if isinstance(e, dict) else str(e)
    for role, entry in (m.get("crew") or {}).items():
        fb = entry.get("fallback") if isinstance(entry, dict) else None
        fbs = fb if isinstance(fb, list) else [fb] if fb else []  # one fallback or an ordered list of them
        print(f"crew {role:14} {show(entry)}" + "".join(f", else {show(f)}" for f in fbs))
