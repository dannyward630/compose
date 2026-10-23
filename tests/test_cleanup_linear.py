import hermetic  # first: no test sees the real home
import io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from cleanup_kit import CLI, ENV, FakeLinear, fc, repo
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["HERDR_ENV"] = ""


class CleanLinearLine(unittest.TestCase):
    """Once the project is linked to a feature, clean always says what it did about Linear."""
    NOTHING = "linear  nothing proven merged; states unchanged"

    def lines(self, feature, metas, project_merged, key="k", linear=None):
        gql = linear or mock.Mock(side_effect=AssertionError("Linear called"))
        out = io.StringIO()
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", key), mock.patch.object(fc.fc_linear, "_linear_warned", []), \
             mock.patch.object(fc.fc_linear, "linear_gql", gql), mock.patch("sys.stdout", out):
            fc.fc_linear.linear_merged(feature, metas, project_merged)
        return [line.split("] ", 1)[1] for line in out.getvalue().splitlines()]

    def test_with_a_key_and_nothing_merged_one_line_says_states_are_unchanged(self):
        self.assertEqual(self.lines("ENG-1", [], False), [self.NOTHING])

    def test_without_a_key_and_nothing_merged_one_line_says_linear_is_skipped(self):
        out = self.lines("ENG-1", [], False, key="")
        self.assertEqual(len(out), 1)
        self.assertIn("linear skipped", out[0])

    def test_no_feature_and_nothing_merged_says_nothing(self):
        for key in ("k", ""):
            for project_merged in (False, True):
                self.assertEqual(self.lines(None, [], project_merged, key=key), [])

    def test_merged_tasks_move_to_done_as_before(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("Done", "ENG-2"))
        out = self.lines("ENG-1", [{"id": "001", "linear": "ENG-3"}], False, linear=linear)
        self.assertEqual(out, ["linear ENG-3 -> Done", "linear ENG-2 -> Done"])
        self.assertEqual(linear.states("ENG-3", "ENG-2", "ENG-1"), ["Done", "Done", "In Review"])

    def test_merged_tasks_without_a_key_are_skipped_once_without_calling_linear(self):
        out = self.lines("ENG-1", [{"id": "001", "linear": "ENG-3"}], True, key="")
        self.assertEqual(len(out), 1)
        self.assertIn("linear skipped", out[0])

    def test_a_merged_project_with_no_merged_task_still_rolls_the_feature_up(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("Done", "ENG-1"))
        self.assertEqual(self.lines("ENG-1", [], True, linear=linear), ["linear ENG-1 -> Done"])


class CleanUnderTheTeamLead(unittest.TestCase):
    """clean finishes every Linear roll-up before the merged project's worktree goes, and never takes it from under the team lead
    or from under itself: the team lead's last report still finds the project, and its done finishes the removal."""
    def setUp(self):
        self.r, self.run = repo()
        self.env = {**os.environ, **ENV}
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.r)], check=True, capture_output=True, env=self.env)
        self.wt = self.r.parent / "compose-p"; self.proj = self.wt / ".compose" / "p"
        self.run("checkout", "-q", "-b", "compose/p-001", cwd=self.wt)
        (self.wt / "f.txt").write_text("f\n"); self.run("add", "f.txt", cwd=self.wt); self.run("commit", "-qm", "Add f", cwd=self.wt)
        self.run("checkout", "-q", "compose/p", cwd=self.wt); self.run("merge", "-q", "--ff-only", "compose/p-001", cwd=self.wt)
        self.run("merge", "-q", "--ff-only", "compose/p")
        task = {"id": "001", "title": "f", "files": [], "protected": [], "linear": "ENG-3", "after": ""}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [task]}))
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')

    def lead(self, state):
        d = fc.fc_crew.crew_dir(self.proj)
        (d / "p-orchestrator.json").write_text(json.dumps({"name": "p-orchestrator", "title": "lead", "space": "w1", "tab": "t1", "pane": "p1"}))
        fc.fc_crew.write_report(self.proj, "p-orchestrator", state, "m")

    def cli(self, *args, cwd=None):
        return subprocess.run([CLI, *args], cwd=cwd or self.r, capture_output=True, text=True, env=self.env)

    def test_every_roll_up_is_done_while_the_worktree_is_still_there(self):
        linear, seen = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2")), []
        def gql(query, variables):
            if "issueUpdate" in query:
                seen.append((variables["id"], self.wt.exists()))
            return linear(query, variables)
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", io.StringIO()), \
                mock.patch.object(fc.fc_linear, "linear_gql", gql), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_clean.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        self.assertEqual(seen, [("ENG-3", True), ("ENG-2", True), ("ENG-1", True)])
        self.assertFalse(self.wt.exists())

    def clean_with_a_second_story(self, linear, task016=None):
        """Task 016 (ENG-5) in story ENG-4 next to 001's story ENG-2, with no branch of its own, then a clean."""
        tasks = json.loads((self.proj / "results" / "tasks.json").read_text())
        tasks["tasks"].append({"id": "016", "title": "g", "files": [], "protected": [], "linear": "ENG-5", "after": ""})
        (self.proj / "results" / "tasks.json").write_text(json.dumps(tasks))
        if task016:
            self.assertEqual(self.cli(*task016).returncode, 0)
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", io.StringIO()), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_clean.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        self.assertFalse(self.wt.exists())

    def test_a_merged_project_moves_its_task_done_by_hand_without_a_branch_and_rolls_up(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"),
                            ENG_4=("In Review", "ENG-1"), ENG_5=("In Review", "ENG-4"))
        self.clean_with_a_second_story(linear, ("done", "--project", "p", "--only", "016", "--note", "already green in 001's layer"))
        self.assertEqual(linear.states("ENG-3", "ENG-5", "ENG-2", "ENG-4", "ENG-1"), ["Done"] * 5)

    def test_a_merged_project_rolls_up_the_story_of_a_task_moved_to_done_outside_it(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"),
                            ENG_4=("In Review", "ENG-1"), ENG_5=("Done", "ENG-4"))
        self.clean_with_a_second_story(linear)
        self.assertEqual(linear.states("ENG-3", "ENG-5", "ENG-2", "ENG-4", "ENG-1"), ["Done"] * 5)

    def test_run_inside_the_worktree_it_rolls_linear_up_and_keeps_the_worktree(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"))
        out, here = io.StringIO(), os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.wt)
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", out), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_clean.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        os.chdir(here)
        self.assertEqual(linear.states("ENG-3", "ENG-2", "ENG-1"), ["Done", "Done", "Done"])
        self.assertIn(f"kept while this command runs inside it: run `compose clean --repo {self.r} --project p` from outside it", out.getvalue())
        self.assertTrue((self.proj / "results" / "clean.json").exists())
        self.assertEqual(self.run("branch", "--list", "compose/p", "compose/p-001").stdout.split(), ["+", "compose/p"])

    def test_a_working_team_lead_keeps_the_worktree_until_its_done_and_force_by_name_overrides(self):
        self.lead("working")
        out = self.cli("clean").stdout
        self.assertIn("kept while p-orchestrator last reported working: they go when p-orchestrator reports done", out)
        self.assertTrue(self.proj.exists())
        r = self.cli("report", "--project", "p", "--as", "p-orchestrator", "done", "shipped")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reported p-orchestrator done", r.stdout)
        self.assertIn(f"run `compose clean --repo {self.r} --project p` from outside {self.wt}", r.stdout)
        self.assertIn("removed worktree", self.cli("clean", "--project", "p").stdout)
        self.assertFalse(self.wt.exists())

    def test_force_by_name_removes_it_under_a_working_team_lead(self):
        self.lead("working")
        self.cli("clean", "--force")  # --force alone never overrides a repo-wide clean
        self.assertTrue(self.wt.exists())
        self.cli("clean", "--project", "p", "--force")
        self.assertFalse(self.wt.exists())

    def test_inside_herdr_the_team_leads_done_finishes_clean_from_outside_once_its_turn_ends(self):
        self.lead("working")
        (self.proj / "results" / "clean.json").write_text("{}")
        out, started, real = io.StringIO(), [], subprocess.Popen
        def popen(argv, **kw):  # git still runs; the detached finisher is only recorded
            return started.append((argv, kw)) if argv[0] == "sh" else real(argv, **kw)
        with mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_crew.subprocess, "Popen", popen), \
                mock.patch("sys.stdout", out):
            fc.fc_crew.finish_clean_after_turn(self.proj, "p-orchestrator")
        [(argv, kw)] = started
        self.assertEqual(argv[:3], ["sh", "-c", '"$0" agent wait "$1" --timeout 900000; "$2" clean --repo "$3" --project "$4"'])
        self.assertEqual(argv[4:], ["p-orchestrator", str(Path(CLI).resolve()), str(self.r), "p"])
        self.assertEqual((kw["cwd"], kw["start_new_session"]), (self.r, True))
        self.assertIn(f"clean  p: {self.wt.resolve()} and its branch go once this turn ends", out.getvalue())


class MergeChangesNothing(unittest.TestCase):
    """A branch whose merge into a target leaves the target's tree as it is counts as merged, whatever its patches say."""
    def test_a_merge_that_changes_nothing_proves_a_branch_merged_after_the_earlier_proofs(self):
        r, run = repo()
        def branch(name, text, extra=None):
            run("checkout", "-q", "-b", name, "main"); (r / "a.txt").write_text(text)
            if extra: (r / "b.txt").write_text(extra)
            run("add", "-A"); run("commit", "-qm", name)
        branch("b", "base\nx\n"); branch("same", "base\nx\n", "y\n"); branch("conf", "base\nz\n")  # same: b's change in another patch
        run("checkout", "-q", "-b", "pick", "main"); run("cherry-pick", "-x", "b")  # -x: a new commit, never b itself
        why = lambda b, *t: fc.fc_clean.merge_evidence(r, b, list(t), False)
        self.assertEqual(why("b", "nope", "conf", "same"), "merging it into same changes nothing")
        self.assertEqual(why("main", "same"), "contained in same")
        self.assertEqual(why("b", "pick", "same"), "contained in pick by patch")
        self.assertEqual(why("b", "same", "pick"), "merging it into same changes nothing")  # targets in order
        self.assertIsNone(why("b", "main", "conf"))  # a real change, then a conflict

    GH = """#!/usr/bin/env python3
import json, subprocess, sys; from pathlib import Path
git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
a = sys.argv[1:]
if a[:2] == ["stack", "--version"]: sys.exit(print("gh stack (fake)"))
f = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "fake-gh-stack.json"; s = json.loads(f.read_text()) if f.exists() else None
if a[:2] == ["stack", "init"]: f.write_text(json.dumps({"trunk": a[a.index("--base") + 1], "branches": [{"name": b} for b in a[4:]]}))
elif a[:2] == ["stack", "view"] and s and git("branch", "--show-current") in [b["name"] for b in s["branches"]]: print(json.dumps(s))
elif a[:2] == ["stack", "unstack"]: f.unlink(missing_ok=True)
else: sys.exit(1)
"""

    def test_clean_removes_a_stack_recut_on_a_moved_main_once_it_lands_and_moves_linear(self):
        r, run = repo()
        bin_ = Path(tempfile.mkdtemp()).resolve(); (bin_ / "gh").write_text(self.GH); (bin_ / "gh").chmod(0o755)
        env = {**os.environ, **ENV, "PATH": f"{bin_}:{os.environ['PATH']}"}
        pins = 'M = {\n    "core": ("now",),\n    "keys": ("key_status", "linear_connected", "save_key"),\n    "steps": ("FLOORS",),\n    "worktree": ("task_prefix", "task_branch"),\n}\n'
        (r / "pins.py").write_text(pins); run("add", "-A"); run("commit", "-qm", "pins")
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(r)], check=True, capture_output=True, env=env)
        wt = r.parent / "compose-p"; proj = wt / ".compose" / "p"
        def commit(f, text, msg, cwd=wt):
            (cwd / f).parent.mkdir(parents=True, exist_ok=True); (cwd / f).write_text(text)
            run("add", "-A", cwd=cwd); run("commit", "-qm", msg, cwd=cwd)
        commit("pins.py", pins.replace('"linear_connected", ', ""), "groundwork")
        commit("tests/t001.txt", "t\n", "test 001"); commit("tests/t002.txt", "t\n", "test 002")
        tasks = [{"id": t, "title": t, "files": [f"src{t}.txt"], "protected": [f"tests/t{t}.txt"], "linear": l, "after": "", "test": "true"} for t, l in (("001", "ENG-3"), ("002", "ENG-4"))]
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks})); (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        for t in ("001", "002"):
            run("checkout", "-q", "-b", f"compose/p-{t}", "compose/p", cwd=wt); commit(f"src{t}.txt", "s\n", f"build {t}")
            run("checkout", "-q", "compose/p", cwd=wt)
        commit("pins.py", pins.replace('("task_prefix", "task_branch")', '("task_prefix", "rename", "task_branch")'), "main moves", cwd=r)  # inside the groundwork's diff context
        subprocess.run([CLI, "stack", "--repo", str(wt), "--project", "p"], check=True, capture_output=True, text=True, env=env)
        run("merge", "-q", "--ff-only", run("branch", "--list", "compose/p-layer-*", "--format=%(refname:short)").stdout.split()[-1])
        linear, out = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("In Review", "ENG-2")), io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", out), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_clean.clean_project(r, "p", wt, proj, explicit=True)
        left = run("branch", "--format=%(refname:short)").stdout.split()
        self.assertEqual([b for b in left if b in ("compose/p", "compose/p-001", "compose/p-002")], [], out.getvalue())
        self.assertFalse(wt.exists())
        self.assertNotIn("UNMERGED", out.getvalue()); self.assertNotIn("kept unmerged", out.getvalue())
        self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-2", "ENG-1"), ["Done", "Done", "Done", "Done"])


class ReviewBaseFirst(unittest.TestCase):
    """Task branches are checked against the review base first, and each kept branch names its first commit with no patch there."""
    def setUp(self):
        self.r, self.run = repo()
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.r)], check=True, capture_output=True, env={**os.environ, **ENV})
        self.wt = self.r.parent / "compose-p"; self.proj = self.wt / ".compose" / "p"

    def commit(self, branch, *subjects):
        """Commits on a new branch cut from compose/p (on compose/p itself when branch is None); their short shas, oldest first."""
        if branch:
            self.run("checkout", "-q", "-b", branch, "compose/p", cwd=self.wt)
        for s in subjects:
            (self.wt / s.replace(" ", "_")).write_text(f"{s}\n"); self.run("add", "-A", cwd=self.wt); self.run("commit", "-qm", s, cwd=self.wt)
        self.run("checkout", "-q", "compose/p", cwd=self.wt)
        return [self.run("rev-parse", "--short", f"{branch or 'compose/p'}~{i}").stdout.strip() for i in reversed(range(len(subjects)))]

    def clean(self, linear=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", out), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_clean.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        return out.getvalue().splitlines()

    def test_task_branches_meet_the_review_base_first_and_kept_ones_name_their_first_unmatched_commit(self):
        self.commit("compose/p-002", "build 002"); self.run("merge", "-q", "--ff-only", "compose/p-002", cwd=self.wt)
        self.commit("compose/p-001", "build 001"); self.run("branch", "compose/base", "compose/p-001")  # 001 only in the review base
        three = self.commit("compose/p-003", "add three", "fix three")  # against main, build 002 would come first
        four, layer = self.commit("compose/p-004", "add four"), self.commit("compose/p-layer-01", "stack one")
        cfg = json.loads((self.proj / "verify.json").read_text()); cfg["review_base"] = "compose/base"
        (self.proj / "verify.json").write_text(json.dumps(cfg))
        tasks = [{"id": t, "title": t, "files": [], "protected": [], "linear": f"ENG-{n}", "after": "", "test": "true"} for n, t in enumerate(("001", "002", "003", "004"), 3)]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks})); (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), **{f"ENG_{n}": ("In Review", "ENG-2") for n in range(3, 7)})
        lines = self.clean(linear)
        self.assertIn("clean  compose/p-001: contained in compose/base", lines)
        self.assertIn("clean  compose/p-002: contained in compose/base", lines)  # compose/p holds it too
        self.assertIn(f"clean  compose/p-003: kept unmerged, first unmatched commit {three[0]} add three and 1 more", lines)
        self.assertIn(f"clean  compose/p-004: kept unmerged, first unmatched commit {four[0]} add four", lines)
        self.assertIn(f"clean  compose/p-layer-01: kept unmerged, first unmatched commit {layer[0]} stack one", lines)
        self.assertEqual(self.run("branch", "--list", "compose/p-*", "--format=%(refname:short)").stdout.split(), ["compose/p-003", "compose/p-004", "compose/p-layer-01"])
        self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-5", "ENG-6"), ["Done", "Done", "In Review", "In Review"])

    def test_a_project_branch_kept_as_not_merged_yet_names_its_first_unmatched_commit_before_the_summary(self):
        first = self.commit(None, "groundwork one", "groundwork two")
        lines = self.clean()
        kept = f"clean  compose/p: kept unmerged, first unmatched commit {first[0]} groundwork one and 1 more"
        self.assertIn(kept, lines, lines)
        self.assertLess(lines.index(kept), next(i for i, l in enumerate(lines) if "project branch compose/p not merged yet" in l))
        self.assertTrue(self.wt.exists())


if __name__ == "__main__":
    unittest.main()
