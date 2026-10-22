"""Run one setup step: the setup flow goes through run_step."""
import subprocess
import fc_core, fc_config, fc_checks, fc_keys, fc_steps, fc_links, fc_pi, fc_harness


# The write rows' writers: each compose link row makes its own owned link, pi gets its openrouter-fast provider, the .env its TEXT_MODEL lines.
def link_writer(name):
    """Make only the owned link named name, with the link and target fc_checks.owned_links gives that row; its one line."""
    return lambda checkout: fc_links.ensure_link(*next((link, target) for n, link, target in fc_checks.owned_links(checkout) if n == name))[1]

WRITERS = {
    "pi openrouter-fast provider": lambda checkout: fc_pi.declare_provider(fc_pi.PI_MODELS),
    "compose CLI link": link_writer("compose CLI link"),
    "compose skill link": link_writer("compose skill link"),
    **{f"{r['name']} skill link": link_writer(f"{r['name']} skill link") for k in fc_harness.rows() for r in (fc_harness.HARNESSES[k],)},
    "bp link": link_writer("bp link"),
    "TEXT_MODEL lines": lambda checkout: fc_pi.write_text_model(fc_config.ENV_FILE),
}

PREVIEWS = {
    "pi openrouter-fast provider": lambda checkout: fc_pi.preview_provider(fc_pi.PI_MODELS),
    "compose CLI link": lambda checkout: next(f"would link {link} -> {target}" for n, link, target in fc_checks.owned_links(checkout) if n == "compose CLI link"),
    "compose skill link": lambda checkout: next(f"would link {link} -> {target}" for n, link, target in fc_checks.owned_links(checkout) if n == "compose skill link"),
    **{f"{r['name']} skill link": (lambda checkout, r=r: next(f"would link {link} -> {target}" for n, link, target in fc_checks.owned_links(checkout) if n == f"{r['name']} skill link"))
       for k in fc_harness.rows() for r in (fc_harness.HARNESSES[k],)},
    "bp link": lambda checkout: next(f"would link {link} -> {target}" for n, link, target in fc_checks.owned_links(checkout) if n == "bp link"),
    "TEXT_MODEL lines": lambda checkout: f"would append {', '.join(fc_pi.TEXT_MODEL_DEFAULTS)} to {fc_config.ENV_FILE}",
}

def run_step(row, checkout, yes, claude, terminal, dry=False):
    """(state, line): state is ok, claude, skipped, manual, done, or failed; the line never holds a key value or the
    step's name (the header above it shows both). A passing check is never run (ok). A claude row without claude waits
    (claude, no line). manual, key, and interactive-without-terminal rows are never run (manual or skipped, the line
    says what to do by hand), a designer row is skipped under yes; run and interactive rows shell out to install, write
    rows call their writer, then the check runs again: done rows have an empty line but a write row keeps its writer's
    line, and a failed run or interactive row ends with the install to run by hand after the last error line, or just
    that install; a failed write row keeps its writer's line, else the check's detail, else no line; every line shows
    ~/ wherever the home directory followed by / appears in it."""
    state, line = _run_step(row, checkout, yes, claude, terminal, dry)
    return state, fc_core.tilde(line)

def _run_step(row, checkout, yes, claude, terminal, dry=False):
    name, _, install, level, needs_claude, mode = row
    ok, detail = fc_steps.check(row, checkout)
    if ok:
        return "ok", ""
    if needs_claude and not claude:
        return "claude", ""
    if mode == "manual":
        return "manual", f"run by hand: {install}"
    if mode == "key":
        kind = next((k for k in ("openrouter", "typesafe", "linear", "figma") if k in name.lower()), "")
        return "skipped", fc_keys.skipped_line(kind, fc_config.WORKSPACE) or install
    if level == "designer" and yes:
        return "skipped", "designer extra, skipped"
    if mode == "interactive" and not terminal:
        return "skipped", f"run by hand: {install}"
    if dry:
        if mode == "write":
            return "would", PREVIEWS[name](checkout)
        if mode == "interactive":
            return "would", f"would run: {install} (it takes the terminal)"
        return "would", f"would run: {install}"
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
        return "done", said if mode == "write" else ""
    if mode == "run" and said:
        return "failed", f"{said.splitlines()[-1]}; by hand: {install}"
    if mode != "write":
        return "failed", f"by hand: {install}"
    return "failed", said or detail
