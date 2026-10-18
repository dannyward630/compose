"""Implementer commands in process groups the run can stop: each child starts in its own session, so a stop (Ctrl-C) kills
the whole group, tool children included, and nothing new starts after it. Stdlib only, no fc_ module."""
import os, signal, subprocess, threading, time

STOP = threading.Event()  # set once the run is stopped


class Stopped(Exception):
    """Raised instead of starting a command after the stop."""


HOOKS = {}  # name -> zero-argument callable stop() calls: herdr agents register their esc and pane close here
RUNNING = set()  # pids of the groups `run` is waiting on


def run(cmd, cwd=None, env=None, timeout=None):
    """Like subprocess.run(cmd, capture_output=True, text=True, stdin=DEVNULL), but in a session of its own and tracked in
    RUNNING while it runs. Returns a subprocess.CompletedProcess; raises Stopped after the stop, TimeoutExpired past `timeout`."""
    if STOP.is_set():
        raise Stopped
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    RUNNING.add(p.pid)
    try:
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_group(p.pid)
            p.communicate()
            raise
        if STOP.is_set():
            raise Stopped
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)
    finally:
        RUNNING.discard(p.pid)


def kill_group(pid):
    """SIGTERM to the process group `pid`, SIGKILL after 5 s if it is still alive; a group already gone is not an error."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):  # gone, or (macOS) every member is a zombie: nothing alive left
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def stop():
    """Set STOP, kill every group in RUNNING, call every hook in HOOKS."""
    STOP.set()
    for pid in list(RUNNING):
        kill_group(pid)
    for hook in list(HOOKS.values()):
        hook()
