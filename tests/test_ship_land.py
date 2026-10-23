import hermetic  # first: no test sees the real home
import json, os, subprocess, unittest
from unittest import mock
from ship_kit import Ship, fc
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""


class Land(Ship):
    def submitted(self):
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(self.prs()), ["1", "2", "3"])

    def test_without_yes_it_prints_the_plan_and_changes_nothing(self):
        self.submitted()
        refs = lambda: subprocess.run(["git", "--git-dir", str(self.origin), "for-each-ref"], capture_output=True, text=True).stdout
        before, log = refs(), self.log()
        out, code = self.land(yes=False)
        self.assertEqual(code, 0)
        self.assertTrue(any("land   plan  3 of 3 layer(s) submitted, verify not run; landing 3 into main by squash, bottom up:" in l for l in out))
        self.assertTrue(any("nothing was merged or pushed" in l and "--yes" in l for l in out))
        self.assertEqual(refs(), before)
        self.assertEqual([c for c in self.log()[len(log):] if not c.startswith("pr view")], [])

    def test_it_refuses_while_a_verify_holds_the_stack_top_and_merges_nothing(self):
        self.submitted()
        proc = subprocess.Popen(["sleep", "60"]); self.addCleanup(proc.wait); self.addCleanup(proc.kill)
        live = fc.fc_update.live_dir(); live.mkdir(parents=True, exist_ok=True)
        (live / f"{proc.pid}.json").write_text(json.dumps({"pid": proc.pid, "kind": "verify", "project": "p", "repo": str(self.repo), "since": "21:01"}))
        log = self.log()
        with self.assertRaises(SystemExit) as e:
            fc.fc_ship.cmd_land(self.args(yes=True, method=None, timeout=1))
        self.assertIn(f"verify is running on p (pid {proc.pid}", str(e.exception))
        self.assertEqual([c for c in self.log()[len(log):] if not c.startswith("pr view")], [])

    def test_a_gh_failure_is_told_apart_from_a_missing_pull_request(self):
        self.submit()
        with mock.patch.dict(os.environ, {"FAKE_GH_VIEW_FAIL": "error connecting to api.github.com"}):
            out, code = self.land()
        self.assertEqual(code, 1)
        self.assertIn("land   STOP  gh pr view failed for compose/p-layer-01: error connecting to api.github.com", out)
        self.assertFalse(any("has no pull request" in l for l in out))
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))

    def test_a_stack_that_was_not_submitted_names_the_missing_pull_request(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        out, code = self.land(yes=False)
        self.assertEqual(code, 1)
        self.assertTrue(any("has no pull request" in l and "compose stack --submit" in l for l in out))

    def test_it_merges_bottom_up_waits_for_checks_and_moves_each_next_pr_onto_the_base(self):
        self.submitted()
        self.set_pr(1, checks=["pending", "pending", "pass"])
        self.set_pr(3, checks=["none"])
        out, code = self.land()
        self.assertEqual(code, 0, out)
        prs = self.prs()
        self.assertEqual([p["state"] for p in prs.values()], ["MERGED"] * 3)
        self.assertEqual([p["base"] for p in prs.values()], ["main"] * 3)
        log = self.log()
        merges = [c for c in log if c.startswith("pr merge")]
        self.assertEqual(merges, ["pr merge 1 --squash", "pr merge 2 --squash", "pr merge 3 --squash"])
        self.assertEqual([c for c in log if c.startswith("pr ready")], ["pr ready 1", "pr ready 2", "pr ready 3"])
        self.assertLess(log.index("pr merge 1 --squash"), log.index("pr edit 2 --base main"))
        self.assertLess(log.index("pr edit 2 --base main"), log.index("pr merge 2 --squash"))
        self.assertLess(log.index("pr merge 2 --squash"), log.index("pr edit 3 --base main"))
        self.assertGreaterEqual(len([c for c in log if c.startswith("pr checks 1")]), 3)
        top = subprocess.run(["git", "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only", "main"], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(top), ["001.src", "002.src", "003.src", "README.md", "setup.txt", "t001.test", "t002.test", "t003.test"])
        self.assertEqual(out[-1], "next: compose clean --project p")
        self.assertFalse((self.proj / "results" / "land.json").exists())
        self.assertEqual(self.git("branch", "--show-current"), "compose/p")  # the user's checkout never moved

    def test_a_failing_check_on_the_first_pr_stops_before_anything_is_merged_or_moved(self):
        self.submitted()
        pushed_before = self.git("rev-parse", "compose/p-layer-03")
        self.set_pr(1, checks=["fail"])
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("required checks on #1 (compose/p-layer-01): fail: ci" in l for l in out))
        self.assertEqual(self.prs()["1"]["state"], "OPEN")
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))
        self.assertEqual(self.git("rev-parse", "compose/p-layer-03"), pushed_before)

    def test_a_failing_check_stops_the_land_and_a_rerun_resumes_where_it_stopped(self):
        self.submitted()
        self.set_pr(2, checks=["fail"])
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED", "OPEN", "OPEN"])
        self.assertTrue(any("required checks on #2" in l and "re-run `compose land` to resume" in l for l in out))
        self.assertEqual(self.prs()["2"]["base"], "main")  # moved onto the base before its checks were read
        self.assertTrue((self.proj / "results" / "land.json").exists())
        self.set_pr(2, checks=["pass"])
        merges = len([c for c in self.log() if c.startswith("pr merge")])
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED"] * 3)
        self.assertEqual(len([c for c in self.log() if c.startswith("pr merge")]), merges + 2)  # PR 1 is not merged twice
        self.assertTrue(any("#1" in l and "already merged" in l for l in out))

    def test_checks_that_stay_pending_stop_it_at_the_timeout(self):
        self.submitted()
        self.set_pr(1, checks=["pending"])
        out, code = self.land(timeout=0)
        self.assertEqual(code, 1)
        self.assertTrue(any("still pending after 0 minutes" in l for l in out))
        self.assertEqual(self.prs()["1"]["state"], "OPEN")

    def test_a_refused_merge_stops_with_what_github_said(self):
        self.submitted()
        self.set_pr(1, refuse="Pull request is not mergeable: the base branch policy prohibits the merge")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("gh pr merge #1" in l and "base branch policy prohibits" in l for l in out))

    def test_a_pr_whose_head_is_not_what_was_submitted_is_not_merged(self):
        self.submitted()
        self.git("checkout", "-q", "compose/p-layer-01")
        self.write("extra.txt", "x\n"); self.commit("Local change")
        self.git("checkout", "-q", "compose/p")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("has commits compose did not push" in l or "submit" in l for l in out))
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))

    def test_a_next_layer_that_conflicts_with_the_base_stops_with_the_files_and_pushes_nothing(self):
        self.submitted()
        self.set_pr(1, extra=["002.src", "from the base\n"])
        top = self.git("rev-parse", "compose/p-layer-02")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertEqual(self.prs()["1"]["state"], "MERGED")
        self.assertTrue(any("compose/p-layer-02 conflicts with main in 002.src" in l and "nothing of it was pushed" in l for l in out), out)
        self.assertEqual(self.git("rev-parse", "compose/p-layer-02"), top)
        self.assertEqual(self.prs()["2"]["state"], "OPEN")
        self.assertEqual(self.prs()["2"]["base"], "compose/p-layer-01")
        self.assertEqual(self.git("-C", str(fc.fc_worktree.stack_worktree(self.repo, self.proj, "compose/p")), "status", "--porcelain"), "")  # no rebase left half done

    def test_a_pr_behind_the_base_is_updated_before_it_merges(self):
        self.submitted()
        self.set_pr(1, behind=True)
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertIn("pr update-branch 1 --rebase", self.log())
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED"] * 3)

    def stacked(self):
        self.submitted()
        for n in (1, 2, 3):
            self.set_pr(n, stacked=True)

    def test_a_github_stack_merges_through_the_async_api_and_keeps_the_heads_github_rewrote(self):
        self.stacked()
        top = self.git("rev-parse", "compose/p-layer-03")
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual([p["state"] for p in self.prs().values()], ["MERGED"] * 3)
        log = self.log()
        self.assertFalse([c for c in log if c.startswith(("pr merge", "pr update-branch")) or ("pr edit" in c and "--base" in c)])
        puts = [c for c in log if " PUT " in f" {c} "]
        self.assertEqual(len(puts), 3)
        self.assertTrue(all("merge_method=squash" in c and "merge_action=direct_merge" in c and "sha=" in c for c in puts), puts)
        self.assertLess(log.index("pr ready 1"), log.index(puts[0]))
        self.assertEqual(self.git("rev-parse", "compose/p-layer-03"), top)  # compose rebased and pushed nothing
        self.assertEqual(out[-1], "next: compose clean --project p")

    def test_a_github_stack_follows_the_merge_method(self):
        self.stacked()
        self.land(method="rebase")
        puts = [c for c in self.log() if " PUT " in f" {c} "]
        self.assertTrue(puts and all("merge_method=rebase" in c for c in puts), puts)

    def test_a_github_stack_merge_that_fails_stops_with_what_github_said(self):
        self.stacked()
        self.set_pr(1, refuse="Required status check is expected")
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any("merge of #1" in l and "Required status check is expected" in l for l in out), out)
        self.assertEqual(self.prs()["1"]["state"], "OPEN")

    def test_the_merge_method_follows_the_flag_then_verify_json(self):
        self.submitted()
        self.config(land_method="rebase")
        self.land()
        self.assertEqual([c for c in self.log() if c.startswith("pr merge")][0], "pr merge 1 --rebase")


if __name__ == "__main__":
    unittest.main()
