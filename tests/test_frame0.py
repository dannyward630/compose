import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Frame0(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.wt = Path(tempfile.mkdtemp()).resolve()
        self.proj = self.wt / ".compose" / "shop"
        self.proj.mkdir(parents=True)

    def register(self, existing):
        (self.home / ".claude.json").write_text(json.dumps({"projects": {str(self.wt): {"mcpServers": existing}}}))
        with mock.patch.object(Path, "home", return_value=self.home), mock.patch.object(fc.fc_core, "sh") as sh:
            fc.fc_frame0.frame0_register(self.wt, 58411)
        return [c.args[0] for c in sh.call_args_list if c.args[0][0] == "claude"]

    def test_port_is_stable_per_project_and_in_range(self):
        other = self.wt / ".compose" / "cart"
        self.assertEqual(fc.fc_frame0.frame0_port(self.proj), fc.fc_frame0.frame0_port(self.proj))
        self.assertIn(fc.fc_frame0.frame0_port(self.proj), fc.fc_frame0.FRAME0_PORTS)
        self.assertNotEqual(fc.fc_frame0.frame0_port(self.proj), fc.fc_frame0.frame0_port(other))

    def test_register_adds_replaces_or_leaves_the_local_server(self):
        add = ["claude", "mcp", "add", "-s", "local", "frame0", "--", "npx", "-y", "frame0-mcp-server", "--api-port=58411"]
        self.assertEqual(self.register({}), [add])
        stale = {"frame0": {"command": "npx", "args": ["-y", "frame0-mcp-server", "--api-port=58320"]}}
        self.assertEqual(self.register(stale), [["claude", "mcp", "remove", "frame0", "-s", "local"], add])
        same = {"frame0": {"command": "npx", "args": ["-y", "frame0-mcp-server", "--api-port=58411"]}}
        self.assertEqual(self.register(same), [])

    def test_register_finds_the_entry_claude_keeps_under_the_main_checkout(self):
        main = Path(tempfile.mkdtemp()).resolve()
        stale = {"frame0": {"command": "npx", "args": ["-y", "frame0-mcp-server", "--api-port=58320"]}}
        (self.home / ".claude.json").write_text(json.dumps({"projects": {str(main): {"mcpServers": stale}}}))
        with mock.patch.object(Path, "home", return_value=self.home), mock.patch.object(fc.fc_core, "worktrees", return_value=[main, self.wt]), \
                mock.patch.object(fc.fc_core, "sh") as sh:
            fc.fc_frame0.frame0_register(self.wt, 58411)
        self.assertEqual([c.args[0] for c in sh.call_args_list if c.args[0][0] == "claude"][0], ["claude", "mcp", "remove", "frame0", "-s", "local"])

    def test_up_still_launches_the_app_when_registering_fails(self):
        app = self.wt / "Frame0.app"
        app.mkdir()
        with mock.patch.object(fc.fc_frame0, "FRAME0_APP", app), mock.patch.object(fc.fc_frame0, "frame0_register", side_effect=RuntimeError("boom")), \
                mock.patch.object(fc.fc_frame0, "frame0_pid", return_value=None), mock.patch.object(fc.fc_core, "port_listening", side_effect=[False, True]), \
                mock.patch.object(fc.fc_core, "sh") as sh, mock.patch("builtins.print"):
            self.assertEqual(fc.fc_frame0.frame0_up(self.proj), (fc.fc_frame0.frame0_port(self.proj), True))
        self.assertEqual(sh.call_args.args[0][:2], ["open", "-n"])

    def test_pid_is_the_main_process_of_this_projects_instance(self):
        app = fc.fc_frame0.FRAME0_APP / "Contents" / "MacOS" / "Frame0"
        flag = f"--user-data-dir={self.proj / 'frame0'}"
        ps = "\n".join([f"  101 {app} --user-data-dir=/elsewhere/frame0",
                        f"  202 {fc.fc_frame0.FRAME0_APP}/Contents/Frameworks/Frame0 Helper.app/Contents/MacOS/Frame0 Helper --type=gpu {flag}",
                        f"  303 {app} {flag}"])
        with mock.patch.object(fc.fc_core, "sh", return_value=mock.Mock(stdout=ps)):
            self.assertEqual(fc.fc_frame0.frame0_pid(self.proj), 303)
        with mock.patch.object(fc.fc_core, "sh", return_value=mock.Mock(stdout=ps.rsplit("\n", 1)[0])):
            self.assertIsNone(fc.fc_frame0.frame0_pid(self.proj))

    def test_save_and_down_do_nothing_without_an_instance(self):
        with mock.patch.object(fc.fc_frame0, "frame0_pid", return_value=None), mock.patch.object(fc.fc_frame0, "frame0_command") as cmd:
            self.assertFalse(fc.fc_frame0.frame0_save(self.proj))
            self.assertFalse(fc.fc_frame0.frame0_down(self.proj))
        cmd.assert_not_called()


if __name__ == "__main__":
    unittest.main()
