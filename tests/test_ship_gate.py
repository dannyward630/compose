import hermetic  # first: no test sees the real home
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
from ship_kit import Ship, fc
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

OLD = "FAIL: gone_test (legacy.Old.gone_test)"  # a failing test that names a file no tree has
NEW = "FAIL: new_test (pkg.Case.new_test)"


def fail(*lines, when="true"):
    """A check that prints `lines` on stderr and exits 1, where the shell test `when` holds."""
    return f"if {when}; then " + "; ".join(f"echo '{l}' >&2" for l in lines) + "; exit 1; fi"


class Gate(Ship):
    def setUp(self):
        super().setUp()
        self.counter = Path(tempfile.mkdtemp()) / "runs"

    def tests(self, **by_id):
        """The `test` of the tasks, by id."""
        path = self.proj / "results" / "tasks.json"
        d = json.loads(path.read_text())
        for t in d["tasks"]:
            t["test"] = by_id.get(t["id"], t["test"])
        path.write_text(json.dumps(d))

    def ran(self):
        return self.counter.read_text().splitlines() if self.counter.exists() else []

    def stop(self, out):
        return "\n".join(l for l in out if "STOP" in l)

    def memo(self):
        return json.loads((self.proj / "results" / "layer-checks.json").read_text())


class LayerScope(Gate):
    def test_each_layer_runs_its_tasks_tests_and_the_top_layer_every_check_where_a_lower_one_runs_the_cheap_ones(self):
        suite, cheap = f": unittest; echo suite >> {self.counter}", f"echo cheap >> {self.counter}"
        self.tests(**{t: f"echo test{t} >> {self.counter}" for t in ("001", "002", "003")})
        self.config(checks=[suite, cheap])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.ran().count("suite"), 1)  # once, on the top layer
        self.assertEqual(self.ran().count("cheap"), 3)
        self.assertEqual(sorted(l for l in self.ran() if l.startswith("test")), ["test001", "test002", "test003"])
        scope = [l for l in out if l.startswith("layers scope")]
        self.assertEqual(len(scope), 3)
        self.assertIn("layer 3 of 3 (compose/p-layer-03)  its tasks' tests and every check", scope[2])
        self.assertTrue(all("its tasks' tests and the cheap checks" in l and "unittest" not in l for l in scope[:2]), scope)
        self.assertTrue(any("layers ok" in l and "every check on the top" in l for l in out))
        self.assertTrue(any("stack submit --auto" in c for c in self.log()))

    def test_a_suite_only_the_top_layer_satisfies_does_not_refuse_the_lower_layers(self):
        self.config(checks=["test -f 003.src # unittest"])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue(self.origin_has("refs/heads/compose/p-layer-03"))

    def test_a_failing_suite_on_the_top_layer_is_refused_and_the_lower_layers_passed(self):
        self.config(checks=["test ! -f 003.src # unittest"])
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn("layer 3 of 3 (compose/p-layer-03) fails `test ! -f 003.src # unittest` on its own tree", self.stop(out))
        self.assertEqual(len([l for l in out if l.startswith("layers ok") and "layer " in l and "fails" not in l]), 2)
        self.assertFalse(any("stack submit" in c for c in self.log()))

    def test_a_layer_whose_own_task_test_fails_is_refused_and_named(self):
        self.tests(**{"002": "test -f 003.src"})  # 002's layer does not hold 003.src
        self.config(checks=["true # unittest"])
        out, code = self.submit()
        self.assertEqual(code, 1)
        stop = self.stop(out)
        self.assertIn("fails `test -f 003.src` on its own tree", stop)
        self.assertIn("layer 2 of 3 (compose/p-layer-02)", stop)
        self.assertIn("Nothing was pushed", stop)
        self.assertFalse(any("stack submit" in c for c in self.log()))

    def test_a_task_without_a_test_adds_no_command_and_a_command_runs_once_on_a_layer(self):
        self.tests(**{"001": "", "002": f"echo same >> {self.counter}", "003": f"echo same >> {self.counter}"})
        self.config(checks=[f"echo same >> {self.counter}"])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.ran()), 3)  # layers 1 to 3 each run `echo same` once, whether it is a check, a test, or both

    def test_a_layer_checked_once_is_not_checked_again_until_its_commands_change(self):
        self.config(checks=[f"echo cheap >> {self.counter}", f": unittest; echo suite >> {self.counter}"])
        self.submit()
        self.assertEqual(len(self.ran()), 4)  # three cheap, one suite
        out, code = self.submit()
        self.assertEqual(len(self.ran()), 4)
        self.assertEqual(len([l for l in out if "unchanged since its checks passed" in l]), 3)
        self.config(checks=[f"echo cheap >> {self.counter}", f": unittest; echo suite2 >> {self.counter}"])  # only the top layer's commands change
        out, code = self.submit()
        self.assertEqual(self.ran()[4:], ["suite2"])  # the top layer reruns only the changed command: `cheap` is green on its tree, so it is taken
        self.assertEqual(len([l for l in out if "not rerun" in l and "cheap" in l]), 1)
        self.assertEqual(len([l for l in out if "unchanged since its checks passed" in l]), 2)  # the lower layers are unchanged


class Based(Gate):
    """The base (main) holds README.md, stable.py and suite_old.py; the layers add the rest, and change suite_old.py when TOUCH."""
    TOUCH = False

    def write(self, name, text):
        super().write(name, text)
        if name == "README.md":
            super().write("suite_old.py", "import os\n")
            super().write("stable.py", "import os\n")
        if name == "setup.txt" and self.TOUCH:
            super().write("suite_old.py", "import os\nimport more\n")


class BaseFailures(Based):
    def test_a_failure_already_on_the_base_and_untouched_is_accepted_and_reported_by_id(self):
        self.config(checks=[f"echo run >> {self.counter}; echo '{OLD}' >&2; exit 1"])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        base = self.git("merge-base", "main", "compose/p-layer-03")[:9]
        said = [l for l in out if l.startswith("layers base")]
        self.assertEqual(len(said), 3)
        self.assertTrue(all("gone_test (legacy.Old.gone_test)" in l and f"fails on the base {base} too" in l and "accepted" in l for l in said), said)
        self.assertEqual(len(self.ran()), 4)  # three layers and the base, which runs the command once
        self.assertTrue(any("3 failing test(s) already red on the base accepted" in l for l in out))
        self.assertTrue(any("stack submit --auto" in c for c in self.log()))

    def test_a_layer_that_newly_breaks_a_test_green_on_the_base_is_refused(self):
        self.config(checks=[fail(NEW, when="test -f 002.src")])
        out, code = self.submit()
        self.assertEqual(code, 1)
        stop = self.stop(out)
        self.assertIn("layer 2 of 3 (compose/p-layer-02) fails", stop)
        self.assertIn("passes on the base", stop)
        self.assertIn("new_test (pkg.Case.new_test)", stop)
        self.assertNotIn("already fail on the base", stop)
        self.assertFalse(any("stack submit" in c for c in self.log()))
        self.assertFalse(self.origin_has("refs/heads/compose/p-layer-01"))
        self.assertFalse(any(l.startswith("layers base") for l in out))

    def test_a_new_failure_beside_an_old_one_is_refused_and_the_old_ones_are_counted(self):
        self.config(checks=[f"echo '{OLD}' >&2; " + fail(NEW, when="test -f 002.src") + "; exit 1"])
        out, code = self.submit()
        self.assertEqual(code, 1)
        stop = self.stop(out)
        self.assertIn("layer 2 of 3", stop)
        self.assertIn("fails here: new_test (pkg.Case.new_test)", stop)
        self.assertIn("1 more already fail on the base and are ignored", stop)
        self.assertNotIn("gone_test (legacy.Old.gone_test)", stop.split("passes on the base")[1].split("1 more")[0])

    def test_a_failure_that_names_no_test_is_refused_and_so_is_a_base_run_that_names_none(self):
        self.config(checks=["exit 1"])
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn("it names no failing test, so it cannot be compared with the base", self.stop(out))
        self.config(checks=[fail(OLD, when="test -f setup.txt") + "; exit 1"])  # the base fails with no id at all
        out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn("its run on the base", self.stop(out))
        self.assertIn("names no failing test", self.stop(out))
        self.assertIn(f"cannot tell whether {OLD[6:]} fail on the base too", self.stop(out))
        self.assertFalse(any("stack submit" in c for c in self.log()))

    def test_a_timeout_is_refused_as_before(self):
        self.config(checks=["exec sleep 5"])
        with mock.patch.object(fc.fc_gate, "CHECKS_TIMEOUT", 1):
            out, code = self.submit()
        self.assertEqual(code, 1)
        self.assertIn("layer 1 of 3 (compose/p-layer-01) fails `exec sleep 5` on its own tree:\ntimed out after 1s", self.stop(out))

    def test_a_layer_that_leaned_on_the_base_is_remembered_with_the_base_and_the_top(self):
        self.config(checks=[f"echo run >> {self.counter}; echo '{OLD}' >&2; exit 1"])
        self.submit()
        base, top = self.git("merge-base", "main", "compose/p-layer-03"), self.git("rev-parse", "compose/p-layer-03")
        kept = self.memo()
        self.assertEqual(len(kept), 3)
        self.assertTrue(all(v.endswith(f":{base}:{top}") for v in kept.values()), kept)
        runs = len(self.ran())
        out, code = self.submit()
        self.assertEqual(len(self.ran()), runs)
        self.assertEqual(len([l for l in out if "unchanged since its checks passed" in l]), 3)

    def test_a_clean_layer_is_remembered_by_its_tip_alone(self):
        self.config(checks=["true"])
        self.submit()
        self.assertTrue(all(v.count(":") == 1 for v in self.memo().values()), self.memo())


class BaseTouched(Based):
    TOUCH = True

    def test_a_failure_on_the_base_in_a_file_the_stack_changes_is_refused(self):
        self.config(checks=["echo 'FAIL: suite_old.py::old' >&2; exit 1"])
        out, code = self.submit()
        self.assertEqual(code, 1)
        stop = self.stop(out)
        self.assertIn("layer 1 of 3", stop)
        self.assertIn("fails on the base too, in what this stack changes: suite_old.py::old", stop)
        self.assertFalse(any("stack submit" in c for c in self.log()))

    def test_the_same_failure_in_a_file_the_stack_leaves_alone_is_accepted(self):
        self.config(checks=["echo 'FAIL: stable.py::old' >&2; exit 1"])
        out, code = self.submit()
        self.assertEqual(code, 0, out)
        self.assertTrue(any(l.startswith("layers base") and "stable.py::old" in l for l in out))


if __name__ == "__main__":
    unittest.main()
