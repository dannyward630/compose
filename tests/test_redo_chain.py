import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class RedoMidChain(unittest.TestCase):
    """Rebuilding a layer in the middle of the stack: the layers above still carry its old commit, and the chain rebase drops it."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start()
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True); (self.proj / "worktrees").mkdir()
        (self.repo / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")
        after = {"011": "010", "012": "011", "005": "012"}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": t, "after": after.get(t, "")} for t in ("010", "011", "012", "005")]}))
        for t, base in (("010", "main"), ("011", "fast/p/010"), ("012", "fast/p/011"), ("005", "fast/p/012")):
            self.layer(t, base, "c.txt" if t == "011" else f"{t}.txt", "old\n")

    def tearDown(self):
        self.env.stop()

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def layer(self, tid, base, name, text):
        self.git("checkout", "-q", "-b", f"fast/p/{tid}", base)
        (self.repo / name).write_text(text)
        self.git("add", "-A"); self.git("commit", "-qm", f"task {tid}")
        self.git("checkout", "-q", "main")

    def test_layers_above_a_rebuilt_layer_replay_onto_it_without_its_old_commit(self):
        fc.replace_branch(self.repo, self.proj, "fast/p/011")
        self.layer("011", "fast/p/010", "c.txt", "new\n")
        chain = fc.linearize(self.repo, self.proj, "main", fc.stack_worktree(self.repo, self.proj, "main"))
        self.assertEqual(chain, [f"fast/p/{t}" for t in ("010", "011", "012", "005")])
        self.assertEqual(self.git("show", "fast/p/005:c.txt"), "new")
        self.assertEqual(self.git("rev-list", "--count", "main..fast/p/005"), "4")  # one commit per layer, the old 011 is gone
        self.assertEqual(self.git("for-each-ref", "refs/fast-coding/replaced/"), "")  # nothing carries the old tip any more
