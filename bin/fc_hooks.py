import hashlib, json, os, re, shlex, sys
from pathlib import Path
import fc_core, fc_config, fc_worktree

# ---------- Claude Code hooks: `guard` keeps the team lead and planner out of code, `skillcheck` names changed skill files ----------

GUARDED_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
GUARDED_ROLES = ("orchestrator", "planner")
CLI_FILE = re.compile(r"/\.compose/(linear\.json|[^/]+/(linear|verify)\.json|[^/]+/scratch/.+|[^/]+/pr/[^/]+\.md)$")  # the team lead's own: the CLI's config and the layers' PR text

def guard_decision(tool, path, role):
    """None to allow, else why not. The team lead writes Linear, the CLI's JSON, and the layers' PR text; code, tests, and docs
    are teammate work. The toolsmith edits in its own worktree of the compose repo, never in a shared checkout of it."""
    if role not in (*GUARDED_ROLES, "toolsmith") or tool not in GUARDED_TOOLS or not path:
        return None
    p = Path(path).expanduser().resolve()
    d = next((x for x in [p.parent, *p.parents] if x.exists()), Path("/"))
    if role == "toolsmith":
        return f"A toolsmith never edits {why}: fix on a branch in your own worktree of the compose repo." if (why := fc_worktree.shared_checkout(d, fc_core.CLI_CHECKOUT)) else None
    if CLI_FILE.search(str(p)):
        return None
    if fc_core.sh(["git", "rev-parse", "--is-inside-work-tree"], d, check=False).returncode != 0:
        return None  # scratch outside any repository, e.g. a brief in /tmp
    return (f"The team lead and the planner never edit code, tests, config, or docs ({p.name}). Hand it to a teammate: "
            f"`compose crew start --role <job> --brief -`, or put it in a task issue for `run`.")

def toplevel(path):
    """The worktree root `path` is in, or None."""
    top = fc_core.sh(["git", "rev-parse", "--show-toplevel"], path, check=False).stdout.strip() if Path(path).is_dir() else ""
    return Path(top).resolve() if top else None

def switch_decision(command, cwd, role, shared):
    """None to allow, else why not. A crew session started without its own worktree runs in the project worktree `shared` with the
    team lead, so a `git checkout` or `git switch` there moves the lead's HEAD, and the stack then reads the wrong task branches.
    Restoring files (`git checkout -- path`) and any checkout in another worktree (`cd`, `git -C`) are fine."""
    if role != "crew" or not command or not shared or not toplevel(shared):
        return None
    here = Path(cwd or ".")
    for segment in re.split(r"&&|\|\||[;|\n]", command):
        try:
            words = shlex.split(segment)
        except ValueError:
            continue
        if words[:1] == ["cd"] and len(words) > 1:
            here = here / Path(words[1]).expanduser()
        if words[:1] != ["git"]:
            continue
        i, where = 1, here
        while i < len(words) and words[i].startswith("-"):  # git's own options; -C and -c take a value
            if words[i] == "-C" and i + 1 < len(words):
                where = where / Path(words[i + 1]).expanduser()
            i += 2 if words[i] in ("-C", "-c") else 1
        verb, rest = (words[i] if i < len(words) else ""), words[i + 1:]
        if verb in ("checkout", "switch") and rest[:1] not in (["--"], ["-p"], ["--patch"]) and toplevel(where) == toplevel(shared):
            return (f"`git {verb}` here would move the team lead's HEAD: {shared} is the project worktree, shared with the team lead. Work in a "
                    f"worktree of your own (ask for `crew start --work-repo` or `--cwd`) and run git there with `git -C <worktree>`.")
    return None

def edit_paths(ev):
    raise NotImplementedError

def cmd_guard(a):
    """Claude Code PreToolUse hook (the plugin's hooks.json): deny the team lead's file edits inside a repository, and a crew
    session's branch switch in the shared project worktree."""
    try:
        ev = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    ti = ev.get("tool_input") or {}
    role = os.environ.get("COMPOSE_ROLE")
    why = (switch_decision(ti.get("command"), ev.get("cwd"), role, os.environ.get("COMPOSE_REPO")) if ev.get("tool_name") == "Bash"
           else guard_decision(ev.get("tool_name"), ti.get("file_path") or ti.get("notebook_path"), role))
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": why}}))

SKILL_DIR = Path.home() / ".claude" / "skills" / "compose"  # the main checkout every live session reads: a merge changes it
SKILL_SEEN = fc_config.CONFIG_PATH.parent / "skill-seen"  # one file per session: the skill files' blob hashes it last saw
# ponytail: never pruned, a few hundred bytes per session; prune by mtime if the directory grows
SKILL_FILES = ("SKILL.md", "sections/*.md", "commands/*.md")

def skill_hashes():
    """Each skill file's git blob hash, by absolute path."""
    files = sorted(f for g in SKILL_FILES for f in SKILL_DIR.resolve().glob(g))
    if not files:
        raise FileNotFoundError(SKILL_DIR)
    return {str(f): hashlib.sha1(b"blob %d\0" % len(b := f.read_bytes()) + b).hexdigest() for f in files}

def skill_changed(seen, cur):
    """The skill files whose hash differs between two skill_hashes() results: changed, added, or removed."""
    return sorted(p for p in cur.keys() | seen.keys() if cur.get(p) != seen.get(p))

def skill_notice(session):
    """Record the skill version this session sees; the notice naming what changed since it last saw one, else None."""
    if not session:  # no session id: every such caller would share one file
        return None
    cur, f = skill_hashes(), SKILL_SEEN / f"{session}.json"
    seen = json.loads(f.read_text()) if f.exists() else None
    if seen != cur:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cur))
    changed = skill_changed(seen or {}, cur)
    if seen is None or not changed:
        return None
    return f"compose's skill changed since you read it: {', '.join(changed)}. Re-read the ones your role uses before acting."

def cmd_skillcheck(a):
    """Claude Code UserPromptSubmit and PostToolUse(Skill) hook: a session with a role, or one that loaded the compose skill
    (the Skill tool, or a typed /compose command), hears once when the skill's files changed. Any error prints nothing."""
    try:
        ev = json.load(sys.stdin)
        session = re.sub(r"[^\w-]", "", ev.get("session_id") or "")
        if not session:
            return
        loads = "/" + (ev.get("tool_input") or {}).get("skill", "") if ev.get("hook_event_name") == "PostToolUse" else ev.get("prompt", "")
        if re.match(r"/compose(:|\s|$)", loads):
            skill_notice(session)  # the version it loads now is the one it read
        elif os.environ.get("COMPOSE_ROLE") or (SKILL_SEEN / f"{session}.json").exists():
            if ev.get("hook_event_name") == "UserPromptSubmit" and (note := skill_notice(session)):
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": note}}))
    except Exception:
        pass
