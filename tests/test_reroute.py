import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
os.environ.update(COMPOSE_NO_TREEHOUSE="1", HERDR_ENV="")

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_reroute  # noqa: E402  (nothing imports it into `fc` yet; compose.py put bin/ on sys.path)

FILES = ["src/keep.py", "src/new.py", "src/gone.py", "src/a.py", "src/b.py"]


class Signals(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        self.write({"src/a.py": "1\n2\n3\n", "src/b.py": "b\n", "src/keep.py": "k\n", "src/gone.py": "p\nq\n"})
        self.commit("base")
        self.git("checkout", "-qb", "task")
        self.write({"src/a.py": "1\n3\nA\nB\n", "src/new.py": "x\ny\nz\n", "docs/outside.txt": "o\n", "assets/logo.png": b"\x00\x01"})
        (self.repo / "src/gone.py").unlink()
        self.commit("task")
        self.git("checkout", "-q", "main")
        self.write({"src/b.py": "b\nmore\n", "other.txt": "1\n2\n3\n4\n5\n"})
        self.commit("base moves on")

    def git(self, *a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-qm", msg)

    def write(self, files):
        for name, body in files.items():
            p = self.repo / name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body if isinstance(body, bytes) else body.encode())

    def signals(self, files, branch="task"):
        return fc_reroute.diff_signals(self.repo, {"files": files}, "main", branch)

    def test_changed_lines_outside_and_untouched_come_from_the_three_dot_diff(self):
        got = self.signals(FILES)
        self.assertEqual(set(got), {"changed", "lines", "outside", "untouched"})
        self.assertEqual(got["changed"], [{"path": "assets/logo.png", "added": 0, "deleted": 0}, {"path": "docs/outside.txt", "added": 1, "deleted": 0},
                                          {"path": "src/a.py", "added": 2, "deleted": 1}, {"path": "src/gone.py", "added": 0, "deleted": 2},
                                          {"path": "src/new.py", "added": 3, "deleted": 0}])
        self.assertEqual(got["lines"], 9)
        self.assertEqual(got["outside"], ["assets/logo.png", "docs/outside.txt"])
        self.assertEqual(got["untouched"], ["src/keep.py", "src/b.py"])

    def test_without_files_every_changed_path_is_outside(self):
        got = self.signals([])
        self.assertEqual(got["outside"], [c["path"] for c in got["changed"]])
        self.assertEqual((len(got["outside"]), got["untouched"]), (5, []))

    def test_a_branch_with_no_change_has_no_signals(self):
        self.assertEqual(self.signals(FILES, "main"), {"changed": [], "lines": 0, "outside": [], "untouched": FILES})
