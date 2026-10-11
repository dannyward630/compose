import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
ENV = {**os.environ, "FAST_CODING_NO_GRAFT": "1", "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", CLI))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class NoTrace(unittest.TestCase):
    """The delivered branch carries no trace of the tool: its files are ignored before anything, never committed,
    and no commit message names it."""
    def make(self, gitignore):
        self.repo = Path(tempfile.mkdtemp()) / "repo"
        self.repo.mkdir()
        (self.repo / "a.txt").write_text("base\n")
        if gitignore is not None:
            (self.repo / ".gitignore").write_text(gitignore)
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "init")):
            self.git(self.repo, *args)
        self.wt = self.repo.parent / "fast-coding-p"

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout

    def init(self):
        p = subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.repo)], capture_output=True, text=True, env=ENV)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_existing_gitignore_gets_the_lines_first_and_nothing_tool_made_is_committed(self):
        self.make("node_modules\n/graft/\n")
        (self.repo / ".fast-coding").mkdir()
        (self.repo / ".fast-coding" / "linear.json").write_text('{"project": "x"}')  # step 0, in the user's checkout
        self.init()
        self.assertEqual((self.wt / ".gitignore").read_text(), "node_modules\n/graft/\n.fast-coding/\n")  # graft already there
        self.assertEqual(self.git(self.wt, "log", "--format=%s", "main..HEAD").splitlines(), ["Ignore local tool directories"])
        self.assertEqual(self.git(self.wt, "ls-files", ".fast-coding"), "")
        self.assertTrue((self.wt / ".fast-coding" / "p" / "verify.json").exists())
        self.assertEqual(json.loads((self.wt / ".fast-coding" / "linear.json").read_text()), {"project": "x"})  # copied, not via git
        (self.wt / ".ignore").write_text("!graft\n")  # what graft writes for ripgrep
        (self.wt / "graft").mkdir(); (self.wt / "graft" / "n.md").write_text("x")
        self.assertEqual(self.git(self.wt, "status", "--porcelain"), "")
        self.assertEqual(self.git(self.repo, "status", "--porcelain"), "")  # the user's checkout too, through the shared exclude
        self.init()  # idempotent: no second commit
        self.assertEqual(len(self.git(self.wt, "log", "--format=%s", "main..HEAD").splitlines()), 1)
        self.assertIn("p ", subprocess.run([CLI, "projects", "--repo", str(self.repo)], capture_output=True, text=True, env=ENV).stdout)

    def test_no_gitignore_means_no_new_file_and_no_commit(self):
        self.make(None)
        self.init()
        self.assertFalse((self.wt / ".gitignore").exists())
        self.assertEqual(self.git(self.wt, "log", "--format=%s", "main..HEAD"), "")
        self.assertEqual(self.git(self.wt, "status", "--porcelain"), "")

    def test_task_commit_message_is_the_change(self):
        self.assertEqual(fc.commit_message({"title": "001 SQLite store: open, schema"}), "SQLite store: open, schema")
        self.assertEqual(fc.commit_message({"title": "Add a favicon"}), "Add a favicon")
        self.assertEqual(fc.commit_message({"title": "007", "files": ["a.go"]}), "Update a.go")


if __name__ == "__main__":
    unittest.main()
