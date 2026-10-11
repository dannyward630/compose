import importlib.machinery, importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class Frame0(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp()).resolve()
        self.proj = self.wt / ".fast-coding" / "shop"
        self.proj.mkdir(parents=True)

    def register(self, existing):
        (self.home / ".claude.json").write_text(json.dumps({"projects": {str(self.wt): {"mcpServers": existing}}}))
        with mock.patch.object(fc.Path, "home", return_value=self.home), mock.patch.object(fc, "sh") as sh:
            fc.frame0_register(self.wt, 58411)
        return [c.args[0] for c in sh.call_args_list]

    def test_port_is_stable_per_project_and_in_range(self):
        other = self.wt / ".fast-coding" / "cart"
        self.assertEqual(fc.frame0_port(self.proj), fc.frame0_port(self.proj))
        self.assertIn(fc.frame0_port(self.proj), fc.FRAME0_PORTS)
        self.assertNotEqual(fc.frame0_port(self.proj), fc.frame0_port(other))

    def test_register_adds_replaces_or_leaves_the_local_server(self):
        add = ["claude", "mcp", "add", "-s", "local", "frame0", "--", "npx", "-y", "frame0-mcp-server", "--api-port=58411"]
        self.assertEqual(self.register({}), [add])
        stale = {"frame0": {"command": "npx", "args": ["-y", "frame0-mcp-server", "--api-port=58320"]}}
        self.assertEqual(self.register(stale), [["claude", "mcp", "remove", "frame0", "-s", "local"], add])
        same = {"frame0": {"command": "npx", "args": ["-y", "frame0-mcp-server", "--api-port=58411"]}}
        self.assertEqual(self.register(same), [])

    def test_pid_is_the_main_process_of_this_projects_instance(self):
        app = fc.FRAME0_APP / "Contents" / "MacOS" / "Frame0"
        flag = f"--user-data-dir={self.proj / 'frame0'}"
        ps = "\n".join([f"  101 {app} --user-data-dir=/elsewhere/frame0",
                        f"  202 {fc.FRAME0_APP}/Contents/Frameworks/Frame0 Helper.app/Contents/MacOS/Frame0 Helper --type=gpu {flag}",
                        f"  303 {app} {flag}"])
        with mock.patch.object(fc, "sh", return_value=mock.Mock(stdout=ps)):
            self.assertEqual(fc.frame0_pid(self.proj), 303)
        with mock.patch.object(fc, "sh", return_value=mock.Mock(stdout=ps.rsplit("\n", 1)[0])):
            self.assertIsNone(fc.frame0_pid(self.proj))

    def test_save_and_down_do_nothing_without_an_instance(self):
        with mock.patch.object(fc, "frame0_pid", return_value=None), mock.patch.object(fc, "frame0_command") as cmd:
            self.assertFalse(fc.frame0_save(self.proj))
            self.assertFalse(fc.frame0_down(self.proj))
        cmd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
