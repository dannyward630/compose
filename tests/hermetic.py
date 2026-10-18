"""Imported first by every test module: no test, and no CLI it runs, sees the real home.

On import the process gets a temp HOME and COMPOSE_CONFIG and loses the key variables, so paths the bin modules compute at
import land there; each test then runs with its own fresh temp HOME (see temp_home) and COMPOSE_CONFIG, and its environment is restored after.
A test that still changes the real ~/.compose files that hold keys or config (created, written, moved or deleted, from the test
process or any subprocess) fails, naming the files, never their content."""
import atexit, hashlib, os, pwd, shutil, tempfile, unittest
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


_made = []  # every directory tempfile.mkdtemp made in this process, removed when the test that made it ends (else at exit)
_mkdtemp = tempfile.mkdtemp


def mkdtemp(*a, **kw):
    d = _mkdtemp(*a, **kw)
    _made.append(d)
    return d


def remove_made(since=0):
    while len(_made) > since:
        shutil.rmtree(_made.pop(), ignore_errors=True)


_stubs = None  # one read-only file per distinct executable body a test made; every stub path is a symlink to its body's file
_chmod = os.chmod


def stub_store():
    global _stubs
    if _stubs is None:
        _stubs = Path(_mkdtemp(prefix="compose-stubs-")).resolve()
        atexit.register(shutil.rmtree, _stubs, ignore_errors=True)
    return _stubs


def chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
    """os.chmod, with every executable file a test makes shared by body. macOS malware-scans each new executable file on its
    first run (about 150 ms of XprotectService, synchronous), and the suite makes thousands of stub tools with a few dozen
    distinct bodies, so a file given an executable mode is moved into the store under its body's hash (or dropped for the
    twin already there) and its path becomes a symlink, which runs without a new scan. A linked stub given a non-executable
    mode becomes its own file again, and so does one written again through Path.write_text or write_bytes (still executable,
    so it is shared again under its new body). Store files are read-only, so any other way of writing through a link fails
    with PermissionError rather than changing every twin."""
    p = Path(path) if dir_fd is None and follow_symlinks and isinstance(path, (str, os.PathLike)) else None
    if p is not None and p.is_symlink() and str(p.resolve()).startswith(str(stub_store()) + "/"):
        if mode & 0o111:
            return
        body = p.read_bytes()
        p.unlink()
        p.write_bytes(body)
    elif p is not None and mode & 0o111 and p.is_file():
        shared = stub_store() / hashlib.sha256(p.read_bytes()).hexdigest()
        if shared.exists():
            p.unlink()
        else:
            try:
                os.replace(p, shared)
            except OSError:  # another file system: a copy, scanned once for everyone
                shutil.copy2(p, shared)
                p.unlink()
            _chmod(shared, 0o555)
        p.symlink_to(shared)
        return
    return _chmod(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)


def path_chmod(self, mode, *, follow_symlinks=True):
    """Path.chmod through chmod: on 3.9 it calls the os.chmod pathlib bound at import, which never sees the patch."""
    chmod(self, mode, follow_symlinks=follow_symlinks)


def shared(p):
    return _stubs is not None and p.is_symlink() and str(p.resolve()).startswith(str(_stubs) + "/")


def writing_anew(write):
    """Path.write_text or write_bytes: a linked stub written again is its own file again, with the executable mode it had."""
    def wrapped(self, *a, **kw):
        was_shared = shared(self)
        if was_shared:
            self.unlink()
        out = write(self, *a, **kw)
        if was_shared:
            chmod(self, 0o755)
        return out
    return wrapped


if tempfile.mkdtemp is not mkdtemp:
    tempfile.mkdtemp = mkdtemp
    os.chmod = chmod
    Path.chmod = path_chmod
    Path.write_text = writing_anew(Path.write_text)
    Path.write_bytes = writing_anew(Path.write_bytes)
    atexit.register(remove_made)


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
    made = len(_made)
    env = mock.patch.dict(os.environ, temp_home())
    env.start()
    try:
        self.addCleanup(untouched, snapshot())  # the first cleanup added runs last, after the test's own
        return _run(self, result)
    finally:
        env.stop()
        remove_made(made)  # the test's temp home and every directory it or its setUp made


run.hermetic = True
if not getattr(unittest.TestCase.run, "hermetic", False):
    for k in KEYS:
        os.environ.pop(k, None)
    os.environ.update(temp_home())
    unittest.TestCase.run = run
