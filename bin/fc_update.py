"""`compose update`: pull the CLI's own checkout --ff-only, relink what compose owns, run doctor."""
import sys
from pathlib import Path
import fc_core, fc_init, fc_links


def cmd_update(a):
    """Exits 1 on local changes or a failed pull, else with doctor's code."""
    checkout = Path(__file__).resolve().parents[1]
    if fc_core.sh(["git", "status", "--porcelain"], checkout, check=False).stdout.strip():
        sys.exit(f"{checkout} has local changes: commit or stash them, then run compose update again")
    p = fc_core.sh(["git", "pull", "--ff-only"], checkout, check=False)
    if p.returncode:
        sys.exit(" ".join((p.stdout + p.stderr).split()))
    for line in fc_links.relink_owned(checkout):
        print(line)
    sys.exit(fc_init.cmd_doctor(a))
