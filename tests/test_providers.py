import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

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
