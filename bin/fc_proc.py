"""Implementer commands in process groups the run can stop: each child starts in its own session, so a stop (Ctrl-C) kills
the whole group, tool children included, and nothing new starts after it. Stdlib only, no fc_ module."""
import subprocess, threading

STOP = threading.Event()  # set once the run is stopped


class Stopped(Exception):
    """Raised instead of starting a command after the stop."""


HOOKS = {}  # name -> zero-argument callable stop() calls: herdr agents register their esc and pane close here
RUNNING = set()  # pids of the groups `run` is waiting on


def run(cmd, cwd=None, env=None, timeout=None):
    """Like subprocess.run(cmd, capture_output=True, text=True, stdin=DEVNULL), but in a session of its own and tracked in
    RUNNING while it runs. Returns a subprocess.CompletedProcess; raises Stopped after the stop, TimeoutExpired past `timeout`."""
    raise NotImplementedError("fc_proc.run")


def kill_group(pid):
    """SIGTERM to the process group `pid`, SIGKILL after 5 s if it is still alive; a group already gone is not an error."""
    raise NotImplementedError("fc_proc.kill_group")


def stop():
    """Set STOP, kill every group in RUNNING, call every hook in HOOKS."""
    raise NotImplementedError("fc_proc.stop")

