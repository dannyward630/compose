import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text()


class CliAndTasksDocs(unittest.TestCase):
    pass


class HerdrAndWorkspacesDocs(unittest.TestCase):
    pass


class SkillDoc(unittest.TestCase):
    pass


class DesignerCommand(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
