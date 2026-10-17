"""The plain setup path: `compose setup --yes` and runs without a terminal. Never prompts."""
import shutil
from pathlib import Path
import fc_steps, fc_herdrconf, fc_links, fc_steprun, fc_finish


def run_plain(checkout, yes):
    """Walk every step, apply the herdr config, print the PATH line and setup's ending; return finish's code."""
    raise NotImplementedError("not implemented: task 020")
