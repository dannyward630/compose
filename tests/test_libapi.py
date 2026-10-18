import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class PythonApi(unittest.TestCase):
    """Task 010 (NEB-929): python_api and section for Python imports."""

    WORDS = "Goal: spin the gadget.\ng = Gadget(); g.spin(3)  # a stopwatch, _hidden"
    FILES = ["app/main.py", "app/other.py", "app/new.py"]

    @classmethod
    def setUpClass(cls):
        root = cls.root = Path(tempfile.mkdtemp()).resolve()
        wt = cls.wt = root / "wt"
        cls.addClassCleanup(shutil.rmtree, root, True)
        subprocess.run(["python3", "-m", "venv", "--without-pip", str(wt / ".venv")], check=True)
        cls.py = str(wt / ".venv" / "bin" / "python")
        purelib = "import sysconfig; print(sysconfig.get_paths()['purelib'])"
        site = Path(subprocess.run([cls.py, "-c", purelib], check=True, capture_output=True, text=True).stdout.strip())
        for dist, ver, mod in (("tool-kit", "1.2.3", "toolkit"), ("myrepo", "0.1", "localmod")):  # myrepo: the repo, installed editable
            info = site / f"{dist.replace('-', '_')}-{ver}.dist-info"
            info.mkdir()
            (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: {ver}\n")
            (info / "top_level.txt").write_text(mod + "\n")
        (site / "myrepo.pth").write_text(str(wt) + "\n")
        (site / "toolkit").mkdir()
        (site / "toolkit" / "__init__.py").write_text(
            'def shout(text, times=2):\n    """Say it loud.\n\n    More."""\n\n\nclass Gadget:\n    """A gadget."""\n\n'
            '    def spin(self, speed):\n        """Spin it."""\n\n    def stop(self):\n        """Stop it."""\n\n'
            '    def _hidden(self):\n        """Hide it."""\n')
        files = {"wt/localmod.py": "def thing(x):\n    'Repo code.'\n", "wt/app/other.py": "from toolkit import shout\n",
                 "wt/app/main.py": "import json, os\nfrom toolkit import shout, Gadget, missing\nimport absent_pkg\nfrom localmod import thing\nfrom . import rel\n",
                 "wt/broken/main.py": "from toolkit import shout\n", "wt/broken/.venv/bin/python": "#!/bin/sh\nexit 3\n",
                 "bare/app/main.py": "from toolkit import Gadget\n", "bare/app/other.py": "from toolkit import shout\n",
                 "bin/python3": f'#!/bin/sh\necho run >> {root}/runs\nexec {cls.py} "$@"\n'}
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
            (root / rel).chmod(0o755)

    def test_a_block_per_distribution_with_its_version_names_and_the_methods_words_name(self):
        blocks = fc.fc_libapi.python_api(self.wt, self.FILES, self.WORDS)
        self.assertEqual(len(blocks), 1, blocks)
        lines = blocks[0].split("\n")
        self.assertEqual((lines[0], len(lines)), ("tool-kit 1.2.3", 4), blocks)
        shout, gadget, spin = ([i for i, l in enumerate(lines) if all(w in l for w in ws)] for ws in
                               (("shout(text, times=2)", "Say it loud."), ("Gadget", "A gadget."), ("spin(", "speed", "Spin it.")))
        self.assertTrue(len(shout) == len(gadget) == len(spin) == 1 and spin[0] > max(shout[0], gadget[0]), blocks)
        self.assertNotIn("More.", blocks[0])

    def test_python3_runs_once_without_a_venv_and_a_failing_interpreter_gives_nothing(self):
        with mock.patch.dict(os.environ, {"PATH": f"{self.root / 'bin'}:{os.environ['PATH']}"}):
            blocks = fc.fc_libapi.python_api(self.root / "bare", self.FILES, self.WORDS)
        self.assertEqual([b.split("\n")[0] for b in blocks], ["tool-kit 1.2.3"])
        self.assertEqual((self.root / "runs").read_text(), "run\n")
        self.assertEqual(fc.fc_libapi.python_api(self.wt, ["broken/main.py"], self.WORDS), [])
        self.assertEqual(fc.fc_libapi.section(self.wt, ["broken/main.py", "app/new.py"], self.WORDS), "")

    def test_section_has_a_header_fits_the_cap_and_ends_on_a_whole_line(self):
        full = fc.fc_libapi.section(self.wt, self.FILES, self.WORDS, cap=10 ** 6)
        self.assertTrue(full.startswith("LIBRARY API") and fc.fc_libapi.python_api(self.wt, self.FILES, self.WORDS)[0] in full, full)
        self.assertEqual(fc.fc_libapi.section(self.wt, self.FILES, self.WORDS), full)
        lines = full.rstrip("\n").split("\n")
        cap = len("\n".join(lines[:-1])) + 3
        cut = fc.fc_libapi.section(self.wt, self.FILES, self.WORDS, cap=cap)
        self.assertEqual((cut.rstrip("\n"), len(cut) <= cap), ("\n".join(lines[:-1]), True), cut)


class JsApi(unittest.TestCase):
    """Task 011 (NEB-931): js_api and section for JS/TS imports."""


if __name__ == "__main__":
    unittest.main()
