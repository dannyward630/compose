"""Imported first by every test module: no test, and no CLI it runs, sees the real home.

On import the process gets a temp HOME and COMPOSE_CONFIG and loses the key variables, so paths the bin modules compute at
import land there; each test then runs with its own fresh temp HOME (see temp_home) and COMPOSE_CONFIG, and its environment is restored after.
A test that still changes the real ~/.compose files that hold keys or config (created, written, moved or deleted, from the test
process or any subprocess) fails, naming the files, never their content."""
import os, pwd, tempfile, unittest
from pathlib import Path
from unittest import mock

REAL = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".compose"  # the account's home, whatever HOME says
GUARDED = ("config.json", "auth.json", ".env", "openrouter.key")
KEYS = ("OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "OPENCODE_CONFIG_CONTENT", "TYPESAFE_API_KEY")


INSTALLED = {  # what compose's required tools keep in a home, faked so `compose init` goes ahead without the user's machine
    ".local/share/gh/extensions/gh-stack/gh-stack": "#!/bin/sh\necho 'gh stack (fake)'\n",
    ".claude/skills/herdr/SKILL.md": "# herdr (fake)\n",
    ".claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md": "# i-have-adhd (fake)\n",
}


def temp_home():
    """{HOME, COMPOSE_CONFIG} for a new temp home that holds only INSTALLED: no keys, no config, no links."""
    home = Path(tempfile.mkdtemp(prefix="compose-home-")).resolve()
    for rel, text in INSTALLED.items():
        f = home / rel
        f.parent.mkdir(parents=True)
        f.write_text(text)
        f.chmod(0o755)
    return {"HOME": str(home), "COMPOSE_CONFIG": str(home / ".compose" / "config.json")}


def snapshot():
    """Each guarded file's (inode, size, mtime), or None when absent: stat only, nothing is opened."""
    out = {}
    for name in GUARDED:
        try:
            s = (REAL / name).stat()
            out[name] = (s.st_ino, s.st_size, s.st_mtime_ns)
        except FileNotFoundError:
            out[name] = None
    return out


def untouched(before):
    changed = [n for n, s in snapshot().items() if s != before[n]]
    if changed:
        raise AssertionError(f"this test changed the real {REAL}: {', '.join(changed)}")


_run = unittest.TestCase.run


def run(self, result=None):
    env = mock.patch.dict(os.environ, temp_home())
    env.start()
    try:
        self.addCleanup(untouched, snapshot())  # the first cleanup added runs last, after the test's own
        return _run(self, result)
    finally:
        env.stop()


run.hermetic = True
if not getattr(unittest.TestCase.run, "hermetic", False):
    for k in KEYS:
        os.environ.pop(k, None)
    os.environ.update(temp_home())
    unittest.TestCase.run = run
