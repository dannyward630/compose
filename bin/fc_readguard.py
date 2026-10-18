"""The read guard: decides one implementer tool call against the task's allowed files. pi (pi_readguard.ts), OpenCode
(opencode_readguard.js) and Claude (a PreToolUse hook) run it as a script, `python3 -I fc_readguard.py <guard file>`, with the
call on stdin. Stdlib only, no fc_ module."""
import json, os, re, shlex, sys
from pathlib import Path

PI_EXT = Path(__file__).resolve().parent / "pi_readguard.ts"
OC_PLUGIN = Path(__file__).resolve().parent / "opencode_readguard.js"


def guard_file(wt):
    """`<wt parent>/<wt name>.guard.json`, beside the task clone (never inside it, so `git add -A` never commits it)."""
    wt = Path(wt)
    return wt.parent / (wt.name + ".guard.json")


def pack_paths(pack):
    """The paths a trail pack cites on its `path:L<a>-L<b>` lines, in order, each once."""
    out = []
    for p in re.findall(r"(\S+?):L\d+-L\d+", pack):
        if p not in out:
            out.append(p)
    return out


def write_guard(wt, files, pack):
    """Write {"root", "allow", "log"} to guard_file(wt) and return that path. `allow` holds the absolute paths of `files` and of
    pack_paths(pack); `log` is `<wt parent>/<wt name>.refused`."""
    root = os.path.realpath(wt)
    allow = sorted({os.path.realpath(os.path.join(root, f)) for f in list(files) + pack_paths(pack)})
    path = guard_file(wt)
    path.write_text(json.dumps({"root": root, "allow": allow, "log": str(path.parent / (Path(wt).name + ".refused"))}, indent=2))
    return path


def command(guard):
    """The shell line that runs this file as the guard for `guard`: `python3 -I <this file> <guard>`."""
    return "python3 -I {} {}".format(shlex.quote(os.path.realpath(__file__)), shlex.quote(str(guard)))


def refusal(tool, args, guard):
    """None when the call is allowed, else the reply text for the model. `guard` is the loaded guard dict."""
    why = ("Blocked: you may read only the files the context pack names (or a directory directly holding one), and in bash only "
           "`trail ask \"<question>\"` or `trail callers <symbol>`. For anything else, run trail ask \"<question>\".")
    tool = (tool or "").lower()
    root, allow = guard["root"], set(guard["allow"])
    if tool == "bash":
        cmd = (args.get("command") or "").strip()
        if (cmd in ("trail ask", "trail callers") or cmd.startswith(("trail ask ", "trail callers "))) \
                and not any(x in cmd for x in (";", "&", "|", "`", "$(", "<", ">", "\n")):
            return None
        return why
    p = args.get("file_path") or args.get("path")
    if tool == "read":
        if p and os.path.realpath(os.path.join(root, p)) in allow:
            return None
        return why
    if tool in ("grep", "glob", "find", "ls", "list"):
        r = os.path.realpath(os.path.join(root, p)) if p else root  # no path means the root
        if r in allow or any(os.path.dirname(a) == r for a in allow):
            return None
        return why
    return None


def refused(wt):
    """How many calls the guard of the clone `wt` has refused: the lines in its log, 0 when there is none."""
    log = Path(json.loads(guard_file(wt).read_text())["log"])
    return len(log.read_text().splitlines()) if log.exists() else 0


def cli():
    """Read one event on stdin (a Claude PreToolUse event or {"tool", "args"}), log a refusal, print the reply."""
    try:
        guard = json.loads(Path(sys.argv[1]).read_text())
        ev = json.load(sys.stdin)
        claude = "tool_name" in ev
        tool = ev.get("tool_name") if claude else ev.get("tool")
        if not tool:
            raise ValueError("event names no tool")
        args = (ev.get("tool_input") if claude else ev.get("args")) or {}
        why = refusal(tool, args, guard)
        if not why:
            return
        with open(guard["log"], "a") as f:
            f.write(json.dumps({"tool": tool, "args": args}) + "\n")
        if claude:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": why}}))
        else:
            print(why)
    except Exception as e:
        print("fc_readguard: {}".format(e), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    cli()
