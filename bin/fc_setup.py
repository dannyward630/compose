"""`compose setup [--yes]`: the guided Textual setup on a terminal, the plain path otherwise."""
import os, shutil, sys
from pathlib import Path
import fc_checks, fc_plain


MODES = ()


def walk_steps(checkout, custom, yes, dry=False):
    import fc_prompt, fc_steps, fc_steprun
    claude = shutil.which("claude") is not None
    results, designer = [], False
    for row in fc_steps.STEPS:
        name, _, install, level, _, mode = row
        if mode == "key":
            continue
        lines = []
        if custom and fc_steps.check(row, checkout)[0]:
            state = "ok"
        elif custom and not fc_prompt.confirm(f"Set up {name}?", level != "designer"):
            state = "skipped"
            if level == "required":
                lines = [f"compose stops working without it; by hand: {install}"]
        elif not custom and level == "designer":
            state, lines = "skipped", ["designer extra, skipped"]
        else:
            designer = designer or level == "designer"
            if mode == "interactive" and not yes:
                state, detail = fc_steprun.run_step(row, checkout, yes, claude, True)
            else:
                with fc_prompt.spin(name):
                    state, detail = fc_steprun.run_step(row, checkout, yes, claude, not yes)
            lines = detail.splitlines()
        results.append((name, state))
        fc_prompt.step(name, "waiting on Claude Code" if state == "claude" else state, lines)
    return results, designer


def run_setup(checkout, yes, dry=False):
    raise NotImplementedError("run_setup")


def cmd_setup(a):
    """a.yes: take every default and never prompt. Stops on a fast-coding leftover; exits with setup's code."""
    checkout = Path(__file__).resolve().parents[1]
    if (Path.home() / ".fast-coding").exists() or any(
            "fast-coding" in str(Path(link).resolve()) for _, link, _ in fc_checks.owned_links(checkout)):
        print(f"a fast-coding install is still on this machine; run {checkout}/bin/migrate-to-compose.sh to move it to compose first")
        sys.exit(1)
    guided = sys.stdin.isatty() and sys.stdout.isatty() and not a.yes
    if guided and shutil.which("uv") is None:
        print("the guided setup needs uv; running the plain setup instead")
        guided = False
    if not guided:
        sys.exit(fc_plain.run_plain(checkout, a.yes))
    os.chdir(checkout / "setup")
    os.execvp("uv", ["uv", "run", "--project", str(checkout / "setup"), "python", "-m", "compose_setup"])
