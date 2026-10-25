import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, sys, unittest
from pathlib import Path
from unittest import mock
# tests/test_modules.py fails a test file without the next line
os.environ["HERDR_ENV"] = ""
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_config


class FactoryConfig(unittest.TestCase):
    def setUp(self):
        saved = dict(vars(fc_config)); self.addCleanup(lambda: vars(fc_config).update(saved))  # apply_config sets module globals

    def apply(self, factory):
        with mock.patch.object(fc_config, "read_config", return_value={"factory": factory}): fc_config.apply_config(move=False)

    def test_factory_keys_must_be_whole_numbers(self):
        for factory, msg in (({"day_tickets": 0}, "factory.day_tickets must be a whole number of 1 or more, not 0"),
                             ({"turn_seconds": 5}, "factory.turn_seconds must be a whole number of 10 or more, not 5"),
                             ({"offer_snooze_minutes": 0}, "factory.offer_snooze_minutes must be a whole number of 1 or more, not 0")):
            with self.assertRaises(SystemExit) as c: self.apply(factory)
            self.assertEqual(c.exception.code, f"{fc_config.CONFIG_PATH}: {msg}")
        self.apply({"day_tickets": 3})
        self.assertEqual(fc_config.FACTORY, {"day_tickets": 3, "turn_seconds": 120, "offer_snooze_minutes": 60})


if __name__ == "__main__":
    unittest.main()
