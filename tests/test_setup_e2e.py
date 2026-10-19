import hermetic  # first: no test sees the real home
import fcntl, os, pty, select, subprocess, sys, tempfile, termios, time, unittest
from pathlib import Path
from types import SimpleNamespace
os.environ["HERDR_ENV"] = ""

ROOT = Path(__file__).resolve().parents[1]
# Every tool the step table checks or installs with, faked: each call is one line "<tool> <args>" in the calls file.
TOOLS = ("brew", "git", "npx", "npm", "gh", "claude", "herdr", "pi", "uv", "trail", "treehouse", "curl")
RECORD = '#!/bin/sh\nprintf \'%s\\n\' "$(basename "$0") $*" >> "$SETUP_E2E_CALLS"\n'


def screen(text):
    """The lines a terminal shows for text: CRLF as one break, a spinner's \\r-overwritten frames and \\x1b[2K dropped."""
    return [line.split("\r")[-1].replace("\x1b[2K", "") for line in text.replace("\r\n", "\n").split("\n")]


def tree(root):
    """Every path under root: a file's mode and bytes, a directory's mode, a link's target; equal before and after means unchanged."""
    root, out = Path(root), {}
    for dirpath, dirs, files in os.walk(root):
        for name in dirs + files:
            p = Path(dirpath, name)
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            elif p.is_dir():
                out[rel] = ("dir", p.stat().st_mode)
            else:
                out[rel] = ("file", p.stat().st_mode, p.read_bytes())
    return out


class SetupE2E:
    """`bin/compose setup` run as a user runs it, under the test's scratch HOME (hermetic's temp home) with fake tools on PATH."""

    def run_setup(self, *args, answers=(), tools=None, tty=True, path=(), timeout=60, **env):
        """Run `bin/compose setup <args>` and return SimpleNamespace(code, text, lines, calls, home).
        answers: (prompt, reply) pairs in order; reply and a newline are typed once prompt shows after the last answered one.
        tools: name -> sh script body, default RECORD for each of TOOLS; None leaves a tool off PATH.
        tty: the child gets a pty as stdin, stdout, stderr, and controlling terminal (getpass reads /dev/tty); else stdin is
        /dev/null and stdout a pipe, in a new session with no terminal. path: directories put after the fake tools on PATH.
        Fails with the transcript when the run outlasts timeout or a prompt never shows."""
        home = Path(os.environ["HOME"])
        tmp = Path(tempfile.mkdtemp(prefix="setup-e2e-"))  # outside HOME, so a fake tool's call changes nothing under it
        fakebin, calls = tmp / "bin", tmp / "calls"
        fakebin.mkdir()
        for name, body in (tools if tools is not None else {t: RECORD for t in TOOLS}).items():
            if body is not None:
                (fakebin / name).write_text(body)
                (fakebin / name).chmod(0o755)
        base = {k: v for k, v in os.environ.items() if k != "CI" and not k.startswith(("HERDR_", "ANTHROPIC_", "COMPOSE_"))}
        base |= {"HOME": str(home), "COMPOSE_CONFIG": os.environ["COMPOSE_CONFIG"], "PATH": ":".join([str(fakebin), *map(str, path), "/usr/bin:/bin"]),
                 "NO_COLOR": "1", "TERM": "xterm-256color", "SETUP_E2E_CALLS": str(calls)}
        argv = [sys.executable, str(ROOT / "bin" / "compose"), "setup", *args]
        if tty:
            master, slave = pty.openpty()
            p = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=home, env=base | env, start_new_session=True,
                                 preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
            os.close(slave)
        else:
            master = None
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=home,
                                 env=base | env, start_new_session=True)
        out, at, left, deadline = b"", 0, list(answers), time.time() + timeout
        try:
            while True:
                if time.time() > deadline:
                    p.kill()
                    self.fail(f"setup ran past {timeout}s; screen so far:\n" + "\n".join(screen(out.decode(errors="replace"))))
                fd = master if tty else p.stdout.fileno()
                if select.select([fd], [], [], 0.2)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:  # EIO once the child closed the pty (macOS)
                        chunk = b""
                    if not chunk:
                        break
                    out += chunk
                while left and tty:
                    seen = out.find(left[0][0].encode(), at)
                    if seen < 0:
                        break
                    at = seen + len(left[0][0].encode())
                    os.write(master, (left.pop(0)[1] + "\n").encode())
            code = p.wait(timeout=max(1, deadline - time.time()))
        finally:
            if master is not None:
                os.close(master)
            if p.stdout:
                p.stdout.close()
        text = out.decode(errors="replace")
        if left:
            self.fail(f"prompt never showed: {left[0][0]!r}; screen:\n" + "\n".join(screen(text)))
        return SimpleNamespace(code=code, text=text, lines=screen(text), home=home,
                               calls=calls.read_text().splitlines() if calls.exists() else [])


class Prompted(SetupE2E, unittest.TestCase):
    """`compose setup` on a terminal, answered in the pty (task 006)."""


class Defaults(SetupE2E, unittest.TestCase):
    """`compose setup --yes`, and setup with no terminal (task 006)."""


class DryRun(SetupE2E, unittest.TestCase):
    """`compose setup --dry-run`: the whole HOME tree unchanged, no fake installer called (task 017)."""
