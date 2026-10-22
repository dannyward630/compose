import hermetic  # first: no test sees the real home
import json, os, subprocess, unittest
from ship_kit import Ship, fc
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""


class PartialSubmit(Ship):
    def result(self, tid, status):
        (self.proj / "results" / f"{tid}.json").write_text(json.dumps({"status": status}))

    def origin_git(self, *a):
        return subprocess.run(["git", "--git-dir", str(self.origin), *a], check=True, capture_output=True, text=True).stdout.split()

    def pushed(self):
        """Origin's layer refs and SHAs, and every file in any ref but main."""
        refs = {r.removeprefix("refs/heads/"): s for s, r in zip(*[iter(self.origin_git("for-each-ref", "--format=%(objectname) %(refname)", "refs/heads/compose"))] * 2)}
        return refs, {f for r in refs for f in self.origin_git("ls-tree", "-r", "--name-only", r)}

    def test_a_failed_task_holds_it_and_the_ones_after_back_and_a_later_submit_adds_them(self):
        self.result("002", "failed")
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue(any("stack  hold  002 is failed; 002, 003 not submitted" in l for l in out), out)
        before, files = self.pushed()
        self.assertTrue({"setup.txt", "001.src", "t001.test"} <= files)
        self.assertFalse(files & {"002.src", "003.src", "t002.test", "t003.test"})
        self.assertEqual(set(json.loads((self.proj / "results" / "prs.json").read_text())), set(before))
        self.result("002", "passed")
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        after, files = self.pushed()
        self.assertTrue({"002.src", "003.src", "t002.test", "t003.test"} <= files)
        self.assertEqual({b: after[b] for b in before}, before)
        self.assertEqual(json.loads((self.proj / "results" / "prs.json").read_text()), {p["branch"]: int(n) for n, p in self.prs().items()})

    def test_every_task_done_pushes_every_layer_and_maps_each_to_its_pr(self):
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertFalse(any("stack  hold" in l for l in out))
        self.assertEqual(json.loads((self.proj / "results" / "prs.json").read_text()), {f"compose/p-layer-0{i}": i for i in (1, 2, 3)})

    def test_a_task_done_on_linear_is_not_held_whatever_its_result(self):
        self.result("002", "failed")
        tasks = json.loads((self.proj / "results" / "tasks.json").read_text())
        tasks["tasks"][1]["linear_state"] = "Done"
        (self.proj / "results" / "tasks.json").write_text(json.dumps(tasks))
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue({"002.src", "003.src"} <= self.pushed()[1])
        self.assertTrue((self.proj / "results" / "prs.json").exists())

    def test_a_pending_first_task_stops_with_nothing_pushed(self):
        (self.proj / "results" / "001.json").unlink()
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertTrue(any("stack  STOP  nothing to submit: 001 is pending" in l for l in out), out)
        self.assertEqual(self.pushed()[0], {})
        self.assertFalse(any("stack submit" in c for c in self.log()))


class PartialLand(Ship):
    def partial(self):
        """Submitted, then layer 3 loses its PR and its branch on origin."""
        self.assertEqual(self.submit()[1], 0)
        self.drop_pr(3)
        subprocess.run(["git", "--git-dir", str(self.origin), "update-ref", "-d", "refs/heads/compose/p-layer-03"], check=True)

    def drop_pr(self, n):
        st = json.loads(self.state.read_text()); del st["prs"][str(n)]; self.state.write_text(json.dumps(st))

    def test_the_plan_lists_only_the_submitted_layers(self):
        self.partial()
        out, code = self.land(yes=False)
        self.assertEqual(code, 0, out)
        self.assertIn("land   plan  2 of 3 layer(s) submitted, verify not run; landing 2 into main by squash, bottom up:", out)
        self.assertTrue(any("compose/p-layer-02" in l for l in out))
        self.assertFalse(any("compose/p-layer-03" in l for l in out))
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))

    def test_yes_merges_the_submitted_layers_bottom_up_and_leaves_the_rest(self):
        self.partial()
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual([c for c in self.log() if c.startswith("pr merge")], ["pr merge 1 --squash", "pr merge 2 --squash"])
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-03"))
        self.assertEqual(out[-3:], ["land   done  2 layer(s) merged into main",
                                    "land   left  1 layer(s) not submitted: they rebuild on main at the next compose stack",
                                    "next: compose stack --submit --project p"])

    def test_the_plan_reports_the_last_verify(self):
        self.submit()
        for passed, word in ((True, "PASS"), (False, "FAIL")):
            (self.proj / "results" / "verify.json").write_text(json.dumps({"passed": passed}))
            out, _ = self.land(yes=False)
            self.assertIn(f"land   plan  3 of 3 layer(s) submitted, verify {word}; landing 3 into main by squash, bottom up:", out)

    def test_a_fully_submitted_stack_lands_as_today(self):
        self.submit()
        out, code = self.land()
        self.assertEqual(code, 0, out)
        self.assertEqual(out[-2:], ["land   done  3 layer(s) merged into main", "next: compose clean --project p"])
        self.assertFalse(any("land   left" in l for l in out))

    def test_a_bottom_layer_without_a_pull_request_stops(self):
        self.submit()
        self.drop_pr(1)
        out, code = self.land()
        self.assertEqual(code, 1)
        self.assertTrue(any(l.startswith("land   STOP  compose/p-layer-01") and l.endswith("has no pull request: `compose stack --submit` first") for l in out), out)
        self.assertFalse(any(c.startswith("pr merge") for c in self.log()))


class LandedLayers(Ship):
    def merge(self, n):
        subprocess.run(["gh", "pr", "edit", str(n), "--base", "main"], cwd=self.repo, check=True)
        subprocess.run(["gh", "pr", "merge", str(n), "--squash"], cwd=self.repo, check=True)

    def tree(self, ref):
        return self.git("ls-tree", "-r", "--name-only", ref).splitlines()

    def assert_built_on_main(self, branch, file, below="main"):
        self.assertIn(file, self.tree(branch))
        self.assertTrue(self.git("rev-list", f"{below}..{branch}"), f"{branch} adds nothing over {below}")
        self.assertEqual(subprocess.run(["git", "merge-base", "--is-ancestor", "main", branch], cwd=self.repo).returncode, 0)

    def test_the_layers_above_a_merged_bottom_build_on_the_new_base(self):
        self.submit(); self.merge(1)
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertEqual(code, 0, out)
        self.assertIn("stack  landed compose/p-layer-01; building on origin/main", out)
        self.assertFalse(any("STOP" in l for l in out), out)
        self.assertIn("stack  ok    (main) <- compose/p-layer-02 <- compose/p-layer-03", out)
        self.assertEqual(self.git("rev-parse", "main"), self.git("--git-dir", str(self.origin), "rev-parse", "main"))
        self.assert_built_on_main("compose/p-layer-02", "002.src")
        self.assert_built_on_main("compose/p-layer-03", "003.src", "compose/p-layer-02")

    def test_two_merged_layers_are_both_named_and_the_last_one_builds_on_the_base(self):
        self.submit(); self.merge(1); self.merge(2)
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertEqual(code, 0, out)
        self.assertIn("stack  landed compose/p-layer-01, compose/p-layer-02; building on origin/main", out)
        self.assertIn("stack  ok    (main) <- compose/p-layer-03", out)
        self.assert_built_on_main("compose/p-layer-03", "003.src")

    def test_open_pull_requests_or_no_layers_file_fetch_nothing(self):
        self.submit()
        old = self.git("rev-parse", "main")
        self.git("checkout", "-q", "main"); self.write("base.txt", "b\n"); self.commit("Move the base"); self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "compose/p"); self.git("branch", "-f", "main", old)
        for _ in range(2):
            out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
            self.assertFalse(any("landed" in l for l in out), out)
            self.assertEqual(self.git("rev-parse", "main"), old)
            (self.proj / "layers.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
