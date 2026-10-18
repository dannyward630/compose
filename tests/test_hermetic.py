import hermetic  # first: no test sees the real home
import io, os, subprocess, tempfile, unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""


class HermeticCleanup(unittest.TestCase):
    """Every temp dir a test makes is gone when the test is: a suite run by many teammates at once must not fill the disk's temp folder."""

    def run_case(self, body):
        made = {}
        class Case(unittest.TestCase):
            def test_it(self):
                body(self, made)
        unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(Case))
        return made

    def test_a_tests_mkdtemp_dirs_are_removed_after_it(self):
        made = self.run_case(lambda case, made: made.update(a=tempfile.mkdtemp(), b=Path(tempfile.mkdtemp(prefix="x-")) / "sub"))
        self.assertEqual([k for k, d in made.items() if Path(d).exists()], [])

    def test_a_tests_temp_home_is_removed_after_it(self):
        made = self.run_case(lambda case, made: made.update(home=os.environ["HOME"]))
        self.assertTrue(made["home"].startswith(tempfile.gettempdir()) or "/compose-home-" in made["home"], made["home"])
        self.assertFalse(Path(made["home"]).exists(), made["home"])

    def test_the_dirs_of_a_test_survive_while_it_runs(self):
        def body(case, made):
            d = Path(tempfile.mkdtemp()); (d / "f").write_text("x")
            made["seen"] = (d / "f").read_text()
        self.assertEqual(self.run_case(body)["seen"], "x")

    def test_stubs_with_the_same_body_share_one_executable(self):
        """macOS scans every new executable file on its first run (about 150 ms of XprotectService each); a stub body
        seen before is linked to the file already scanned instead of being a new file."""
        def body(case, made):
            for n in ("a", "b"):
                d = Path(tempfile.mkdtemp()); (d / "gh").write_text("#!/bin/sh\necho 1.0.0\n"); (d / "gh").chmod(0o755)
                made[n] = d / "gh"
            made["out"] = subprocess.run([str(made["a"])], capture_output=True, text=True).stdout
            made["links"] = (made["a"].is_symlink(), made["b"].is_symlink())
            made["same"] = made["a"].resolve() == made["b"].resolve()
        made = self.run_case(body)
        self.assertEqual((made["out"], made["links"], made["same"]), ("1.0.0\n", (True, True), True))

    def test_stubs_with_different_bodies_are_different_executables(self):
        def body(case, made):
            for n, text in (("a", "#!/bin/sh\necho a\n"), ("b", "#!/bin/sh\necho b\n")):
                d = Path(tempfile.mkdtemp()); (d / "t").write_text(text); (d / "t").chmod(0o755)
                made[n] = subprocess.run([str(d / "t")], capture_output=True, text=True).stdout
        self.assertEqual(self.run_case(body), {"a": "a\n", "b": "b\n"})

    def test_a_stub_made_non_executable_again_is_its_own_file(self):
        def body(case, made):
            d = Path(tempfile.mkdtemp()); f = d / "gh"; f.write_text("#!/bin/sh\necho 1.0.0\n"); f.chmod(0o755)
            g = Path(tempfile.mkdtemp()) / "gh"; g.write_text("#!/bin/sh\necho 1.0.0\n"); g.chmod(0o755)
            f.chmod(0o644)
            made["f_exec"], made["g_exec"] = os.access(f, os.X_OK), os.access(g, os.X_OK)
            made["f_link"] = f.is_symlink()
        self.assertEqual(self.run_case(body), {"f_exec": False, "g_exec": True, "f_link": False})

    def test_a_stub_rewritten_in_place_runs_its_new_body_and_leaves_its_twin(self):
        def body(case, made):
            f = Path(tempfile.mkdtemp()) / "gh"; f.write_text("#!/bin/sh\necho 1.0.0\n"); f.chmod(0o755)
            g = Path(tempfile.mkdtemp()) / "gh"; g.write_text("#!/bin/sh\necho 1.0.0\n"); g.chmod(0o755)
            f.write_text("#!/bin/sh\necho 2.0.0\n")  # no chmod again: it stays executable
            made["f"], made["g"] = subprocess.run([str(f)], capture_output=True, text=True).stdout, g.read_text()
            h = Path(tempfile.mkdtemp()) / "gh"; h.write_text("#!/bin/sh\necho 1.0.0\n"); h.chmod(0o755)
            made["h"] = subprocess.run([str(h)], capture_output=True, text=True).stdout
        self.assertEqual(self.run_case(body), {"f": "2.0.0\n", "g": "#!/bin/sh\necho 1.0.0\n", "h": "1.0.0\n"})


if __name__ == "__main__":
    unittest.main()
