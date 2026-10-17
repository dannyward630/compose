import json, os, re, sys
from pathlib import Path
import fc_core


# ---------- global config and workspaces ----------
# ~/.compose/config.json: top-level settings, and `workspaces` whose active entry (`workspace`) overrides them.
#   {"workspace": "work",
#    "models": {"implementer": "pi:...", "fallback": "pi:..." or null, "fix": "pi:...",
#               "crew": {"orchestrator": "claude:<id>", "<role>": "claude:<id>", "default": "claude:<id>", "small": "claude:<id>"}},
#    "env": {"TYPESAFE_API_KEY": "..."},
#    "workspaces": {"work": {"openrouter_api_key": "sk-or-..."}, "personal": {"openrouter_api_key": "sk-or-...", "models": {...}}}}
# `default` is the top level itself; it always exists and is active when `workspace` is unset.
# A model id names its harness: `pi:<provider/model>` runs pi, `claude:<model-id>` runs Claude Code with that model, bare
# `claude` runs Claude Code with its default model, anything else is an OpenCode model id. Teammate sessions run in pi or Claude Code.

DEFAULT_MODEL = "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast"  # pi harness; the OpenRouter preset pins Together, then CoreWeave
# Takes over when an attempt errors, times out, is rate-limited, or misses. None by default: GLM passes where gpt-oss kept missing,
# so a second model is opt-in (`models.fallback` in the config).
FALLBACK_MODEL = None
JEV_DIR = Path(__file__).resolve().parent.parent / "jev"  # the browser agent verify's e2e cases drive: its own uv project
# Harness-reported cost is wrong when a request is pinned to a specific host: OpenCode prices by OpenRouter's catalog default, not
# the pinned provider's rate. These override the reported cost (dollars per million input, output) for the models we pin.
PRICES = {"openrouter/openai/gpt-oss-120b": (0.35, 0.75), "openrouter-fast/openai/gpt-oss-120b@preset/gpt-oss-120b-cerebras": (0.35, 0.75),
          "openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast": (0.15, 0.50)}
CONFIG_PATH = Path(os.environ.get("COMPOSE_CONFIG", Path.home() / ".compose" / "config.json"))
ENV_FILE = CONFIG_PATH.parent / ".env"  # TEXT_MODEL* (Mercury review, jev's text helper) and TYPESAFE_* (jev, acceptance); the process env wins
OPENROUTER_KEY = None  # the active workspace's key; None leaves each harness on its own auth store
MAX_DIFF_LINES = 350          # per task branch, added plus deleted, against its base; a reviewer reads one layer at a time
DOC_RE = re.compile(r"(^|/)(docs?|documentation)/|\.(md|mdx|rst|txt|adoc)$", re.I)  # implementers never add documents
DEP_DIRS = ("node_modules", "vendor", ".venv")  # git-ignored installs a task clone borrows from the main checkout
# graft otherwise appends /graft/ to the tracked .gitignore and writes .ignore in every clone it builds or refreshes, which
# the scope check rightly reads as an edit outside the task. Children (pi, OpenCode, their graft calls) inherit this.
os.environ.setdefault("GRAFT_NO_GITIGNORE", "1")
os.environ.setdefault("GRAFT_NO_IGNORE", "1")

CREW_MODELS = {}  # models.crew from the config: role (or default, small) -> claude:<model-id>
LINEAR_KEY = None  # the active workspace's Linear API key, set by apply_config; never printed or passed in argv
WORKSPACE = "default"
CREW_EFFORT = {}  # the same keys -> Claude Code --effort, for entries written as {"model": ..., "effort": ...}
CREW_FALLBACK = {}  # the same keys -> [(model, effort), ...] to try in order when the entry's own model fails its availability probe
PLANNING_ROLES = ("wayfinder",)  # the product owner and the engineering manager plan through it; the team lead delegates, so it never gets `planner`
CREW_DEFAULTS = {"designer": ("claude:claude-opus-5-5", "high")}  # role -> (model, effort) used when models.crew has no entry for it
PROBE_CACHE = Path.home() / ".compose" / "model-probe.json"


def read_config():
    return json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

def write_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(CONFIG_PATH, json.dumps(cfg, indent=2) + "\n")
    CONFIG_PATH.chmod(0o600)  # it holds API keys

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

def apply_config():
    """Point models, keys, and env at the active workspace. Its key wins over the shell and the jev .env, and every
    OpenRouter caller (pi, OpenCode, the Mercury review, jev's e2e text helper) bills to it."""
    global DEFAULT_MODEL, FALLBACK_MODEL, OPENROUTER_KEY, CREW_MODELS, CREW_EFFORT, CREW_FALLBACK, LINEAR_KEY, WORKSPACE
    name, st = settings(read_config())
    WORKSPACE, LINEAR_KEY = name, st.get("linear_api_key") or None  # the CLI moves Linear states with it (full path only)
    models = st.get("models", {})
    crew = models.get("crew") or {}  # an entry is "claude:<id>" or {"model": "claude:<id>", "effort": "high"}
    CREW_MODELS = {k: (v.get("model") if isinstance(v, dict) else v) for k, v in crew.items()}
    CREW_EFFORT = {k: v["effort"] for k, v in crew.items() if isinstance(v, dict) and v.get("effort")}
    entry = lambda e: (e.get("model"), e.get("effort")) if isinstance(e, dict) else (e, None)
    CREW_FALLBACK = {k: [entry(f) for f in (v["fallback"] if isinstance(v["fallback"], list) else [v["fallback"]])]
                     for k, v in crew.items() if isinstance(v, dict) and v.get("fallback")}  # one entry or an ordered list
    DEFAULT_MODEL = models.get("implementer", DEFAULT_MODEL)
    FALLBACK_MODEL = models.get("fallback", FALLBACK_MODEL)
    if "fix" in models:
        os.environ["COMPOSE_FIX_MODEL"] = models["fix"]
    os.environ.update({k: str(v) for k, v in st.get("env", {}).items()})
    if "openrouter_api_key" in st:
        if not st["openrouter_api_key"]:
            sys.exit(f"{CONFIG_PATH}: workspace {name!r} has an empty openrouter_api_key")
        OPENROUTER_KEY = st["openrouter_api_key"]
        os.environ["OPENROUTER_API_KEY"] = os.environ["TEXT_MODEL_API_KEY"] = OPENROUTER_KEY
        os.environ["OPENCODE_CONFIG_CONTENT"] = json.dumps({"provider": {"openrouter": {"options": {"apiKey": OPENROUTER_KEY}}}})
    return name

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
        spaces[name] = {"openrouter_api_key": read_key(name)}  # empty fails loudly on use instead of billing another account
        print(f"added {name}" + ("" if spaces[name]["openrouter_api_key"] else f"; no key yet: pbpaste | compose workspace key {name}"))
    elif action == "key":
        linear = getattr(a, "linear", False)
        key = read_key(name, "Linear" if linear else "OpenRouter")
        if not key:
            sys.exit("no key read; copy it, then: pbpaste | compose workspace key " + name + (" --linear" if linear else ""))
        (cfg if name == "default" else spaces[name])["linear_api_key" if linear else "openrouter_api_key"] = key
        print(f"{name}: {'Linear' if linear else 'OpenRouter'} key set")
    elif action == "remove":
        if name == "default":
            sys.exit("default always exists; clear its key in the config's top level instead")
        del spaces[name]
        if cfg.get("workspace") == name:
            cfg["workspace"] = "default"
            print(f"removed the active workspace {name}; now on default")
    elif name:
        cfg["workspace"] = name
    if action or name:
        write_config(cfg)
    current = cfg.get("workspace") or "default"
    for n, entry in [("default", cfg), *spaces.items()]:
        key = entry.get("openrouter_api_key")
        state = "…" + key[-4:] if key else "not set" if "openrouter_api_key" in entry else "harness auth stores" if n == "default" else "inherits default"
        lin = "set" if entry.get("linear_api_key") else "inherits default" if n != "default" and "linear_api_key" in cfg else "not set"
        print(f"{'*' if n == current else ' '} {n:16} openrouter key {state}, linear key {lin}")
    _, st = settings(cfg)
    m = st.get("models", {})
    print(f"implementer {m.get('implementer', DEFAULT_MODEL)}\nfallback    {m.get('fallback', FALLBACK_MODEL)}\nfix         {m.get('fix', '(implementer)')}")
    show = lambda e: (f"{e.get('model')}" + (f" ({e['effort']} effort)" if e.get("effort") else "")) if isinstance(e, dict) else str(e)
    for role, entry in (m.get("crew") or {}).items():
        fb = entry.get("fallback") if isinstance(entry, dict) else None
        fbs = fb if isinstance(fb, list) else [fb] if fb else []  # one fallback or an ordered list of them
        print(f"crew {role:14} {show(entry)}" + "".join(f", else {show(f)}" for f in fbs))
