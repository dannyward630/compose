import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, sys, unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


def task(**kv):
    kv = {"id": "001", "test": "t", **kv}
    desc = "## Goal\nDo it.\n\n```compose\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"
    return fc.fc_tasks.task_from_issue({"id": "NEB-1", "title": "T", "description": desc})


class TaskTier(unittest.TestCase):
    def test_each_of_the_four_tiers_is_kept(self):
        for tier in ("cheap", "standard", "frontier", "no-frontier"):
            with self.subTest(tier=tier):
                self.assertEqual(task(tier=tier)["tier"], tier)

    def test_a_block_without_a_tier_has_no_tier_key(self):
        self.assertNotIn("tier", task())

    def test_an_unknown_tier_exits_naming_the_issue_and_the_value(self):
        for bad in ("huge", "Frontier", "cheap,standard"):
            with self.subTest(tier=bad), self.assertRaises(SystemExit) as e:
                task(tier=bad)
            self.assertEqual(str(e.exception), f"NEB-1: tier must be cheap, standard, frontier or no-frontier, not {bad}")

    def test_a_tier_does_not_change_the_other_keys(self):
        meta = task(tier="cheap", files="a.py, b.py", kind="code")
        self.assertEqual((meta["id"], meta["test"], meta["files"], meta["kind"], meta["linear"]), ("001", "t", ["a.py", "b.py"], "code", "NEB-1"))


class ModelAuto(unittest.TestCase):
    def test_a_block_without_model_gets_the_default_and_model_auto(self):
        meta = task()
        self.assertEqual(meta["model"], fc.fc_config.DEFAULT_MODEL)
        self.assertIs(meta["model_auto"], True)

    def test_a_block_with_model_keeps_it_and_has_no_model_auto(self):
        meta = task(model="pi:a/b")
        self.assertEqual(meta["model"], "pi:a/b")
        self.assertNotIn("model_auto", meta)

    def test_a_tier_and_a_model_together_keep_the_model_without_model_auto(self):
        meta = task(tier="frontier", model="pi:a/b")
        self.assertEqual((meta["tier"], meta["model"]), ("frontier", "pi:a/b"))
        self.assertNotIn("model_auto", meta)

    def test_a_tier_without_a_model_still_gets_model_auto(self):
        self.assertIs(task(tier="cheap")["model_auto"], True)


if __name__ == "__main__":
    unittest.main()
