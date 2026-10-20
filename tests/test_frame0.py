import hermetic  # first: no test sees the real home
import http.server, importlib.machinery, importlib.util, json, os, subprocess, tempfile, threading, unittest, urllib.request
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
        add = ["claude", "mcp", "add", "-s", "local", "frame0", "--", "compose", "frame0", "mcp", "--api-port=58411"]
        remove = ["claude", "mcp", "remove", "frame0", "-s", "local"]
        self.assertEqual(self.register({}), [add])
        stale = {"frame0": {"command": "compose", "args": ["frame0", "mcp", "--api-port=58320"]}}
        self.assertEqual(self.register(stale), [remove, add])
        bare = {"frame0": {"command": "npx", "args": ["-y", "frame0-mcp-server", "--api-port=58411"]}}  # registered before the proxy
        self.assertEqual(self.register(bare), [remove, add])
        same = {"frame0": {"command": "compose", "args": ["frame0", "mcp", "--api-port=58411"]}}
        self.assertEqual(self.register(same), [])

    def test_register_finds_the_entry_claude_keeps_under_the_main_checkout(self):
        main = Path(tempfile.mkdtemp()).resolve()
        stale = {"frame0": {"command": "compose", "args": ["frame0", "mcp", "--api-port=58320"]}}
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

    def test_an_app_that_stays_silent_or_is_gone_says_what_to_check(self):
        with mock.patch.object(fc.fc_frame0.urllib.request, "urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "dialog is probably open"):
                fc.fc_frame0.frame0_command(58411, "file:save")
        with mock.patch.object(fc.fc_frame0.urllib.request, "urlopen", side_effect=fc.fc_frame0.urllib.error.URLError(ConnectionRefusedError())):
            with self.assertRaisesRegex(RuntimeError, "not listening on port 58411"):
                fc.fc_frame0.frame0_command(58411, "file:save")


class FakeApp(http.server.BaseHTTPRequestHandler):
    """Frame0's API: tokens live in the class, as they live in the app process, and a new app starts with none."""
    valid, issued, calls = set(), [], []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/request_api_token":
            token = f"token{len(self.issued)}"
            self.issued.append(token), self.valid.add(token)
            status, out = 200, {"success": True, "data": token}
        elif self.headers["Authorization"] not in {f"Bearer {t}" for t in self.valid}:
            status, out = 403, {"success": False, "error": "Invalid API token"}
        else:
            self.calls.append(body["command"])
            status, out = 200, {"success": True, "data": body["command"]}
        data = json.dumps(out).encode()
        self.send_response(status), self.send_header("Content-Length", str(len(data))), self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class Frame0Proxy(unittest.TestCase):
    def setUp(self):
        FakeApp.valid, FakeApp.issued, FakeApp.calls = set(), [], []
        self.app = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeApp)
        self.proxy = fc.fc_frame0.frame0_proxy(self.app.server_address[1])
        for server in (self.app, self.proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown), self.addCleanup(server.server_close)

    def call(self, token):
        req = urllib.request.Request(f"http://127.0.0.1:{self.proxy.server_address[1]}/execute_command", method="POST", data=b'{"command": "page:get"}',
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def test_a_token_the_restarted_app_forgot_is_renewed_once_and_the_call_goes_through(self):
        FakeApp.valid.add("live")
        self.assertEqual(self.call("live")["data"], "page:get")  # a token the app knows passes untouched
        self.assertEqual(FakeApp.issued, [])
        FakeApp.valid.clear()  # the app restarted
        self.assertEqual(self.call("live")["data"], "page:get")
        self.assertEqual(self.call("live")["data"], "page:get")  # the server keeps sending its old token
        self.assertEqual(FakeApp.issued, ["token0"])
        self.assertEqual(FakeApp.calls, ["page:get"] * 3)

    def test_a_denied_renewal_is_the_answer(self):
        with mock.patch.object(fc.fc_frame0, "frame0_post", side_effect=[(403, {"success": False, "error": "Invalid API token"}),
                                                                         (403, {"success": False, "error": "User denied API access"})]):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.call("old")
        self.addCleanup(e.exception.close)
        self.assertIn("User denied API access", e.exception.read().decode())


class Frame0Mcp(unittest.TestCase):
    def test_runs_the_server_on_the_proxy_with_this_processs_stdio(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "npx").write_text(f"#!/bin/sh\necho \"$@\" > {tmp / 'args'}\nexit 7\n")
        (tmp / "npx").chmod(0o755)
        r = subprocess.run([str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "frame0", "mcp", "--api-port=58411"], capture_output=True, text=True,
                           env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"})
        self.assertEqual((r.returncode, r.stdout), (7, ""))  # its exit code is the server's, and nothing else reaches the protocol's stdout
        words = (tmp / "args").read_text().split()
        self.assertEqual(words[:2], ["-y", "frame0-mcp-server"])
        self.assertRegex(words[2], r"^--api-port=\d+$")
        self.assertNotEqual(words[2], "--api-port=58411")  # the server talks to the proxy, not the app


if __name__ == "__main__":
    unittest.main()
