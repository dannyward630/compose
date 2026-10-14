import importlib.machinery, importlib.util, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class FigmaCheck(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))

    def check(self, figma=None):
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("sys.stdout", out):
            fc.cmd_figma(SimpleNamespace(repo=".", project="p", action="check", figma=figma, only=None))
        return out.getvalue()

    def stored(self):
        return json.loads((self.proj / "linear.json").read_text())

    def test_figma_key_parses_urls_and_bare_keys(self):
        for text, key in (("https://www.figma.com/design/AbCdEf123456/Shop?node-id=1-2", "AbCdEf123456"),
                          ("https://www.figma.com/design/AbCdEf123456/branch/BrAnCh789012/Shop", "BrAnCh789012"),
                          ("https://figma.com/board/BoArD1234567/Flow", "BoArD1234567"),
                          ("https://www.figma.com/slides/SlIdEs123456", "SlIdEs123456"),
                          ("AbCdEf123456", "AbCdEf123456"),
                          ("junk", None), ("abc123456", None), ("a" * 41, None), ("AbCdEf-123456", None),
                          ("https://example.com/design/AbCdEf123456/Shop", None)):
            self.assertEqual(fc.figma_key(text), key, text)

    def test_store_figma_keeps_other_keys_and_creates_missing_file(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "OldKey123456", "x": 1}))
        fc.store_figma(self.proj, "NewKey123456")
        self.assertEqual(self.stored(), {"feature": "ENG-1", "figma": "NewKey123456", "x": 1})
        (self.proj / "linear.json").unlink()
        fc.store_figma(self.proj, "NewKey123456")
        self.assertEqual(self.stored(), {"figma": "NewKey123456"})

    def test_check_stores_a_url_then_shows_the_stored_key(self):
        out = self.check("https://www.figma.com/design/AbCdEf123456/Shop?node-id=1-2")
        self.assertEqual(self.stored(), {"feature": "ENG-1", "figma": "AbCdEf123456"})
        self.assertIn("figma file AbCdEf123456 stored in ", out)
        self.assertIn("linear.json; confirm access with whoami and get_metadata through the Figma MCP", out)
        self.assertIn("figma file AbCdEf123456 stored in ", self.check())

    def test_check_refuses_junk_and_a_missing_key(self):
        with self.assertRaises(SystemExit) as e:
            self.check("not a key")
        self.assertEqual(str(e.exception), "not a Figma file url or key: not a key")
        self.assertEqual(self.stored(), {"feature": "ENG-1"})
        with self.assertRaises(SystemExit) as e:
            self.check()
        self.assertEqual(str(e.exception), "no Figma file: fast-coding figma check --figma <url or key>")

    def test_help_lists_check_and_judge(self):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding"), "figma", "--help"], capture_output=True, text=True)
        self.assertIn("{check,judge}", r.stdout)


def judge_task(ident, tid, title, crits, kind="design"):
    desc = "## Acceptance criteria\n" + "".join(f"- {c}\n" for c in crits) + f"\n```fast-coding\nid: {tid}\nkind: {kind}\ntest: t\n```\n"
    return {"id": ident, "title": title, "description": desc, "status": "Todo", "blockedBy": []}


class FigmaJudge(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "AbCdEf123456"}))
        (self.proj / "verify.json").write_text(json.dumps({"acceptance_threshold": 0.7}))
        fc.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            judge_task("ENG-3", "001", "Cart page", ["Shows the total", "Has a pay button"]), judge_task("ENG-4", "002", "Store", ["x"], kind="code"),
            judge_task("ENG-5", "003", "Hero", ["Has a headline"]), judge_task("ENG-6", "004", "Pay", ["Has a card field"]), judge_task("ENG-7", "005", "Bare", [])]})
        for tid in ("001", "002", "004", "005", "009"):  # a tree for every id but 003, so only the id and kind checks can refuse 002 and 009
            (self.proj / "results" / f"{tid}.tree.txt").write_text(f"FRAME {tid}\n  TEXT Total: $10\n")
        for name, value in (("ENV_FILE", self.proj / "none.env"), ("say", lambda m: None)):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)

    def judge(self, only, replies, confirm=None, fail=None, blocks=False):
        replies = {t: {"model": "jev-test", "answers": {f"c{i}": {"choice": c, "probabilities": {c: p}} for i, (c, p) in enumerate(r)}} for t, r in replies.items()}
        self.out = io.StringIO()
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "jev_ask", side_effect=lambda env, cfg, state, q, label: replies[state["task"]]) as self.ask, \
                mock.patch.object(fc, "fast_json", side_effect=fail, return_value=confirm) as self.confirm, mock.patch.object(fc, "linear_event") as self.ev, mock.patch("sys.stdout", self.out):
            try:
                fc.cmd_figma(SimpleNamespace(repo=".", project="p", action="judge", figma=None, only=only))
            except SystemExit as e:
                if not blocks:
                    raise
                self.assertEqual(e.code, 1)  # a blocked task exits non-zero
        return json.loads((self.proj / "results" / f"{only[:3]}.json").read_text())

    def test_all_met_writes_a_passed_result_and_tells_linear(self):
        (self.proj / "results" / "001.json").write_text(json.dumps({"status": "failed", "attempts": 2}))
        res = self.judge("001", {"Cart page": [("MET", 0.95), ("MET", 0.9)]})
        env, cfg, state, questions, label = self.ask.call_args.args
        self.assertEqual((state, label, cfg["acceptance_threshold"]), ({"task": "Cart page", "tree": "FRAME 001\n  TEXT Total: $10\n"}, "figma judge", 0.7))
        self.assertEqual([(q["instructions"]["criterion"], q["instructions"]["task"], sorted(q["criteria"])) for q in questions.values()],
                         [("Shows the total", "001", ["MET", "NOT_MET", "UNCLEAR"]), ("Has a pay button", "001", ["MET", "NOT_MET", "UNCLEAR"])])
        self.assertEqual({k: res[k] for k in ("id", "title", "status", "kind", "failed", "attempts", "seconds", "cost", "model", "branch")},
                         {"id": "001", "title": "Cart page", "status": "passed", "kind": "design", "failed": [], "attempts": 3, "seconds": 0.0, "cost": 0.0, "model": "jev-test", "branch": "figma:AbCdEf123456"})
        self.assertEqual((len(res["criteria"]), bool(res["finished_at"]), self.confirm.called, "TREE" in questions["c0"]["instructions"]["rules"]), (2, True, False, True))
        self.assertIn("001 MET p_not_met=0.00 Shows the total", self.out.getvalue())
        self.assertEqual(self.ev.call_args_list, [mock.call(self.proj, mock.ANY, "passed", res)])

    def test_only_a_confirmed_not_met_at_the_threshold_fails(self):
        res = self.judge("001", {"Cart page": [("NOT_MET", 0.65), ("NOT_MET", 0.7)]}, fail=RuntimeError("down"), blocks=True)
        self.assertEqual((res["status"], self.confirm.call_count), ("blocked", 1))
        self.assertIn("CRITERION: Has a pay button", self.confirm.call_args.args[2])
        replies = {"Cart page": [("MET", 0.9), ("MET", 0.9)], "Pay": [("NOT_MET", 0.9)]}
        with self.assertRaises(SystemExit) as e:
            self.judge("001,004", replies, confirm={"confirmed": True, "evidence": "FRAME 004"})
        self.assertNotIn(e.exception.code, (0, None))
        res = json.loads((self.proj / "results" / "004.json").read_text())
        self.assertEqual((res["status"], len(res["failed"])), ("failed", 1))
        self.assertIn("004 NOT_MET p_not_met=0.90 Has a card field", self.out.getvalue())
        self.assertEqual([c.args[1]["id"] for c in self.ev.call_args_list], ["001"])

    def test_only_all_met_passes_so_unclear_and_unconfirmed_not_met_block(self):
        res = self.judge("001", {"Cart page": [("NOT_MET", 0.0), ("UNCLEAR", 0.14)]}, confirm={"confirmed": False, "evidence": ""}, blocks=True)
        self.assertEqual((res["status"], res["failed"], len(res["unclear"])), ("failed", [], 2))
        self.assertFalse(self.ev.called)

    def test_refuses_with_one_line(self):
        for only, needle in ((None, "figma judge needs --only <ids>"), ("009", "009"), ("002", "002"), ("003", f"no node tree at {self.proj / 'results' / '003.tree.txt'}"), ("005", "005: no acceptance criteria to judge")):
            with self.subTest(only=only), self.assertRaises(SystemExit) as e:
                self.judge(only, {})
            self.assertIn(needle, str(e.exception))
            self.assertNotIn("\n", str(e.exception))
            self.assertEqual("no node tree" in str(e.exception), only == "003")

    def test_choices_name_the_tree_not_the_code(self):
        self.judge("001", {"Cart page": [("MET", 0.9), ("MET", 0.9)]})
        tree = {"MET": "The tree satisfies this criterion.", "NOT_MET": "The tree violates or omits this criterion.", "UNCLEAR": "Cannot be decided from the tree shown."}
        for q in self.ask.call_args.args[3].values():
            self.assertEqual(q["criteria"], tree)
            self.assertNotIn("code", " ".join(q["criteria"].values()).lower())

    def test_a_billing_halt_from_the_confirm_call_stops_the_command(self):
        with self.assertRaises(fc.PaymentRequired):
            self.judge("001,004", {"Cart page": [("NOT_MET", 0.9), ("MET", 0.9)], "Pay": [("MET", 0.9)]}, fail=fc.PaymentRequired("openrouter", "402"))
        self.assertEqual((self.confirm.call_count, self.ask.call_count, self.ev.called), (1, 1, False))
        self.assertFalse((self.proj / "results" / "001.json").exists())

    def test_a_confirm_reply_wrapped_in_a_list_is_unwrapped(self):
        res = self.judge("004", {"Pay": [("NOT_MET", 0.9)]}, confirm=[{"confirmed": True, "evidence": "FRAME 004"}], blocks=True)
        self.assertEqual((res["status"], res["criteria"][0]["evidence"], self.confirm.call_count, res["judge_errors"]), ("failed", "FRAME 004", 1, []))

    def test_a_confirm_call_that_still_fails_is_a_judge_error_not_a_verdict(self):
        for kw in ({"confirm": [1, 2]}, {"fail": ValueError("bad json")}):
            res = self.judge("004", {"Pay": [("NOT_MET", 0.9)]}, blocks=True, **kw)
            row = res["criteria"][0]
            self.assertEqual((res["status"], row["confirmed"], row["judge_error"], res["failed"], len(res["judge_errors"])), ("blocked", False, True, [], 1))
            self.assertIn("confirm call failed", row["evidence"])
            self.assertEqual(self.confirm.call_count, 2)  # retried once with a stricter instruction
            self.assertIn("no list", self.confirm.call_args.args[1])
            self.assertIn("BLOCKED by a judge tool error", self.out.getvalue())
            self.assertFalse(self.ev.called)


class FigmaConnectorBriefs(unittest.TestCase):
    def test_designer_and_builder_briefs_name_the_connector_and_ban_the_plugin(self):
        builder = fc.design_brief({"id": "001", "nodes": ["Page/A"]}, "AbCd", Path("r"))
        designer = fc.DESIGNER_BRIEF.format(slug="p", wt="/w", feature="ENG-1", figma="AbCd")
        for brief in (builder, designer):
            self.assertIn("mcp__claude_ai_Figma__*", brief)
            self.assertIn("one ToolSearch select call", brief)
            self.assertIn("Never use `plugin:*figma*` tools", brief)


if __name__ == "__main__":
    unittest.main()
