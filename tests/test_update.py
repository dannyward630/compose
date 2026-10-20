import hermetic  # first: no test sees the real home
import io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_init, fc_links, fc_update

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]

def git(cwd, *args):
    return subprocess.run([*GIT, "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout

def commit(repo, name):
    (repo / name).write_text(name); git(repo, "add", name); git(repo, "commit", "-m", name)


class Update(unittest.TestCase):
    def setUp(self):  # seed pushes to a bare remote; checkout is the CLI's own clone of it
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); root = Path(os.path.realpath(t.name))
        self.seed, self.remote, self.co = root / "seed", root / "remote.git", root / "my checkout"
        git(root, "init", "-q", "-b", "main", str(self.seed)); commit(self.seed, "a")
        git(root, "clone", "-q", "--bare", str(self.seed), str(self.remote))
        git(root, "clone", "-q", str(self.remote), str(self.co))
        self.relink = mock.Mock(return_value=["linked compose CLI link"])
    def update(self, doctor_code=0):
        def doctor(a):
            print("doctor says hi"); sys.exit(doctor_code) if doctor_code else None
        out = io.StringIO()  # sys.exit("message") prints it and exits 1
        with mock.patch.object(fc_update, "__file__", str(self.co / "bin" / "fc_update.py")), \
             mock.patch.object(fc_links, "relink_owned", self.relink), mock.patch.object(fc_init, "cmd_doctor", doctor), \
             redirect_stdout(out), redirect_stderr(out), self.assertRaises(SystemExit) as e:
            fc_update.cmd_update(mock.Mock())
        code = e.exception.code
        return (1, out.getvalue() + code + "\n") if isinstance(code, str) else (code or 0, out.getvalue())
    def test_fast_forward_relinks_then_runs_doctor_and_exits_with_its_code(self):
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main")
        code, out = self.update()
        self.assertEqual(code, 0); self.assertTrue((self.co / "b").exists())
        self.relink.assert_called_once_with(self.co)
        self.assertLess(out.index("linked compose CLI link"), out.index("doctor says hi"))
        self.assertEqual(self.update(doctor_code=1)[0], 1)  # already up to date: still relinks and runs doctor
        self.assertEqual(self.relink.call_count, 2)

    def test_local_changes_or_untracked_files_stop_before_pulling(self):
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main")
        for dirty in ("a", "new"):
            with self.subTest(dirty):
                (self.co / dirty).write_text("edited")
                code, out = self.update()
                self.assertEqual(code, 1); self.assertFalse((self.co / "b").exists())
                line = next(l for l in out.splitlines() if str(self.co) in l)
                self.assertRegex(line, "commit|stash"); self.relink.assert_not_called()
                (self.co / dirty).unlink() if dirty == "new" else git(self.co, "restore", "a")

    def advice(self, out):  # the command the diverged message tells the user to run
        return next(l.strip() for l in out.splitlines() if l.strip().startswith("git -C "))
    def test_diverged_commits_only_here_are_listed_and_rebase_is_the_advice_that_works(self):
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main"); commit(self.co, "c")
        here = git(self.co, "rev-parse", "HEAD").strip()[:12]
        code, out = self.update()
        self.assertEqual(code, 1); self.relink.assert_not_called(); self.assertFalse((self.co / "b").exists())
        self.assertNotIn("hint:", out)
        self.assertIn("main has 1 commit that origin/main does not", out)
        self.assertRegex(out, rf"\+ {here} c\b.*only here")
        cmd = self.advice(out)
        self.assertIn("rebase origin/main", cmd); self.assertIn(f"'{self.co}'", cmd)
        subprocess.run(cmd, shell=True, check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.assertEqual(self.update()[0], 0); self.assertTrue((self.co / "b").exists()); self.assertTrue((self.co / "c").exists())

    def test_diverged_commits_already_upstream_point_to_reset_which_keeps_nothing_lost(self):
        commit(self.co, "c"); git(self.seed, "pull", "-q", str(self.co), "main")
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main")
        git(self.co, "commit", "-q", "--amend", "-m", "c, reworded here")  # same patch, another hash
        code, out = self.update()
        self.assertEqual(code, 1); self.relink.assert_not_called()
        self.assertRegex(out, r"- \w+ c, reworded here.*already on origin/main")
        cmd = self.advice(out); self.assertIn("reset --hard origin/main", cmd)
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        self.assertEqual(self.update()[0], 0); self.assertEqual((self.co / "c").read_text(), "c")

    def test_diverged_with_any_commit_only_here_advises_rebase_not_reset(self):
        commit(self.co, "c"); git(self.seed, "pull", "-q", str(self.co), "main")
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main")
        git(self.co, "commit", "-q", "--amend", "-m", "c again"); commit(self.co, "d")
        code, out = self.update()
        self.assertIn("main has 2 commits that origin/main does not", out)
        self.assertIn("rebase origin/main", self.advice(out)); self.assertNotIn("reset --hard", out)

    def test_other_pull_failures_print_gits_message_on_one_line_and_relink_nothing(self):
        git(self.co, "remote", "set-url", "origin", str(self.remote.with_name("gone.git")))
        code, out = self.update()
        self.assertEqual(code, 1); self.relink.assert_not_called()
        self.assertEqual(len([l for l in out.splitlines() if "gone.git" in l]), 1, out)
