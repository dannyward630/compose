"""The plain setup path: `compose setup --yes` and runs without a terminal. Never prompts."""
import shutil
from pathlib import Path
import fc_steps, fc_herdrconf, fc_links, fc_steprun, fc_finish


def run_plain(checkout, yes):
    """Walk every step, apply the herdr config, print the PATH line and setup's ending; return finish's code."""
    claude = shutil.which("claude") is not None
    results = []
    for row in fc_steps.STEPS:
        state, line = fc_steprun.run_step(row, checkout, yes, claude, terminal=False)
        print(f"{state} {line}")
        results.append((row[0], state))
    _, lines = fc_herdrconf.apply_herdr_config(Path.home() / ".config" / "herdr" / "config.toml", checkout / "setup" / "herdr.toml")
    for line in lines:
        print(line)
    path = fc_links.path_line()
    if path:
        print(path)
    lines, code = fc_finish.finish(results, yes)
    for line in lines:
        print(line)
    return code
