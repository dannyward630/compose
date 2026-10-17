"""Run one setup step: the plain path and the Textual app both go through run_step."""
import subprocess
import fc_config, fc_keys, fc_steps, fc_links, fc_pi


# The write rows' writers: compose relinks the links it owns, pi gets its openrouter-fast provider, the .env its TEXT_MODEL lines.
WRITERS = {
    "pi openrouter-fast provider": lambda checkout: fc_pi.declare_provider(fc_pi.PI_MODELS),
    "compose CLI link": lambda checkout: fc_links.relink_owned(checkout),
    "compose skill link": lambda checkout: fc_links.relink_owned(checkout),
    "bp link": lambda checkout: fc_links.relink_owned(checkout),
    "TEXT_MODEL lines": lambda checkout: fc_pi.write_text_model(fc_config.ENV_FILE),
}

def run_step(row, checkout, yes, claude, terminal):
    """(state, line): state is ok, claude, skipped, manual, done, or failed; the line never holds a key value.
    A passing check is never run (ok). A claude row without claude waits (claude). manual, key, and interactive-without-
    terminal rows are never run (manual or skipped, the line says what to do by hand), a designer row is skipped under yes;
    run and interactive rows shell out to install, write rows call their writer, then the check runs again: done, or failed
    with the last line of the command's error output."""
    name, _, install, level, needs_claude, mode = row
    ok, detail = fc_steps.check(row, checkout)
    if ok:
        return "ok", f"{name}: ok"
    if needs_claude and not claude:
        return "claude", f"{name}: waiting on Claude Code"
    if mode == "manual":
        return "manual", f"{name}: run by hand: {install}"
    if mode == "key":
        kind = next((k for k in ("openrouter", "typesafe", "linear", "figma") if k in name.lower()), "")
        return "skipped", f"{name}: {fc_keys.skipped_line(kind, fc_config.WORKSPACE) or install}"
    if level == "designer" and yes:
        return "skipped", f"{name}: designer extra, skipped"
    if mode == "interactive" and not terminal:
        return "skipped", f"{name}: run by hand: {install}"
    said = ""
    if mode == "write":
        got = WRITERS[name](checkout)
        said = "; ".join(got) if isinstance(got, list) else got
    elif mode == "run":
        p = subprocess.run(install, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        said = "\n".join(l.strip() for l in (p.stdout or "").splitlines() if l.strip())
    else:  # interactive with a terminal: the installer keeps the terminal
        subprocess.run(install, shell=True)
    ok, detail = fc_steps.check(row, checkout)
    if ok:
        return "done", said if mode == "write" and said else f"{name}: done"
    if mode == "run" and said:
        return "failed", f"{name}: {said.splitlines()[-1]}"
    return "failed", said or (f"{name}: {detail}" if detail else f"{name}: failed")
