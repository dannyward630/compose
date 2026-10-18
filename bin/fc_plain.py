"""The plain setup path: `compose setup --yes` and runs without a terminal. Never prompts."""
import shutil
import fc_steps, fc_steprun, fc_finish


def run_plain(checkout, yes):
    """Walk every step, skipping the designer rows, print each step once and setup's ending; return finish's code."""
    claude = shutil.which("claude") is not None
    results = []
    for row in fc_steps.STEPS:
        if row[3] == "designer":
            state, line = "skipped", "designer extra, skipped"
        else:
            state, line = fc_steprun.run_step(row, checkout, yes, claude, terminal=False)
        print(f"{state} {row[0]}")
        for part in line.splitlines():
            if part:
                print(f"  {part}")
        results.append((row[0], state))
    lines, code = fc_finish.finish(results, yes)
    for line in lines:
        print(line)
    return code
