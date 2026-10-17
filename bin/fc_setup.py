"""`compose setup [--yes]`: the guided Textual setup on a terminal, the plain path otherwise."""
import os, shutil, sys
from pathlib import Path
import fc_checks, fc_plain


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
