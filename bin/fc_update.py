"""`compose update`: pull the CLI's own checkout --ff-only, relink what compose owns, run doctor."""
import sys
from pathlib import Path
import fc_core, fc_init, fc_links


def cmd_update(a):
    """Exits 1 on local changes or a failed pull, else with doctor's code."""
    raise NotImplementedError("not implemented: task 027")
