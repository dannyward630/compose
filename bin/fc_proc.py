"""Implementer commands in process groups the run can stop: each child starts in its own session, so a stop (Ctrl-C) kills
the whole group, tool children included, and nothing new starts after it. Stdlib only, no fc_ module."""
import contextlib, fcntl, os, signal, subprocess, threading, time

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
    """Set STOP, kill every group in RUNNING, call every hook in HOOKS. The hooks are taken first: a group killed lets the
    thread that waited on it go on, and that thread may take its hook out on its way out, before its own cleanup ends."""
    STOP.set()
    hooks = list(HOOKS.values())
    for pid in list(RUNNING):
        kill_group(pid)
    for hook in hooks:
        hook()


def on_termination(cleanup):
    """Install the SIGTERM and SIGHUP handler (a closed pane, a `timed` limit above this process, a kill): left to die bare the
    CLI skips atexit, so every scratch config it made stays in the temp folder and a command `timed` started runs on without
    it. The handler runs `cleanup`, then stop(), then exits 128 + the signal: no SystemExit, which a run's worker threads would
    hold open until their tasks end."""
    def terminated(sig, _frame):
        cleanup()
        stop()
        os._exit(128 + sig)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, terminated)


SLOTS = 2  # `timed` commands that run at once on this machine; COMPOSE_TEST_SLOTS overrides
SLOT_SAY_AFTER = 1.0  # seconds a wait for a slot stays silent


@contextlib.contextmanager
def slot(say=None):
    """One of SLOTS machine-wide slots (lock files under ~/.compose/test-slots), held while a timed command runs: five teammates
    each running a suite at once leave the machine doing little else. Yields the slot's number, which goes in the command's env
    as COMPOSE_TEST_SLOT so a compose it runs takes none: a suite under a slot runs compose itself, and with one slot its timed
    commands would wait on their parent for ever; a process already under one yields that. `say` gets one line once the wait
    passes SLOT_SAY_AFTER. The lock goes with the process, so a killed command frees its slot."""
    held = os.environ.get("COMPOSE_TEST_SLOT")
    if held:
        yield held
        return
    n = max(1, int(os.environ.get("COMPOSE_TEST_SLOTS") or SLOTS))
    d = os.path.join(os.path.expanduser("~"), ".compose", "test-slots")
    os.makedirs(d, exist_ok=True)
    fds = [os.open(os.path.join(d, str(i)), os.O_RDWR | os.O_CREAT, 0o644) for i in range(n)]
    t0, said = time.monotonic(), False
    try:
        while True:
            for i, fd in enumerate(fds):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    continue
                yield str(i)
                return
            if say and not said and time.monotonic() - t0 >= SLOT_SAY_AFTER:
                say(f"waiting for a test slot: {n} timed command{'s' if n > 1 else ''} already run on this machine")
                said = True
            time.sleep(0.2)
    finally:
        for fd in fds:
            os.close(fd)  # closing releases the lock
