import hermetic  # first: no test sees the real home
import fcntl, os, pty, re, select, subprocess, sys, tempfile, termios, time, unittest
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


# Step lines and HOME paths every real run shows and writes with the default fakes.
STEP_LINES = ["◇  gh: ok", "◇  compose CLI link: done", "◇  ~/.local/bin on PATH: manual", "◇  Chromium: failed", "◇  framelink-figma: skipped"]
PATHS = {".local/bin/compose", ".local/bin/bp", ".claude/skills/compose", ".pi/agent/models.json", ".compose/.env", ".compose/config.json",
         ".config/herdr/config.toml"}
SKIP = [("(Enter skips): ", ""), ("Continue without it? (y/N) ", "y")]


def assert_run(test, r, code, last):
    test.assertEqual((r.code, [line for line in r.lines if line][-1]), (code, last))
    test.assertEqual([line for line in r.lines if line in STEP_LINES], STEP_LINES)
    test.assertLessEqual(PATHS, tree(r.home).keys())


class Prompted(SetupE2E, unittest.TestCase):
    """`compose setup` on a terminal, answered in the pty (task 006)."""

    def test_quick_start_with_every_key_skipped(self):
        r = self.run_setup(answers=[("number [1]: ", "1"), *SKIP * 3])
        assert_run(self, r, 1, "└  setup is not finished: missing OpenRouter, TypeSafe, Linear")
        at = [next(i for i, line in enumerate(r.lines) if part in line) for part in
              ("┌  compose setup", "◆  How do you want to set up?", STEP_LINES[0], "OpenRouter key (Enter skips)", "◇  Summary")]
        self.assertEqual(at, sorted(at))
        self.assertNotIn("(Y/n)", r.text)
        self.assertIn("git config --global rerere.enabled true", r.calls)


class Defaults(SetupE2E, unittest.TestCase):
    """`compose setup --yes`, and setup with no terminal (task 006)."""

    def assert_no_question(self, *args, **kw):
        r = self.run_setup(*args, **kw)
        assert_run(self, r, 0, "└  run compose setup in a terminal to finish")
        self.assertNotIn("◆", r.text)

    def test_yes_on_a_terminal_finishes_with_no_input(self):
        self.assert_no_question("--yes")

    def test_no_terminal_is_the_same_as_yes(self):
        self.assert_no_question(tty=False)


class DryRun(SetupE2E, unittest.TestCase):
    """`compose setup --dry-run`: the whole HOME tree unchanged, no fake installer called (task 017)."""

    def test_dry_run_answered_changes_nothing_and_installs_nothing(self):
        before = tree(os.environ["HOME"])
        r = self.run_setup("--dry-run", answers=[("number [1]: ", "1"), ("(Enter skips): ", "sk-or-test-1"), *SKIP * 2])
        self.assertEqual(tree(r.home), before)
        self.assertLessEqual(set(r.calls), {"gh auth status", "gh stack --version", "herdr --version", "treehouse --version",
                                            "herdr integration status", "git config --global --get rerere.enabled"})
        changes = sum(bool(re.match(r"(◇  [^:]+: |│  )would ", line)) for line in r.lines)
        self.assertEqual((r.code, [line for line in r.lines if line][-1], "sk-or-test-1" in r.text),
                         (1, f"└  dry run: nothing changed; {changes} changes listed above", False))


class StepDetail(SetupE2E, unittest.TestCase):
    """A step's │ lines never repeat the name or only the state of the ◇ header above them (task 023)."""

    def test_detail_lines_never_repeat_their_header(self):
        r = self.run_setup(answers=[("number [1]: ", "1"), *SKIP * 3])
        under, head = {}, None
        for line in r.lines:
            if not line.startswith("│"):
                head = (m := re.fullmatch(r"◇  (.+): (\S+)", line)) and m.groups()
            elif head and line.startswith("│  "):
                under.setdefault(head, []).append(line[3:])
        self.assertEqual([(h, l) for h, ls in under.items() for l in ls if l.startswith(f"{h[0]}: ") or l == h[1]], [])
        self.assertEqual((under.get(("Chromium", "failed"), [""])[0], under.get(("~/.local/bin on PATH", "manual"), [""])[0]),
                         ("by hand: npx playwright install chromium", 'run by hand: put `export PATH="$HOME/.local/bin:$PATH"` in your shell profile'))
