import hermetic  # first: no test sees the real home
import io, json, os, subprocess, sys, tempfile, unittest
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


class Fixture(unittest.TestCase):
    def setUp(self):  # seed pushes to a bare remote; checkout is the CLI's own clone of it
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); root = Path(os.path.realpath(t.name))
        self.seed, self.remote, self.co = root / "seed", root / "remote.git", root / "my checkout"
        git(root, "init", "-q", "-b", "main", str(self.seed)); commit(self.seed, "a")
        git(root, "clone", "-q", "--bare", str(self.seed), str(self.remote))
        git(root, "clone", "-q", str(self.remote), str(self.co))
        self.relink = mock.Mock(return_value=["linked compose CLI link"])
        self.live = root / "live"  # the registry of runs and verifies: this test's, not the machine's
        p = mock.patch.object(fc_update, "live_dir", return_value=self.live); p.start(); self.addCleanup(p.stop)
    def update(self, doctor_code=0, force=False):
        def doctor(a):
            print("doctor says hi"); sys.exit(doctor_code) if doctor_code else None
        out = io.StringIO()  # sys.exit("message") prints it and exits 1
        with mock.patch.object(fc_update, "__file__", str(self.co / "bin" / "fc_update.py")), \
             mock.patch.object(fc_links, "relink_owned", self.relink), mock.patch.object(fc_init, "cmd_doctor", doctor), \
             redirect_stdout(out), redirect_stderr(out), self.assertRaises(SystemExit) as e:
            fc_update.cmd_update(mock.Mock(force=force))
        code = e.exception.code
        return (1, out.getvalue() + code + "\n") if isinstance(code, str) else (code or 0, out.getvalue())


class Update(Fixture):
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

    def test_commits_only_here_are_rebased_onto_upstream_and_the_update_goes_on(self):
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main"); commit(self.co, "c")
        here = git(self.co, "rev-parse", "HEAD").strip()[:12]
        code, out = self.update()
        self.assertEqual(code, 0, out); self.assertNotIn("hint:", out)
        self.assertTrue((self.co / "b").exists()); self.assertTrue((self.co / "c").exists())
        self.assertEqual(git(self.co, "log", "--format=%s", "origin/main..HEAD").split(), ["c"])  # c now sits on top of upstream's b
        self.assertIn("main had 1 commit origin/main lacked; rebased onto it, 0 already upstream dropped", out)
        self.assertRegex(out, rf"\+ {here} c\b.*only here"); self.assertIn("stay only in this checkout", out)
        self.relink.assert_called_once_with(self.co); self.assertIn("doctor says hi", out)

    def test_commits_already_upstream_under_another_hash_are_dropped_not_replayed(self):
        commit(self.co, "c"); git(self.seed, "pull", "-q", str(self.co), "main")
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main")
        git(self.co, "commit", "-q", "--amend", "-m", "c, reworded here")  # same patch, another hash
        code, out = self.update()
        self.assertEqual(code, 0, out); self.assertRegex(out, r"- \w+ c, reworded here.*already on origin/main")
        self.assertIn("1 already upstream dropped", out); self.assertNotIn("stay only in this checkout", out)
        self.assertEqual(git(self.co, "rev-parse", "HEAD"), git(self.co, "rev-parse", "origin/main"))
        self.assertEqual((self.co / "c").read_text(), "c")

    def test_a_rebase_that_conflicts_is_aborted_and_the_state_and_fix_are_printed(self):
        (self.seed / "a").write_text("theirs"); git(self.seed, "commit", "-qam", "theirs"); git(self.seed, "push", "-q", str(self.remote), "main")
        (self.co / "a").write_text("mine"); git(self.co, "commit", "-qam", "mine")
        mine = git(self.co, "rev-parse", "HEAD")
        code, out = self.update()
        self.assertEqual(code, 1); self.relink.assert_not_called()
        self.assertEqual(git(self.co, "rev-parse", "HEAD"), mine); self.assertEqual((self.co / "a").read_text(), "mine")
        self.assertFalse((self.co / ".git" / "rebase-merge").exists()); self.assertEqual(git(self.co, "status", "--porcelain"), "")
        self.assertIn("stopped", out); self.assertIn(f"back at {mine.strip()[:7]}", out)
        self.assertIn("main has 1 commit that origin/main does not", out)
        self.assertRegex(out, r"\+ \w+ mine.*only here"); self.assertIn(f"git -C '{self.co}' rebase origin/main", out)
        self.assertIn("Then run compose update again.", out)

    def test_local_commits_with_an_unreachable_remote_are_not_rebased_over_a_failed_fetch(self):
        commit(self.co, "c"); before = git(self.co, "rev-parse", "HEAD")
        git(self.co, "remote", "set-url", "origin", str(self.remote.with_name("gone.git")))
        code, out = self.update()
        self.assertEqual(code, 1); self.relink.assert_not_called(); self.assertNotIn("rebased", out)
        self.assertEqual(len([l for l in out.splitlines() if "gone.git" in l]), 1, out); self.assertEqual(git(self.co, "rev-parse", "HEAD"), before)

    def test_other_pull_failures_print_gits_message_on_one_line_and_relink_nothing(self):
        git(self.co, "remote", "set-url", "origin", str(self.remote.with_name("gone.git")))
        code, out = self.update()
        self.assertEqual(code, 1); self.relink.assert_not_called()
        self.assertEqual(len([l for l in out.splitlines() if "gone.git" in l]), 1, out)


class Freeze(Fixture):
    """A run or verify live anywhere on this machine freezes the CLI: `compose update` names it and changes nothing, `--force` overrides."""
    def setUp(self):
        super().setUp()
        self.proc = subprocess.Popen(["sleep", "60"]); self.addCleanup(self.proc.wait); self.addCleanup(self.proc.kill)
        commit(self.seed, "b"); git(self.seed, "push", "-q", str(self.remote), "main")
    def register(self, pid, kind="run", project="shop", name=None):
        self.live.mkdir(exist_ok=True)
        (self.live / f"{name or pid}.json").write_text(json.dumps({"pid": pid, "kind": kind, "project": project, "repo": "/work/shop", "since": "10:02"}))

    def test_a_live_run_or_verify_stops_the_update_before_it_pulls_naming_the_project(self):
        for kind in ("run", "verify"):
            with self.subTest(kind):
                self.register(self.proc.pid, kind)
                code, out = self.update()
                self.assertEqual(code, 1); self.assertFalse((self.co / "b").exists()); self.relink.assert_not_called()
                self.assertIn(f"shop: {kind} live since 10:02 (pid {self.proc.pid}) in /work/shop", out); self.assertIn("--force", out)

    def test_force_updates_anyway(self):
        self.register(self.proc.pid)
        code, out = self.update(force=True)
        self.assertEqual(code, 0, out); self.assertTrue((self.co / "b").exists())

    def test_nothing_live_updates_as_before_and_a_dead_runs_file_is_ignored_and_removed(self):
        dead = subprocess.Popen(["true"]); dead.wait(); self.register(dead.pid)
        code, out = self.update()
        self.assertEqual(code, 0, out); self.assertTrue((self.co / "b").exists()); self.assertEqual(list(self.live.glob("*.json")), [])

    def test_a_broken_registry_file_is_skipped(self):
        self.register(self.proc.pid, name="x"); (self.live / "junk.json").write_text("{not json")
        self.assertEqual([w["pid"] for w in fc_update.live_work()], [self.proc.pid])

    def test_hold_registers_this_process_until_it_exits(self):
        script = ("import sys, json, pathlib; sys.path.insert(0, sys.argv[1]); import fc_update; "
                  "fc_update.live_dir = lambda: pathlib.Path(sys.argv[2]); "
                  "fc_update.hold('verify', 'shop', '.'); print(json.dumps(fc_update.live_work()))")
        out = subprocess.run([sys.executable, "-c", script, str(Path(fc_update.__file__).parent), str(self.live)],
                             capture_output=True, text=True, check=True).stdout
        [held] = json.loads(out); self.assertEqual((held["kind"], held["project"]), ("verify", "shop")); self.assertEqual(held["repo"], os.path.realpath("."))
        self.assertEqual(fc_update.live_work(), [])  # the process exited: its file is gone
