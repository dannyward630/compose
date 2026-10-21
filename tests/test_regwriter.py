import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_regwriter  # noqa: E402


BODY = "## Goal\nFix it.\n\n## Acceptance criteria\n\n* a\n* b\n\n## Test plan\nRun it.\n"
REPRO = "## Reproduction\n\nrun x\nsee y\n\n## Constraints\nnone"
FENCE = "`" * 3


class Brief(unittest.TestCase):
    """The regression test writer's branch and brief."""

    def brief(self, body, diff="diff --git a/x b/x\n+fix"):
        return fc_regwriter.writer_brief({"id": "007", "title": "Fix the thing", "body": body}, diff)

    def test_branch_is_task_prefix_plus_regress_id(self):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "p"
        proj.mkdir(parents=True)
        (proj / "verify.json").write_text(json.dumps({"task_prefix": "fast/p/"}))
        self.assertEqual(fc_regwriter.writer_branch(proj, "007"), "fast/p/regress-007")

    def test_starts_with_four_lines_then_criteria_when_no_reproduction(self):
        self.assertTrue(self.brief(BODY).startswith(
            "Write one regression test for task 007: Fix the thing.\n"
            "The fix below passed. Your test must fail on the base and pass on the fix.\n"
            "Change only test files, in one commit; never edit the fix.\n"
            'Then report working "test ready: <commit> <command>", where <command> runs only your test.\n'
            "\n## Expected behavior\n* a\n* b\n\n## The fix\n"))

    def test_reproduction_wins_over_criteria(self):
        text = self.brief(BODY + "\n" + REPRO)
        self.assertIn("## Expected behavior\nrun x\nsee y\n\n## The fix\n", text)
        self.assertNotIn("* a", text)

    def test_section_runs_to_end_and_ends_at_next_level_two_heading_only(self):
        text = self.brief("## Acceptance criteria\n### sub\n* a\n\n## Z\nz")
        self.assertIn("## Expected behavior\n### sub\n* a\n\n## The fix", text)
        self.assertIn("## Expected behavior\nlast\n\n## The fix", self.brief("## Reproduction\n\nlast\n\n"))

    def test_ends_with_diff_in_fence(self):
        self.assertTrue(self.brief(BODY, "-a\n+b").endswith(f"## The fix\n{FENCE}diff\n-a\n+b\n{FENCE}"))


class Writer(unittest.TestCase):
    """The regression test writer starts on its own branch and checkout off the task's tip."""


class Ready(unittest.TestCase):
    """run waits for the writer's ready line, and stops waiting when the writer ends without one."""
