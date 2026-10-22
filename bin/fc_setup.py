"""`compose setup [--yes]`: one prompt flow on a terminal, every default otherwise."""
import shutil, sys
from pathlib import Path
import fc_checks, fc_config, fc_finish, fc_keys, fc_perms, fc_prompt, fc_steprun, fc_steps


MODES = ("Quick start (every default, designer extras off)", "Custom (choose each step)")


def walk_steps(checkout, custom, yes, dry=False):
    claude = shutil.which("claude") is not None
    other = fc_steps.other_harness(checkout)
    results, designer = [], False
    for row in fc_steps.STEPS:
        name, _, install, level, _, mode = row
        if mode in ("key", "perms"):  # asked for after the steps: fc_keys.ask_keys, fc_perms.offer
            continue
        lines = []
        if custom and fc_steps.check(row, checkout)[0]:
            state = "ok"
        elif custom and not fc_prompt.confirm(f"Set up {name}?", level != "designer"):
            state = "skipped"
            if fc_steps.required(row, other):
                lines = [f"compose stops working without it; by hand: {install}"]
        elif not custom and level == "designer":
            state, lines = "skipped", ["designer extra, skipped"]
        else:
            designer = designer or level == "designer"
            if mode == "interactive" and not yes:
                state, detail = fc_steprun.run_step(row, checkout, yes, claude, True, dry)
            else:
                with fc_prompt.spin(name):
                    state, detail = fc_steprun.run_step(row, checkout, yes, claude, not yes, dry)
            lines = detail.splitlines()
        results.append((name, state))
        if state == "would":
            fc_prompt.step(name, detail)
        else:
            fc_prompt.step(name, "waiting on Claude Code" if state == "claude" else state, lines)
    return results, designer


def run_setup(checkout, yes, dry=False):
    fc_prompt.intro("compose setup" + (" (dry run)" if dry else ""))
    custom = False
    if not yes:
        custom = fc_prompt.select("How do you want to set up?", MODES) == 1
    results, designer = walk_steps(checkout, custom, yes, dry)
    kinds, rules = [], fc_perms.offer(yes, dry)
    if not yes:
        kinds = fc_keys.ask_keys(fc_config.settings(fc_config.read_config())[0], fc_steps.FRAMELINK_ENV, designer, dry)
        with fc_prompt.spin("checking your model"):
            lines, code = fc_finish.finish(results, yes, dry)
    else:
        lines, code = fc_finish.finish(results, yes, dry)
    lines = rules + lines
    if dry:
        changes = sum(state == "would" for _, state in results) + len(kinds) + sum(line.startswith("would ") for line in lines)
        fc_prompt.note("Summary", lines)
        fc_prompt.outro(f"dry run: nothing changed; {changes} changes listed above")
    else:
        fc_prompt.note("Summary", lines[:-1])
        fc_prompt.outro(lines[-1])
    return code


def cmd_setup(a):
    """a.yes: take every default and never prompt. Stops on a fast-coding leftover; exits with setup's code."""
    checkout = Path(__file__).resolve().parents[1]
    if (Path.home() / ".fast-coding").exists() or any(
            "fast-coding" in str(Path(link).resolve()) for _, link, _ in fc_checks.owned_links(checkout)):
        print(f"a fast-coding install is still on this machine; run {checkout}/bin/migrate-to-compose.sh to move it to compose first")
        sys.exit(1)
    sys.exit(run_setup(checkout, a.yes or not (sys.stdin.isatty() and sys.stdout.isatty()), a.dry_run))
