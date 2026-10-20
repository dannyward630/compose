"""`compose update`: pull the CLI's own checkout --ff-only, relink what compose owns, run doctor."""
import shlex, sys
from pathlib import Path
import fc_core, fc_init, fc_links


def diverged(checkout):
    """The way out when the checkout's branch has commits its upstream lacks, else None.
    `git cherry` marks each one `-` when its patch is already upstream under another hash, `+` when it is only here."""
    git = lambda *args: fc_core.sh(["git", *args], checkout, check=False)
    branch, upstream = (git("rev-parse", "--abbrev-ref", ref).stdout.strip() for ref in ("HEAD", "@{u}"))
    cherry = git("cherry", "-v", upstream, "HEAD")
    if not upstream or cherry.returncode or not cherry.stdout.strip():
        return None
    lines = []
    for line in cherry.stdout.splitlines():
        mark, sha, subject = line.split(" ", 2)
        where = f"already on {upstream}" if mark == "-" else "only here"
        lines.append(f"  {mark} {sha[:12]} {subject} ({where})")
    n = len(lines)
    if all(l.lstrip().startswith("-") for l in lines):
        fix = f"git -C {shlex.quote(str(checkout))} reset --hard {upstream}"
        why = "Every change is already upstream, so drop the local copies:"
    else:
        fix = f"git -C {shlex.quote(str(checkout))} rebase {upstream}"
        why = "Replay them on top of it (changes already upstream are skipped):"
    return "\n".join([f"{checkout}: {branch} has {n} commit{'s' if n > 1 else ''} that {upstream} does not, so it cannot fast-forward:",
                      *lines, why, f"  {fix}", "Then run compose update again."])


def cmd_update(a):
    """Exits 1 on local changes or a failed pull, else with doctor's code."""
    checkout = Path(__file__).resolve().parents[1]
    if fc_core.sh(["git", "status", "--porcelain"], checkout, check=False).stdout.strip():
        sys.exit(f"{checkout} has local changes: commit or stash them, then run compose update again")
    p = fc_core.sh(["git", "pull", "--ff-only"], checkout, check=False)
    if p.returncode:
        sys.exit(diverged(checkout) or " ".join((p.stdout + p.stderr).split()))
    for line in fc_links.relink_owned(checkout):
        print(line)
    sys.exit(fc_init.cmd_doctor(a))
