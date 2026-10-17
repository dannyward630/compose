"""The end of every setup run: models merged, key rules, the implementer probe, the exit code."""
import shutil
import fc_auth, fc_config, fc_keys, fc_steps, fc_defaults

CLAUDE_MISSING = "Claude Code is missing: install it with curl -fsSL https://claude.ai/install.sh | bash, log in, then run compose setup again"


def finish(results, yes):
    """(lines, code) from results, the [(row name, state)] of run_step; code 0 when compose is ready, else 1."""
    cfg = fc_config.read_config()
    merged, lines = fc_defaults.merge_models(cfg)
    fc_config.write_config(merged)
    lines += fc_defaults.PRESET_STEPS
    ws, _ = fc_config.settings(cfg)
    status = fc_keys.key_status(fc_auth.read_auth(fc_config.AUTH_PATH), ws, fc_steps.FRAMELINK_ENV)
    missing = [k for k in ("openrouter", "typesafe") if not status[k]]
    if fc_keys.linear_state(status, fc_keys.linear_connected()) in ("missing", "unknown"):
        missing.append("linear")
    lines += [fc_keys.skipped_line(k, ws) for k in missing]
    ready = not missing
    if not yes and status["openrouter"]:
        ok, probe_lines = fc_defaults.probe_implementer(merged)
        lines += probe_lines
        ready = ready and ok
    if not shutil.which("claude"):
        lines.append(CLAUDE_MISSING)
        return lines, 1
    if not ready and not yes:
        lines.append("setup is not finished")
        return lines, 1
    lines += ["compose is ready", "next: run compose to open herdr"]
    return lines, 0
