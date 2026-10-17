import importlib.machinery, importlib.util, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class FigmaCheck(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))

    def check(self, figma=None):
        out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("sys.stdout", out):
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
            self.assertEqual(fc.fc_core.figma_key(text), key, text)

    def test_store_figma_keeps_other_keys_and_creates_missing_file(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "OldKey123456", "x": 1}))
        fc.store_figma(self.proj, "NewKey123456")
        self.assertEqual(self.stored(), {"feature": "ENG-1", "figma": "NewKey123456", "x": 1})
        (self.proj / "linear.json").unlink()
        fc.store_figma(self.proj, "NewKey123456")
        self.assertEqual(self.stored(), {"figma": "NewKey123456"})

    def test_check_stores_a_url_then_shows_the_stored_key(self):
        with mock.patch.object(fc, "framelink_fetch", return_value="{}") as fetch:
            out = self.check("https://www.figma.com/design/AbCdEf123456/Shop?node-id=1-2")
            self.assertIn("figma file AbCdEf123456 stored in ", self.check())
        self.assertEqual(self.stored(), {"feature": "ENG-1", "figma": "AbCdEf123456"})
        self.assertIn("figma file AbCdEf123456 stored in ", out)
        self.assertIn("confirm the write connector with whoami", out)
        self.assertIn("framelink reads figma file AbCdEf123456", out)
        fetch.assert_called_with("AbCdEf123456", depth=1)

    def test_check_says_how_to_set_up_framelink_when_it_cannot_read(self):
        with mock.patch.object(fc, "framelink_fetch", side_effect=RuntimeError(fc.FRAMELINK_SETUP)):
            with self.assertRaises(SystemExit) as e:
                self.check("AbCdEf123456")
        msg = str(e.exception)
        for text in ("framelink cannot read figma file AbCdEf123456", ".config/figma-context-mcp/.env", "claude mcp add framelink-figma", "--env", "FIGMA_API_KEY=<token>"):
            self.assertIn(text, msg)

    def test_framelink_fetch_uses_env_file_depth_and_never_leaks_the_token(self):
        env = self.proj / "fl.env"
        with self.assertRaises(RuntimeError) as e:
            fc.framelink_fetch("K", env_file=env)
        self.assertIn("claude mcp add framelink-figma", str(e.exception))
        env.write_text("FIGMA_API_KEY=figd_secret_token\n")
        ok = SimpleNamespace(returncode=0, stdout='{"nodes": []}', stderr="")
        with mock.patch.object(subprocess, "run", return_value=ok) as run:
            self.assertEqual(fc.framelink_fetch("K", node="1:2", depth=1, env_file=env), '{"nodes": []}')
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:4], ["npx", "-y", "figma-developer-mcp", "fetch"])
        self.assertEqual(cmd[cmd.index("--env") + 1], str(env))
        for flag, val in (("--file-key", "K"), ("--node-id", "1:2"), ("--depth", "1")):
            self.assertEqual(cmd[cmd.index(flag) + 1], val)
        self.assertNotIn("figd_secret_token", " ".join(cmd))
        bad = SimpleNamespace(returncode=1, stdout="", stderr="403 token figd_secret_token rejected")
        with mock.patch.object(subprocess, "run", return_value=bad), self.assertRaises(RuntimeError) as e:
            fc.framelink_fetch("K", env_file=env)
        self.assertIn("403 token *** rejected", str(e.exception))
        self.assertNotIn("figd_secret_token", str(e.exception))

    def test_check_refuses_junk_and_a_missing_key(self):
        with self.assertRaises(SystemExit) as e:
            self.check("not a key")
        self.assertEqual(str(e.exception), "not a Figma file url or key: not a key")
        self.assertEqual(self.stored(), {"feature": "ENG-1"})
        with self.assertRaises(SystemExit) as e:
            self.check()
        self.assertEqual(str(e.exception), "no Figma file: fast-coding figma check --figma <url or key>")

    def test_help_lists_check_and_judge(self):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py"), "figma", "--help"], capture_output=True, text=True)
        self.assertIn("{check,tree,judge}", r.stdout)


class FigmaTree(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "AbCdEf123456"}))
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            judge_task("ENG-1", "001", "Button", ["Has a label"]), judge_task("ENG-2", "002", "Code", ["x"], kind="code")]})

    def tree(self, **kw):
        ns = dict(repo=".", project="p", action="tree", figma=None, only="001", node="1:2,3-4", depth=None, bindings=None)
        out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("sys.stdout", out):
            fc.cmd_figma(SimpleNamespace(**{**ns, **kw}))
        return out.getvalue()

    def test_saves_each_nodes_framelink_tree_then_the_write_results(self):
        (self.proj / "bind.txt").write_text('{"bound": "color/bg"}\n')
        with mock.patch.object(fc, "framelink_fetch", side_effect=lambda key, node=None, depth=None: f"TREE {node}") as fetch:
            out = self.tree(bindings=str(self.proj / "bind.txt"), depth=3)
        text = (self.proj / "results" / "001.tree.txt").read_text()
        self.assertEqual(text, 'NODE 1:2\nTREE 1:2\n\nNODE 3-4\nTREE 3:4\n\nWRITE RESULT (facts the write script returned: node ids, variable bindings, component keys)\n{"bound": "color/bg"}\n')
        self.assertEqual([c.args[0] for c in fetch.call_args_list], ["AbCdEf123456"] * 2)
        self.assertEqual(fetch.call_args.kwargs, {"node": "3:4", "depth": 3})
        self.assertIn("001.tree.txt", out)

    def test_refuses_a_missing_id_node_non_design_task_and_a_failed_fetch(self):
        for kw, msg in ((dict(only=None), "needs --only"), (dict(node=None), "needs --only"), (dict(only="002"), "002 is not a design task")):
            with self.assertRaises(SystemExit) as e:
                self.tree(**kw)
            self.assertIn(msg, str(e.exception))
        with mock.patch.object(fc, "framelink_fetch", side_effect=RuntimeError("framelink fetch failed")), self.assertRaises(SystemExit) as e:
            self.tree()
        self.assertEqual(str(e.exception), "framelink fetch failed")
        self.assertFalse((self.proj / "results" / "001.tree.txt").exists())


def judge_task(ident, tid, title, crits, kind="design"):
    desc = "## Acceptance criteria\n" + "".join(f"- {c}\n" for c in crits) + f"\n```fast-coding\nid: {tid}\nkind: {kind}\ntest: t\n```\n"
    return {"id": ident, "title": title, "description": desc, "status": "Todo", "blockedBy": []}


def reask_reply(choice):
    return {"model": "jev-test", "answers": {"c0": {"choice": choice, "probabilities": {choice: 0.9}}}}


def big_tree(variants=15, pad=10000):
    """A Framelink-shaped tree of ~variants*pad characters: a Button set whose every variant holds a Tint child, as design 138 had."""
    kids = [{"id": f"1:{i}", "name": f"variant={i}", "type": "COMPONENT", "padding": "x" * pad,
             "children": [{"id": f"2:{i}", "name": "Tint", "type": "RECTANGLE"}]} for i in range(variants)]
    doc = {"metadata": {"name": "File"}, "nodes": [{"id": "9:536", "name": "Button", "type": "COMPONENT_SET", "children": kids}], "globalVars": {"styles": {}}}
    return "NODE 9:536\n" + json.dumps(doc, indent=2) + "\n"


class FigmaJudge(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "AbCdEf123456"}))
        (self.proj / "verify.json").write_text(json.dumps({"acceptance_threshold": 0.7}))
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            judge_task("ENG-3", "001", "Cart page", ["Shows the total", "Has a pay button"]), judge_task("ENG-4", "002", "Store", ["x"], kind="code"),
            judge_task("ENG-5", "003", "Hero", ["Has a headline"]), judge_task("ENG-6", "004", "Pay", ["Has a card field"]), judge_task("ENG-7", "005", "Bare", [])]})
        for tid in ("001", "002", "004", "005", "009"):  # a tree for every id but 003, so only the id and kind checks can refuse 002 and 009
            (self.proj / "results" / f"{tid}.tree.txt").write_text(f"FRAME {tid}\n  TEXT Total: $10\n")
        for mod, name, value in ((fc.fc_config, "ENV_FILE", self.proj / "none.env"), (fc.fc_core, "say", lambda m: None)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)

    def judge(self, only, replies, confirm=None, fail=None, blocks=False, reask=None):
        replies = {t: {"model": "jev-test", "answers": {f"c{i}": {"choice": c, "probabilities": {c: p}} for i, (c, p) in enumerate(r)}} for t, r in replies.items()}
        self.out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc, "jev_ask", side_effect=lambda env, cfg, state, q, label: reask_reply(reask) if label.endswith("re-ask") else replies[state["task"]]) as self.ask, \
                mock.patch.object(fc, "fast_json", side_effect=fail, return_value=confirm) as self.confirm, mock.patch.object(fc.fc_linear, "linear_event") as self.ev, mock.patch("sys.stdout", self.out):
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

    def test_a_refuted_not_met_or_unclear_is_re_asked_once_and_only_a_met_reply_passes(self):
        refuted = {"confirmed": False, "evidence": "Criterion is satisfied"}
        res = self.judge("004", {"Pay": [("NOT_MET", 0.9)]}, confirm=refuted, reask="MET")
        row = res["criteria"][0]
        self.assertEqual((res["status"], row["choice"], row["first_choice"], row["reask"]["choice"], row["evidence"]), ("passed", "MET", "NOT_MET", "MET", "Criterion is satisfied"))
        self.assertEqual(self.ask.call_count, 2)
        self.assertIn("Criterion is satisfied", self.ask.call_args.args[3]["c0"]["instructions"]["context"])
        res = self.judge("004", {"Pay": [("UNCLEAR", 0.3)]}, reask="MET")
        self.assertEqual((res["status"], self.ask.call_count, self.confirm.called), ("passed", 2, False))
        for first, again in (("NOT_MET", "NOT_MET"), ("NOT_MET", "UNCLEAR"), ("UNCLEAR", "NOT_MET"), ("UNCLEAR", "UNCLEAR")):
            res = self.judge("004", {"Pay": [(first, 0.9)]}, confirm=refuted, reask=again, blocks=True)
            self.assertEqual((res["status"], len(res["unclear"]), self.ask.call_count), ("failed", 1, 2), (first, again))

    def test_a_task_figma_line_is_the_file_the_result_names(self):
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            {**judge_task("ENG-3", "001", "Cart page", ["x"]), "description": judge_task("ENG-3", "001", "Cart page", ["x"])["description"].replace("test: t", "test: t\nfigma: LibKey123456789")}]})
        res = self.judge("001", {"Cart page": [("MET", 0.95)]})
        self.assertEqual(res["branch"], "figma:LibKey123456789")

    def test_a_confirm_error_blocks_with_no_re_ask(self):
        res = self.judge("004", {"Pay": [("NOT_MET", 0.9)]}, fail=RuntimeError("down"), reask="MET", blocks=True)
        self.assertEqual((res["status"], res["criteria"][0]["choice"], self.ask.call_count), ("blocked", "NOT_MET", 1))

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


    def judge_big(self, answer, confirm=None, text=None):
        """Judge task 001 on a big tree; answer(part_text) -> (choice, p_not_met) per chunk, one criterion."""
        (self.proj / "results" / "001.tree.txt").write_text(text or big_tree())
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [judge_task("ENG-3", "001", "Cart page", ["Every variant has a Tint"])]})
        self.states = []

        def jev(env, cfg, state, q, label):
            self.states.append(state)
            choice, p = answer(state["tree"])
            return {"model": "jev-test", "answers": {"c0": {"choice": choice, "probabilities": {choice: 0.9, "NOT_MET": p}}}}
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc, "jev_ask", side_effect=jev), mock.patch.object(fc, "fast_json", return_value=confirm), \
                mock.patch.object(fc.fc_linear, "linear_event"), mock.patch("sys.stdout", io.StringIO()):
            try:
                fc.cmd_figma(SimpleNamespace(repo=".", project="p", action="judge", figma=None, only="001"))
            except SystemExit as e:
                self.assertEqual(e.code, 1)
        return json.loads((self.proj / "results" / "001.json").read_text())

    def test_chunks_hold_every_node_and_stay_under_the_limit(self):
        text = big_tree()
        chunks = fc.tree_chunks(text)
        self.assertGreater(len(chunks), 4)
        self.assertTrue(all(len(c) <= fc.TREE_CHUNK_CHARS for c in chunks))
        joined = "\n".join(chunks)
        for i in range(15):
            self.assertIn(f'"id": "1:{i}"', joined)
            self.assertIn(f'"id": "2:{i}"', joined)
        self.assertEqual(fc.tree_chunks("small tree\n"), ["small tree\n"])

    def test_a_node_with_no_children_or_a_plain_text_tree_is_still_covered(self):
        blob = "NODE 1:1\n" + "".join(f"line {i} " + "y" * 200 + "\n" for i in range(500))
        chunks = fc.tree_chunks(blob)
        self.assertTrue(all(len(c) <= fc.TREE_CHUNK_CHARS for c in chunks))
        self.assertEqual("".join(chunks).count("line "), 500)
        self.assertEqual("".join(fc.tree_chunks("z" * 70000 + "\n")).count("z"), 70000)

    def test_a_big_tree_is_judged_whole_and_the_result_counts_the_chunks(self):
        res = self.judge_big(lambda t: ("MET", 0.0) if '"id": "2:7"' in t else ("UNCLEAR", 0.0))
        self.assertEqual((res["status"], res["chunks"], len(self.states)), ("passed", len(self.states), res["chunks"]))
        self.assertGreater(res["chunks"], 1)
        self.assertTrue(all(len(s["tree"]) <= fc.TREE_CHUNK_CHARS for s in self.states))
        self.assertEqual([s["tree_part"] for s in self.states][:2], [f"1 of {res['chunks']}", f"2 of {res['chunks']}"])

    def test_one_chunk_showing_not_met_fails_the_criterion_whatever_the_others_say(self):
        res = self.judge_big(lambda t: ("NOT_MET", 0.9) if '"id": "1:12"' in t else ("MET", 0.0), confirm={"confirmed": True, "evidence": "variant=12"})
        self.assertEqual((res["status"], res["criteria"][0]["choice"], res["criteria"][0]["evidence"]), ("failed", "NOT_MET", "variant=12"))

    def test_no_chunk_showing_met_leaves_the_criterion_unmet(self):
        res = self.judge_big(lambda t: ("UNCLEAR", 0.0))
        self.assertEqual((res["status"], res["criteria"][0]["choice"]), ("failed", "UNCLEAR"))

    def test_a_chunk_that_errors_blocks_and_is_never_a_pass(self):
        def jev(env, cfg, state, q, label):
            if state.get("tree_part", "").startswith("2 of"):
                raise RuntimeError("max_tokens_exceeded")
            return {"model": "m", "answers": {"c0": {"choice": "MET", "probabilities": {"MET": 0.9}}}}
        (self.proj / "results" / "001.tree.txt").write_text(big_tree())
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [judge_task("ENG-3", "001", "Cart page", ["Every variant has a Tint"])]})
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc, "jev_ask", side_effect=jev), mock.patch.object(fc.fc_linear, "linear_event") as ev, mock.patch("sys.stdout", io.StringIO()), self.assertRaises(SystemExit):
            fc.cmd_figma(SimpleNamespace(repo=".", project="p", action="judge", figma=None, only="001"))
        res = json.loads((self.proj / "results" / "001.json").read_text())
        self.assertEqual(res["status"], "blocked")
        self.assertIn("chunk 2 of", res["judge_errors"][0]["evidence"])
        self.assertIn("max_tokens_exceeded", res["judge_errors"][0]["evidence"])
        self.assertFalse(ev.called)


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
