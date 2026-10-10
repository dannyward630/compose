import json, os, subprocess, tempfile, unittest
from pathlib import Path

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
ENV = {**os.environ, "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def issues(n):
    return [{"id": f"{i:03d}", "title": f"task {i}", "status": "", "blockedBy": [],
             "description": f"## Goal\nDo {i}.\n\n```fast-coding\nid: {i:03d}\nfiles: f{i}.txt\ntest: false\n```\n"} for i in range(1, n + 1)]


class Lite(unittest.TestCase):
    """A lite project runs without Linear: `init --lite` marks it, `sync` takes the orchestrator's own JSON, `tasks` warns past 12."""
    def fc(self, *args, stdin=None):
        p = subprocess.run([CLI, *args, "--repo", str(self.repo)], capture_output=True, text=True, env=ENV, input=stdin)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()) / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, env=ENV)
        run("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        run("add", "-A"); run("commit", "-qm", "init")

    def sync(self, slug, n):
        return self.fc("sync", "--project", slug, stdin=json.dumps({"feature": {"id": slug, "title": "t", "description": "## Plan"}, "issues": issues(n)}))

    def test_lite_syncs_without_linear_and_warns_past_twelve_tasks(self):
        out = self.fc("init", "--project", "hw", "--lite")
        self.assertIn("lite, no Linear", out)
        self.assertEqual(json.loads((self.repo.parent / "fast-coding-hw" / ".fast-coding" / "hw" / "linear.json").read_text()),
                         {"feature": "hw", "lite": True})
        self.assertIn("12 task(s) synced", self.sync("hw", 12))
        self.assertNotIn("LITE PROJECT", self.fc("tasks", "--project", "hw"))
        self.sync("hw", 13)
        self.assertIn("WARNING LITE PROJECT HAS 13 TASKS", self.fc("tasks", "--project", "hw"))

    def test_full_project_never_gets_the_lite_warning(self):
        self.fc("init", "--project", "big")
        (self.repo.parent / "fast-coding-big" / ".fast-coding" / "big" / "linear.json").write_text(json.dumps({"feature": "big"}))
        self.sync("big", 13)
        self.assertNotIn("LITE PROJECT", self.fc("tasks", "--project", "big"))


if __name__ == "__main__":
    unittest.main()
