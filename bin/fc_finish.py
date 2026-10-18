"""The end of every setup run: the steps' outcome, herdr's config, the PATH line, models merged, key rules, the implementer probe, the exit code."""
import os
import shutil
import sys
from pathlib import Path
import fc_auth, fc_config, fc_defaults, fc_herdrconf, fc_keys, fc_links, fc_steps

CLAUDE_MISSING = "Claude Code is missing: install it with curl -fsSL https://claude.ai/install.sh | bash, log in, then run compose setup again"


def finish(results, yes):
    """(lines, code) from results, the [(row name, state)] of run_step; code 0 when compose is ready, else 1."""
    fc_config.apply_config()  # the keys auth.json holds now go into the env before anything reads them
    yes = yes or not sys.stdin.isatty()
    state = dict(results)
    groups = {s: [] for s in ("failed", "claude", "manual", "skipped")}
    for name, _, _, _, _, mode in fc_steps.STEPS:
        if mode != "key" and state.get(name) in groups:
            groups[state.get(name)].append(name)
    lines = [f"{head}: " + ", ".join(names) for head, names in
             (("failed", groups["failed"]), ("waiting on Claude Code", groups["claude"]),
              ("run by hand", groups["manual"]), ("skipped", groups["skipped"])) if names]
    lines += fc_herdrconf.apply_herdr_config(Path.home() / ".config" / "herdr" / "config.toml",
                                             Path(__file__).resolve().parents[1] / "setup" / "herdr.toml")[1]
    if (path := fc_links.path_line()):
        lines += ["~/.local/bin is not on your PATH; add this line to your shell profile:", path]
    cfg = fc_config.read_config()
    merged, added = fc_defaults.merge_models(cfg)
    if added:
        fc_config.write_config(merged)
        names = [k for k in fc_defaults.DEFAULT_MODELS if k != "crew" and k not in cfg.get("models", {})]
        n = len(merged["models"]["crew"]) - len(cfg.get("models", {}).get("crew", {}))
        if names or n:
            lines.append("added default models to ~/.compose/config.json: " +
                         ", ".join(names + ([f"crew ({n} roles)"] if n else [])))
    lines += fc_defaults.PRESET_STEPS
    ws, _ = fc_config.settings(cfg)
    status = fc_keys.key_status(fc_auth.read_auth(fc_config.AUTH_PATH), ws, fc_steps.FRAMELINK_ENV)
    missing = [k for k in ("openrouter", "typesafe") if not status[k]]
    if fc_keys.linear_state(status, fc_keys.linear_connected()) in ("missing", "unknown"):
        missing.append("linear")
    lines += [fc_keys.skipped_line(k, ws) for k in missing]
    ready = not missing
    probe_ok = None
    if not yes and status["openrouter"]:
        ok, probe_lines = fc_defaults.probe_implementer(merged)
        lines += [line for line in probe_lines if line not in fc_defaults.PRESET_STEPS]
        ready = ready and ok
        probe_ok = ok
    if not shutil.which("claude"):
        lines.append(CLAUDE_MISSING)
        return lines, 1
    if not ready and not yes:
        reasons = []
        if missing:
            reasons.append("missing " + ", ".join({"openrouter": "OpenRouter", "typesafe": "TypeSafe", "linear": "Linear"}[k] for k in missing))
        if probe_ok is False:
            reasons.append("the model probe failed")
        lines.append("setup is not finished: " + "; ".join(reasons))
        return lines, 1
    if yes:
        rows = [(name, install) for name, _, install, level, _, _ in fc_steps.STEPS
                if level == "required" and state.get(name) not in ("ok", "done")]
        if rows:
            lines += ["compose is installed but not ready:", *[f"  {name}: {install}" for name, install in rows],
                      "run compose setup in a terminal to finish"]
            return lines, 0
    lines += ["compose is ready", "next: run claude in a pane and type /compose" if os.environ.get("HERDR_ENV") else "next: run compose to open herdr"]
    return lines, 0
