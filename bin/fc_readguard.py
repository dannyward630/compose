"""The read guard: decides one implementer tool call against the task's allowed files. pi (pi_readguard.ts), OpenCode
(opencode_readguard.js) and Claude (a PreToolUse hook) run it as a script, `python3 -I fc_readguard.py <guard file>`, with the
call on stdin. Stdlib only, no fc_ module."""
import json, sys
from pathlib import Path

PI_EXT = Path(__file__).resolve().parent / "pi_readguard.ts"
OC_PLUGIN = Path(__file__).resolve().parent / "opencode_readguard.js"


def guard_file(wt):
    """`<wt parent>/<wt name>.guard.json`, beside the task clone (never inside it, so `git add -A` never commits it)."""
    raise NotImplementedError("fc_readguard.guard_file")


def pack_paths(pack):
    """The paths a trail pack cites on its `path:L<a>-L<b>` lines, in order, each once."""
    raise NotImplementedError("fc_readguard.pack_paths")


def write_guard(wt, files, pack):
    """Write {"root", "allow", "log"} to guard_file(wt) and return that path. `allow` holds the absolute paths of `files` and of
    pack_paths(pack); `log` is `<wt parent>/<wt name>.refused`."""
    raise NotImplementedError("fc_readguard.write_guard")


def command(guard):
    """The shell line that runs this file as the guard for `guard`: `python3 -I <this file> <guard>`."""
    raise NotImplementedError("fc_readguard.command")


def refusal(tool, args, guard):
    """None when the call is allowed, else the reply text for the model. `guard` is the loaded guard dict."""
    raise NotImplementedError("fc_readguard.refusal")


def refused(wt):
    """How many calls the guard of the clone `wt` has refused: the lines in its log, 0 when there is none."""
    raise NotImplementedError("fc_readguard.refused")


def cli():
    """Read one event on stdin (a Claude PreToolUse event or {"tool", "args"}), log a refusal, print the reply."""
    raise NotImplementedError("fc_readguard.cli")


if __name__ == "__main__":
    cli()
