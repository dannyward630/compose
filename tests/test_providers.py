import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, socket, sys, tempfile, threading, unittest, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_providers  # bin/ is on sys.path once compose.py is loaded

FAKE = {"base_url": "http://127.0.0.1:1/v1", "models": ["fake-1", "fake-2"]}

def cp_apply(test, cfg):
    """A scratch config.json holding `cfg`, fc_config pointed at it, and apply_config() run; every global it sets is restored."""
    c, d = fc.fc_config, Path(tempfile.mkdtemp()); (d / "config.json").write_text(json.dumps(cfg))
    for p in [mock.patch.object(c, "CONFIG_PATH", d / "config.json"), mock.patch.object(c, "AUTH_PATH", d / "auth.json"), mock.patch.object(c, "ENV_FILE", d / ".env"),
              mock.patch.object(c, "PROBE_CACHE", d / "model-probe.json"), mock.patch.dict(os.environ), mock.patch.object(c, "PROVIDERS", {})] + [
              mock.patch.object(c, k, getattr(c, k)) for k in ("DEFAULT_MODEL", "FALLBACK_MODEL", "TEST_READER", "CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK")]:
        p.start(); test.addCleanup(p.stop)
    c.apply_config()

class ConfigProviders(unittest.TestCase):
    def exits(self, cfg, line):
        with self.assertRaises(SystemExit) as e: cp_apply(self, cfg)
        self.assertEqual(str(e.exception.code), f"{fc.fc_config.CONFIG_PATH}: {line}")
    def test_provider_of_names_declared_providers_only(self):
        cp_apply(self, {"providers": {"fakelocal": FAKE}})
        for m in ("pi:fakelocal/fake-1", "fakelocal/fake-1"): self.assertEqual(fc.fc_config.provider_of(m), ("fakelocal", "fake-1"))
        self.assertEqual(fc.fc_config.provider_of("pi:fakelocal/org/m"), ("fakelocal", "org/m"))
        for m in ("claude:opus", "pi:openrouter/x/y", "other/fake-1", "pi:other/x", "fakelocal", "pi:fakelocal"): self.assertIsNone(fc.fc_config.provider_of(m), m)
    def test_workspace_provider_replaces_the_top_level_one_by_name(self):
        other = {"base_url": "http://h/v1"}
        cp_apply(self, {"workspace": "w", "providers": {"fakelocal": FAKE, "other": other}, "workspaces": {"w": {"providers": {"fakelocal": {"base_url": "https://ws/v1"}}}}})
        self.assertEqual(fc.fc_config.PROVIDERS, {"fakelocal": {"base_url": "https://ws/v1"}, "other": other})
    def test_bad_entries_exit_with_their_line(self):
        for name in ("Fake", "-x", "_x", "a b", "a/b", ""):
            with self.subTest(name): self.exits({"providers": {name: FAKE}}, f"provider names are lowercase letters, digits, - and _: {name!r}")
        for name in ("openrouter", "openrouter-fast"):
            with self.subTest(name): self.exits({"providers": {name: {}}}, f"providers.{name} is reserved: openrouter models already route there")
        for entry in ({"models": ["a"]}, {"base_url": ""}, {"base_url": "localhost:11434/v1"}, {"base_url": "ftp://h/v1"}):
            with self.subTest(entry): self.exits({"providers": {"fakelocal": entry}}, "providers.fakelocal needs a base_url such as http://localhost:11434/v1")
        for models in ("fake-1", [1], {"a": "b"}, ["a", None]):
            with self.subTest(models): self.exits({"providers": {"fakelocal": {"base_url": "http://h/v1", "models": models}}}, "providers.fakelocal.models must be a list of model ids")
        self.exits({"providers": {"first": {"base_url": "nope"}, "Bad": FAKE}}, "providers.first needs a base_url such as http://localhost:11434/v1")
    def test_configured_model_missing_from_models_exits(self):
        bad, line = "fakelocal/nope", "{} is not in providers.fakelocal.models: fake-1, fake-2"
        self.exits({"providers": {"fakelocal": FAKE}, "models": {"implementer": "pi:" + bad}}, line.format("pi:" + bad))
        for models in ({"fallback": bad}, {"fix": bad}, {"test_reader": bad}, {"crew": {"s": bad}}, {"crew": {"s": {"model": bad}}},
                       {"crew": {"s": {"model": "claude:opus", "fallback": bad}}}, {"crew": {"s": {"model": "claude:opus", "fallback": ["claude:haiku", {"model": bad}]}}}):
            with self.subTest(models): self.exits({"providers": {"fakelocal": FAKE}, "models": models}, line.format(bad))
    def test_unrestricted_models_pass_and_no_providers_leaves_other_settings(self):
        cp_apply(self, {"models": {"implementer": "claude:opus"}})
        self.assertEqual((fc.fc_config.PROVIDERS, fc.fc_config.DEFAULT_MODEL), ({}, "claude:opus"))
        models = {"implementer": "pi:fakelocal/fake-2", "fallback": "pi:open/any/id", "test_reader": "claude:opus", "crew": {"small": "fakelocal/fake-1"}}
        cp_apply(self, {"providers": {"fakelocal": FAKE, "open": {"base_url": "http://h/v1"}}, "models": models})
        self.assertEqual(fc.fc_config.DEFAULT_MODEL, "pi:fakelocal/fake-2")

PE_JS = """// generated by compose from ~/.compose/config.json providers; do not edit
const PROVIDERS = <json>;
export default function (pi) {
  const want = process.env.COMPOSE_PI_MODEL || "";
  for (const p of PROVIDERS) {
    const ids = p.models.length ? p.models : want.startsWith(p.name + "/") ? [want.slice(p.name.length + 1)] : [];
    pi.registerProvider(p.name, { name: p.name, baseUrl: p.baseUrl, apiKey: p.apiKeyEnv ? process.env[p.apiKeyEnv] || "" : "none", api: "openai-completions",
      models: ids.map((id) => ({ id, name: id, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 131072, maxTokens: 16384 })) });
  }
}
"""

def pe_provider_of(model):
    name, _, mid = model.removeprefix("pi:").partition("/")
    return (name, mid) if name == "fakelocal" and mid else None

class PiExtension(unittest.TestCase):
    def setUp(self):
        self.d, self.providers = Path(tempfile.mkdtemp()), {"fakelocal": {"base_url": "http://127.0.0.1:1/v1", "models": ["fake-1"]}}
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", self.d / "config.json"), mock.patch.object(fc.fc_config, "PROVIDERS", self.providers),
                  mock.patch.object(fc.fc_config, "provider_of", pe_provider_of)):
            p.start(); self.addCleanup(p.stop)
        self.js = self.d / "pi-providers.js"
    def test_text_is_the_template_with_the_providers_json(self):
        self.providers["other"] = {"base_url": "http://h/v1"}  # no models: an empty list; sorted by name
        rows = [{"apiKeyEnv": None, "baseUrl": p["base_url"], "models": p.get("models", []), "name": n} for n, p in sorted(self.providers.items())]
        self.assertEqual(fc_providers.pi_extension_text().rstrip("\n"), PE_JS.replace("<json>", json.dumps(rows, sort_keys=True)).rstrip("\n"))
    def test_args_write_the_file_only_when_providers_change(self):
        for m in ("pi:fakelocal/fake-1", "pi:fakelocal/org/m"): self.assertEqual(fc_providers.pi_args(m), ["-e", str(self.js)])
        self.assertEqual(self.js.read_text(), fc_providers.pi_extension_text())
        os.utime(self.js, ns=(1, 1)); fc_providers.pi_args("pi:fakelocal/fake-1")
        self.assertEqual(self.js.stat().st_mtime_ns, 1)
        self.providers["fakelocal"]["base_url"] = "http://127.0.0.1:2/v1"; fc_providers.pi_args("pi:fakelocal/fake-1")
        self.assertIn("http://127.0.0.1:2/v1", self.js.read_text())
    def test_other_models_get_nothing_and_write_nothing(self):
        for m in ("claude:opus", "pi:openrouter/x/y", "pi:undeclared/x", "undeclared/x"):
            with self.subTest(m): self.assertEqual((fc_providers.pi_args(m), fc_providers.pi_env(m)), ([], {}))
        self.assertFalse(self.js.exists())
    def test_env_names_the_provider_and_id(self):
        for m, want in (("pi:fakelocal/fake-1", "fakelocal/fake-1"), ("fakelocal/fake-1", "fakelocal/fake-1"), ("pi:fakelocal/org/m", "fakelocal/org/m")):
            self.assertEqual(fc_providers.pi_env(m), {"COMPOSE_PI_MODEL": want})
    def test_cost_is_priced_then_free_when_local_then_the_reported_one(self):
        u = {"tokens_in": 1000, "tokens_out": 2000, "cost": 9.0}
        self.assertEqual(fc_providers.cost("openrouter/openai/gpt-oss-120b", u), (1000 * 0.35 + 2000 * 0.75) / 1e6)
        self.assertEqual(fc_providers.cost("pi:fakelocal/fake-1", u), 0.0)
        with mock.patch.object(fc.fc_config, "PRICES", {"fakelocal/fake-1": (1, 2)}): self.assertEqual(fc_providers.cost("fakelocal/fake-1", u), 5000 / 1e6)
        self.assertEqual(fc_providers.cost("claude:opus", u), 9.0)
        self.assertIsNone(fc_providers.cost("claude:opus", {"tokens_in": 1, "tokens_out": 2}))

PT_OUT = "\n".join(json.dumps(e) for e in ({"type": "message_update", "usage": {"input": 42, "output": 7}},
                   {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}))
PT_FAST = "openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast"

class PiTurnLocal(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); self.cwd = self.d / "task"; self.cwd.mkdir(); self.js = self.d / "pi-providers.js"
        self.run = mock.Mock(return_value=mock.Mock(stdout=PT_OUT, stderr="", returncode=0)); self.ledger = fc.fc_core.Ledger()
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", self.d / "config.json"), mock.patch.object(fc.fc_config, "PROVIDERS", {"fakelocal": {"base_url": "http://127.0.0.1:1/v1", "models": ["fake-1"]}}),
                  mock.patch.object(fc.fc_config, "provider_of", pe_provider_of), mock.patch.object(fc.fc_core, "LEDGER", self.ledger),
                  mock.patch.object(fc.fc_proc, "run", self.run), mock.patch.object(fc.fc_models.subprocess, "run", self.run), mock.patch.dict(os.environ)):
            p.start(); self.addCleanup(p.stop)
        os.environ.pop("COMPOSE_PI_MODEL", None)
    def turn(self, model):
        fc.fc_models.pi_turn(self.cwd, model, "hi")
        return self.run.call_args[0][0], self.run.call_args[1]["env"]
    def test_local_turn_loads_the_extension_names_the_model_and_costs_nothing(self):
        argv, env = self.turn("fakelocal/fake-1")
        self.assertEqual(argv[argv.index("-e"):argv.index("-e") + 2], ["-e", str(self.js)])
        self.assertEqual((argv[-1], env["COMPOSE_PI_MODEL"]), ("hi", "fakelocal/fake-1"))
        self.assertEqual(self.ledger.rows["fakelocal"], {"calls": 1, "tokens_in": 42, "tokens_out": 7, "cost": 0.0, "priced": True})
        self.assertIn("fakelocal $0.0000 (", self.ledger.line())
    def test_probe_carries_the_extension_before_the_model(self):
        argv = fc.fc_models.probe_command("pi:fakelocal/fake-1")
        self.assertEqual(argv[argv.index("-e"):argv.index("-e") + 2], ["-e", str(self.js)])
        self.assertLess(argv.index("-e"), argv.index("--model"))
        self.assertEqual((argv[argv.index("--model") + 1], argv[-1]), ("fakelocal/fake-1", "Reply with exactly: ok"))
        self.assertEqual(fc.fc_models.probe_once("pi:fakelocal/fake-1", 5)[0], True)
        self.assertEqual(self.run.call_args[1]["env"]["COMPOSE_PI_MODEL"], "fakelocal/fake-1")
    def test_openrouter_models_are_unchanged(self):
        for model in ("openrouter/openai/gpt-oss-120b", PT_FAST):
            with self.subTest(model):
                argv, env = self.turn(model)
                self.assertNotIn("-e", argv); self.assertNotIn("COMPOSE_PI_MODEL", env); self.assertEqual(argv[-1], "hi")
                p = fc.fc_config.PRICES[model]; self.assertEqual(self.ledger.rows["openrouter"]["cost"], (42 * p[0] + 7 * p[1]) / 1e6); self.ledger.rows.clear()
                self.assertNotIn("-e", fc.fc_models.probe_command("pi:" + model))
                fc.fc_models.probe_once("pi:" + model, 5); self.assertNotIn("COMPOSE_PI_MODEL", self.run.call_args[1]["env"])
        self.assertFalse(self.js.exists())

class HerdrPiLocal(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); (self.d / "wt").mkdir(); (self.d / "wt.guard.json").write_text("{}"); self.ledger = fc.fc_core.Ledger()
        self.panes, self.starts, self.js = [], [], self.d / "pi-providers.js"
        started = {"agent": {"agent_session": {"value": "sfile"}}}
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", self.d / "config.json"), mock.patch.object(fc.fc_config, "PROVIDERS", {"fakelocal": {"base_url": "http://127.0.0.1:1/v1"}}),
                  mock.patch.object(fc.fc_config, "provider_of", pe_provider_of), mock.patch.object(fc.fc_core, "LEDGER", self.ledger), mock.patch.dict(os.environ),
                  mock.patch.object(fc.fc_herdr, "herdr", return_value={}), mock.patch.object(fc.fc_herdr, "herdr_error", return_value=({}, None)),
                  mock.patch.object(fc.fc_herdr, "herdr_agent_start", lambda *a: self.starts.append(list(a)) or started), mock.patch.object(fc.fc_readguard, "command", lambda f: "guard"),
                  mock.patch.object(fc.fc_herdr, "herdr_implementer_pane", lambda space, cwd, env, label: self.panes.append(env) or "p1"),
                  mock.patch.object(fc.fc_models, "parse_pi_session", return_value=(1, "ok", [], {"tokens_in": 42, "tokens_out": 7, "cost": 0.5}, []))):
            p.start(); self.addCleanup(p.stop)
        os.environ.pop("COMPOSE_PI_MODEL", None)
    def turn(self, model):
        task = {"meta": {"id": "028", "title": "t"}, "proj": self.d / "shop", "space": "w9"}
        fc.fc_implement.herdr_pi(str(self.d / "wt"), model, "hi", None, task)
        return self.panes[-1], self.starts[-1][self.starts[-1].index("--") + 1:]
    def test_local_pane_env_start_args_and_ledger_row(self):
        env, args = self.turn("fakelocal/fake-1")
        self.assertEqual(env["COMPOSE_PI_MODEL"], "fakelocal/fake-1")
        pairs = [args[i:i + 2] for i in range(len(args))]
        self.assertLess(pairs.index(["-e", str(fc.fc_readguard.PI_EXT)]), pairs.index(["-e", str(self.js)]))
        self.assertLess(args.index(str(self.js)), args.index("--model")); self.assertEqual(args[args.index("--model") + 1], "fakelocal/fake-1")
        self.assertEqual(self.ledger.rows["fakelocal"], {"calls": 1, "tokens_in": 42, "tokens_out": 7, "cost": 0.0, "priced": True})
    def test_openrouter_fast_model_is_unchanged(self):
        model = PT_FAST; env, args = self.turn(model)
        self.assertNotIn("COMPOSE_PI_MODEL", env); self.assertNotIn(str(self.js), args); self.assertEqual(args[args.index("--model") + 1], model)
        p = fc.fc_config.PRICES[model]; self.assertEqual(self.ledger.rows["openrouter"]["cost"], (42 * p[0] + 7 * p[1]) / 1e6)
        self.assertFalse(self.js.exists())
    def test_fc_implement_stays_within_its_line_cap(self):
        self.assertLessEqual(len(Path(fc.fc_implement.__file__).read_text().splitlines()), 600)

class CrewPiLocal(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp()); self.js, self.ext, self.calls = self.d / "pi-providers.js", self.d / "herdr-ext.ts", []
        self.ext.write_text("")
        replies = {("agent", "list"): {"agents": []}, ("tab", "create"): {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}}, ("agent", "get"): {"agent": {"agent_status": "working"}}}
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", self.d / "config.json"), mock.patch.object(fc.fc_config, "PROVIDERS", {"fakelocal": {"base_url": "http://127.0.0.1:1/v1"}}),
                  mock.patch.object(fc.fc_config, "provider_of", pe_provider_of), mock.patch.object(fc.fc_herdr, "PI_HERDR_EXT", self.ext), mock.patch.object(fc.fc_core, "project_dir", return_value=self.d / ".compose" / "shop"),
                  mock.patch.object(fc.fc_herdr, "herdr", lambda *args, **kw: self.calls.append(args) or replies.get(args[:2], {})), mock.patch("time.sleep"),
                  mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_herdr, "herdr_space", return_value="w9"),
                  mock.patch.object(fc.fc_herdr, "herdr_find_space", return_value="w9"), mock.patch.object(fc.fc_mcp, "installed_servers", return_value=[]),
                  mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")), mock.patch.dict(os.environ), mock.patch("builtins.print")):
            p.start(); self.addCleanup(p.stop)
        (self.d / ".compose" / "shop").mkdir(parents=True); os.environ.pop("COMPOSE_PI_MODEL", None)
    def start(self, model):
        fc.fc_crew.cmd_crew(type("A", (), {"action": "start", "role": "wayfinder", "title": "t", "brief": "b", "model": model}))
        tab, start = (next(c for c in self.calls if c[:2] == pair) for pair in (("tab", "create"), ("agent", "start")))
        return list(tab), list(start)
    def test_local_pi_teammate_gets_tab_env_and_pi_args(self):
        tab, start = self.start("pi:fakelocal/fake-1")
        self.assertIn(["--env", "COMPOSE_PI_MODEL=fakelocal/fake-1"], [tab[i:i + 2] for i in range(len(tab))])
        self.assertIn(["-e", str(self.js)], [start[i:i + 2] for i in range(len(start))])
        self.assertLess(start.index(str(self.js)), start.index("--model")); self.assertEqual(start[start.index("--model") + 1], "fakelocal/fake-1")
        self.assertLess(start.index(str(self.ext)), start.index(str(self.js)))
        self.assertFalse([a for a in tab + start if "sk-or" in a or a == "--api-key"])
    def test_claude_and_openrouter_teammates_are_unchanged(self):
        for model in ("claude:opus", "pi:openrouter-fast/z-ai/glm@preset/p"):
            with self.subTest(model=model):
                self.calls.clear(); tab, start = self.start(model)
                self.assertFalse([a for a in tab + start if "COMPOSE_PI_MODEL" in a or "pi-providers.js" in a])
        self.assertFalse(self.js.exists())

class ReachHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.server.seen.append(self.path); self.send_response(self.server.code); self.send_header("Content-Length", "0"); self.end_headers()

class Reach(unittest.TestCase):
    def providers(self, **urls):
        p = mock.patch.object(fc.fc_config, "PROVIDERS", {n: {"base_url": u} for n, u in urls.items()}); p.start(); self.addCleanup(p.stop)
    def serve(self, code=200):
        s = ThreadingHTTPServer(("127.0.0.1", 0), ReachHandler); s.code, s.seen = code, []
        threading.Thread(target=s.serve_forever, daemon=True).start(); self.addCleanup(s.server_close); self.addCleanup(s.shutdown)
        return s, f"http://127.0.0.1:{s.server_address[1]}/v1/"
    def closed(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        return f"http://127.0.0.1:{port}/v1/"
    def line(self, name, url): return f"local provider {name} at {url} is not answering: start the server, then run again"
    def test_any_http_answer_is_up_and_gets_models_under_the_base_url(self):
        for code in (200, 404, 503):
            with self.subTest(code=code):
                s, url = self.serve(code); self.providers(fakelocal=url)
                self.assertEqual(fc_providers.reach("fakelocal"), (True, f"HTTP {code}")); self.assertEqual(s.seen, ["/v1/models"])
    def test_closed_port_is_not_answering_with_a_5_second_timeout(self):
        url = self.closed(); self.providers(fakelocal=url)
        with mock.patch.object(urllib.request, "urlopen", wraps=urllib.request.urlopen) as uo:
            self.assertEqual(fc_providers.reach("fakelocal"), (False, self.line("fakelocal", url)))
        args, kw = uo.call_args; self.assertEqual(kw.get("timeout", args[1] if len(args) > 1 else None), 5)
    def test_url_errors_oserrors_and_timeouts_are_not_answering(self):
        url = self.closed(); self.providers(fakelocal=url)
        for err in (urllib.error.URLError("refused"), OSError("down"), socket.timeout("slow")):
            with self.subTest(err=err), mock.patch.object(urllib.request, "urlopen", side_effect=err):
                self.assertEqual(fc_providers.reach("fakelocal"), (False, self.line("fakelocal", url)))
    def test_reach_is_never_cached(self):
        s, url = self.serve(); self.providers(fakelocal=url)
        self.assertTrue(fc_providers.reach("fakelocal")[0]); s.shutdown(); s.server_close()
        self.assertEqual(fc_providers.reach("fakelocal"), (False, self.line("fakelocal", url)))
    def test_doctor_rows_are_sorted_with_a_check_that_reaches_the_provider(self):
        s, up = self.serve(); down = self.closed(); self.providers(zeta=up, alpha=down)
        rows = fc_providers.doctor_rows()
        self.assertEqual([(r[0], r[2], *r[3:]) for r in rows], [(f"local provider {n}", f"start the server at {u}", "default", False, "manual") for n, u in (("alpha", down), ("zeta", up))])
        self.assertEqual([r[1](Path(".")) for r in rows], [(False, "not answering"), (True, "not answering")])
    def test_no_providers_give_no_rows(self):
        self.providers(); self.assertEqual(fc_providers.doctor_rows(), [])
