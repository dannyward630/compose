import hermetic  # first: no test sees the real home
import os, tempfile, unittest
from pathlib import Path
from ship_kit import Ship, fc
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""


class LayerChecks(Ship):
    def test_a_failing_layer_refuses_the_submit_and_is_named_with_nothing_pushed(self):
        self.config(checks=["! test -f 002.src"])  # layer 1 holds the setup files and passes; layer 2 has 002.src
        out, code = self.submit()
        self.assertEqual(code, 1)
        stop = [l for l in out if "STOP" in l]
        self.assertEqual(len(stop), 1)
        self.assertIn("layer 2 of 3 (compose/p-layer-02) fails `! test -f 002.src` on its own tree", stop[0])
        self.assertIn("Nothing was pushed", stop[0])
        self.assertTrue(any("layers ok" in l and "compose/p-layer-01" in l for l in out))
        self.assertFalse(any("stack submit" in c for c in self.log()))
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-01"))
        self.assertFalse((self.proj / "layers.json").exists())

    def test_every_layer_runs_the_checks_once_and_an_unchanged_layer_is_not_run_again(self):
        counter = Path(tempfile.mkdtemp()) / "runs"
        self.config(checks=[f"echo run >> {counter}"])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(counter.read_text().splitlines()), 3)
        self.assertTrue(any("stack submit --auto" in c for c in self.log()))
        self.assertTrue(self.origin_has("refs/heads/compose/p-layer-03"))
        out, code = self.submit()
        self.assertEqual(len(counter.read_text().splitlines()), 3)
        self.assertEqual(len([l for l in out if "unchanged since its checks passed" in l]), 3)
        self.config(checks=[f"echo run >> {counter}", "true"])  # other checks: every layer is checked again
        self.submit()
        self.assertEqual(len(counter.read_text().splitlines()), 6)

    def test_a_layer_is_checked_on_its_own_tree_not_the_top(self):
        self.config(checks=["test -f 003.src"])  # only the top layer has it
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn("layer 1 of 3 (compose/p-layer-01) fails `test -f 003.src`", "\n".join(out))

    def test_a_stack_preview_and_a_project_without_checks_run_none(self):
        counter = Path(tempfile.mkdtemp()) / "runs"
        self.config(checks=[f"echo run >> {counter}"])
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertFalse(counter.exists())
        self.config()
        out, code = self.submit()
        self.assertEqual(code, 0)
        self.assertTrue(any("no checks in verify.json" in l for l in out))
        self.assertTrue(any("stack submit --auto" in c for c in self.log()))


class Reword(Ship):
    def test_a_commit_message_that_names_the_process_is_fixed_when_the_layer_is_built(self):
        self.git("checkout", "-q", "compose/p-001")
        self.git("commit", "-q", "--amend", "-m", "task 001: wire compose verify\n\nDone by the implementer.\nIndex the title.")
        self.git("checkout", "-q", "compose/p")
        out, code = self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertEqual(code, 0)
        self.assertIn("Update 001.src", self.subjects("compose/p-layer-02"))
        self.assertNotIn("task 001: wire compose verify", self.subjects("compose/p-layer-02"))
        self.assertTrue(any("stack  note" in l and "wire compose verify" in l and "mentions the process (`task 001`)" in l for l in out))
        self.assertEqual(self.git("log", "-1", "--format=%s", "compose/p-001"), "task 001: wire compose verify")  # the task branch is left alone
        body = self.git("log", "--format=%B", "--grep=^Update 001.src", "compose/p-layer-02")
        self.assertIn("Index the title.", body)
        self.assertNotIn("implementer", body)

    def test_reword_lists_the_layer_commits_and_flags_the_ones_that_break_the_rules(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.config(commit_convention={"types": ["feat", "fix"], "example": "feat: x"})
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=None, as_is=False)
        self.assertEqual(code, 0)
        listed = [l for l in out if l.startswith("  ")]
        self.assertEqual(len(listed), 7)  # setup, three tests, three tasks
        self.assertTrue(all("no type prefix" in l for l in listed))
        self.assertFalse(self.prs())

    def test_set_rewords_one_commit_keeps_the_trees_and_never_pushes(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        tips = {b: self.git("rev-parse", b) for b in ("compose/p-layer-01", "compose/p-layer-02", "compose/p-layer-03")}
        sha = self.git("log", "-1", "--format=%H", "--grep=^Build 001", "compose/p-layer-02")
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha[:8]}=Add the first thing\n\nIt reads the file."], as_is=False)
        self.assertEqual(code, 0, out)
        self.assertIn("Add the first thing", self.subjects("compose/p-layer-02"))
        self.assertNotIn("Build 001", self.subjects("compose/p-layer-02"))
        for b, tip in tips.items():
            self.assertEqual(self.git("rev-parse", f"{b}^{{tree}}"), self.git("rev-parse", f"{tip}^{{tree}}"))
        self.assertEqual(self.git("rev-parse", "compose/p-layer-01"), tips["compose/p-layer-01"])  # a layer below the change is untouched
        self.assertEqual(self.subjects("compose/p-layer-03")[0], "Build 003")
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-02"))
        self.assertFalse(any(c.startswith(("pr ", "stack submit", "stack push")) for c in self.log()))
        self.assertTrue(any("nothing pushed" in l for l in out))
        # the choice lives on the commit: any later rebuild applies it again
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        self.assertIn("Add the first thing", self.subjects("compose/p-layer-02"))

    def test_a_message_that_breaks_the_rules_is_refused_unless_taken_as_is(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        sha = self.git("log", "-1", "--format=%H", "--grep=^Build 001", "compose/p-layer-02")
        before = self.git("rev-parse", "compose/p-layer-02")
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha[:8]}=Wave 2 of compose run"], as_is=False)
        self.assertEqual(code, 1)
        self.assertTrue(any("mentions the process" in l for l in out))
        self.assertFalse((self.proj / "rewords.json").exists())
        self.assertEqual(self.git("rev-parse", "compose/p-layer-02"), before)
        out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha[:8]}=Wave 2 of compose run"], as_is=True)
        self.assertEqual(code, 0)
        self.assertIn("Wave 2 of compose run", self.git("log", "--format=%s", "main..compose/p-layer-02"))

    def test_a_sha_that_names_no_commit_or_several_is_refused(self):
        self.run_cmd(fc.fc_ship.cmd_stack, submit=False)
        for sha in ("deadbeef", ""):
            out, code = self.run_cmd(fc.fc_ship.cmd_reword, set=[f"{sha}=Add it"], as_is=False)
            self.assertEqual(code, 1)
            self.assertTrue(any("names 0 commits" in l for l in out), out)


if __name__ == "__main__":
    unittest.main()
