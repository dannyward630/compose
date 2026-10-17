import json, os, subprocess
from pathlib import Path
import fc_mcp, fc_core


def is_claude(model):
    return model == "claude" or str(model).startswith("claude:")

def claude_id(model):
    """The --model value for a Claude model id, or None for bare `claude` (Claude Code's own default)."""
    return (model.split(":", 1)[1] or None) if str(model).startswith("claude:") else None


def headless_env():
    """The environment for a Claude Code process the CLI runs headless: no COMPOSE_* at all, above all not the herdr
    tab's role, project, and worktree, so the plugin's hooks treat it as no one's session (a team lead's Stop hook would
    park a watch in it, and its guard would block an implementer's edits). No secret vars either: its tools run project code."""
    return {k: v for k, v in fc_core.clean_env().items() if not k.startswith("COMPOSE_")}

NO_ATTRIBUTION = json.dumps({"attribution": {"commit": "", "pr": ""}})  # `--settings` outranks the user settings: no Co-Authored-By trailer or "Generated with" line on any commit a Claude session makes
def crew_settings(role, cwd):
    """The `--settings` JSON of a teammate session in `cwd`."""
    enabled = {}
    try:
        enabled = (json.loads((Path.home() / ".claude" / "settings.json").read_text()).get("enabledPlugins") or {})
    except (OSError, ValueError):
        pass
    keep = fc_mcp.keeps_skills(role)
    return json.dumps({"attribution": {"commit": "", "pr": ""}, "env": {"ENABLE_TOOL_SEARCH": "true"},
                       "enabledPlugins": {k: False for k in enabled if not k.startswith("compose@") and not (keep and k.startswith("figma@"))}})

def claude_once(cwd, prompt, timeout=900, model=None):
    """One-shot baseline through Claude Code on the subscription. Marginal cost $0; the CLI's own cost figure is recorded for reference."""
    # --model is explicit because ~/.claude/settings.json may carry a launcher-injected default that headless runs cannot use.
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model or os.environ.get("COMPOSE_CLAUDE_MODEL", "claude-sonnet-5-5"),
           "--settings", NO_ATTRIBUTION, "--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write,Bash,Grep,Glob"]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env=headless_env())
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        out = {}
    if out.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(out.get('result', ''))[:300]}")
    usage = out.get("usage", {})
    tokens_in = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    fc_core.LEDGER.add("claude-subscription", tokens_in, usage.get("output_tokens", 0), 0.0)
    return None, str(out.get("result", ""))[-1500:], out.get("num_turns", 0), {"tokens_in": tokens_in, "tokens_out": usage.get("output_tokens", 0),
                                                                                "cost": 0.0, "reference_cost": out.get("total_cost_usd")}


def claude_trusted(path):
    """Whether Claude Code has accepted its folder-trust dialog for `path` (None when it cannot tell), by Claude Code's own rule:
    in a repo, the repo's main checkout or a folder from `path` up to the repo's top accepted it, and a folder above the repo never
    counts, so a repo nested in a trusted folder still asks; outside git, `path` or any parent accepted it.
    An untrusted folder parks a new session at the trust prompt, so `crew start` says so instead of starting one."""
    try:
        projects = json.loads((Path.home() / ".claude.json").read_text()).get("projects") or {}
    except (OSError, json.JSONDecodeError):
        return None
    git = fc_core.sh(["git", "-C", str(path), "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"], None, check=False)
    top, common = map(Path, git.stdout.splitlines()) if git.returncode == 0 else (None, None)
    main = common.parent if common and common.name == ".git" else top  # a linked worktree's main checkout; a submodule is its own
    folders = [p for p in (path, *path.parents) if not top or p.is_relative_to(top)] + ([main] if main else [])
    return any((projects.get(str(p)) or {}).get("hasTrustDialogAccepted") for p in folders)

def untrusted(path):
    return (f"Claude Code has never trusted {path}, so a session there would wait at its trust prompt. Run `claude` in "
            f"{path} once and accept the prompt (the product owner decides that), then start this teammate again.")
