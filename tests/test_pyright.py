import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONFIG = {"include": ["bin"], "typeCheckingMode": "strict", "pythonVersion": "3.9", "pythonPlatform": "Darwin"}
COMMAND = "npx -y pyright@1.1.414 --pythonpath /usr/bin/python3"
LINE = f"Type-check the CLI with `{COMMAND}` (strict; the error count is reported, nothing is gated on it)."
TESTS_LINE = "Run the CLI tests with `python3 -m unittest discover -s tests`."


def development():
    lines = (ROOT / "README.md").read_text().splitlines()
    start = lines.index("## Development") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


class PyrightConfig(unittest.TestCase):
    def test_config_is_exactly_the_strict_bin_config(self):
        path = ROOT / "pyrightconfig.json"
        self.assertTrue(path.exists(), "pyrightconfig.json must exist at the repo root")
        self.assertEqual(json.loads(path.read_text()), CONFIG)

    def test_readme_command_follows_the_unittest_line(self):
        section = development()
        starts = [i for i, line in enumerate(section) if line.startswith("Run the CLI tests with")]
        self.assertEqual(len(starts), 1, "one unittest line in Development")
        i = starts[0]
        self.assertLess(i + 1, len(section), "a line must follow the unittest line in Development")
        self.assertIn(COMMAND, section[i + 1])
        self.assertEqual(section[i + 1], LINE)

    def test_unittest_line_is_unchanged(self):
        self.assertIn(TESTS_LINE, development())

    def test_command_appears_once_in_readme(self):
        text = (ROOT / "README.md").read_text()
        self.assertEqual(text.count("pyright@"), 1, "the pyright command is stated once, in Development")


if __name__ == "__main__":
    unittest.main()
