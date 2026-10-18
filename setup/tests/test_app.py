import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import hermetic  # first: no test sees the real home
import html, json, os, re, threading, unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from textual.app import App
from textual.widgets import Button

from compose_setup import app as setup_app
from compose_setup.finish import FinishScreen
from compose_setup.keys import KeysScreen
import fc_config, fc_finish, fc_herdrconf, fc_keys, fc_steprun, fc_steps

ROOT = Path(__file__).resolve().parents[2]
ROWS = tuple((name, lambda c: (False, ""), "true", level, False, mode) for name, level, mode in (
    ("gh", "required", "run"), ("figma", "designer", "run"), ("brew", "default", "interactive"),
    ("pi", "required", "run"), ("token", "designer", "run")))  # token stays unchosen
STATES = {"figma": ("done", ""), "brew": ("ok", ""), "pi": ("failed", "boom line")}


async def until(pilot, cond):
    for _ in range(100):
        if cond(): return
        await pilot.pause(0.05)

def lines(app):  # the screen's text, one string per line
    out = {}
    for n, t in re.findall(r'clip-path="url\(#[^"]*-line-(\d+)\)"[^>]*>([^<]*)</text>', app.export_screenshot()):
        out[int(n)] = out.get(int(n), "") + html.unescape(t).replace("\xa0", " ")
    return [out[n].rstrip() for n in sorted(out)]

def key(app, word):  # the footer key whose description names the action
    return next(k for k, b in app.active_bindings.items() if word in (b.binding.description or "").lower())


class GuidedSetup(unittest.IsolatedAsyncioTestCase):
    async def test_steps_then_keys_and_finish(self):
        log, suspended = [], []
        def run_step(row, checkout, yes, claude, terminal):
            log.append((row[0], terminal, bool(suspended))); return STATES[row[0]]
        @contextmanager
        def suspend(app):
            suspended.append(1); yield; suspended.pop()
        with mock.patch.object(fc_steps, "STEPS", ROWS), mock.patch.object(App, "suspend", suspend), mock.patch.object(fc_steprun, "run_step", run_step), \
                mock.patch.object(fc_herdrconf, "apply_herdr_config", side_effect=lambda *a: log.append("herdr") or ("ok", [])), \
                mock.patch.object(fc_keys, "key_status", return_value=dict.fromkeys(("openrouter", "typesafe", "linear", "figma"), False)), \
                mock.patch.object(fc_keys, "linear_connected", return_value=None), mock.patch.object(fc_finish, "finish", return_value=(["all set"], 0)):
            app = setup_app.SetupApp(ROOT)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                text = html.unescape("".join(re.findall(r">([^<>]*)</text>", app.export_screenshot()))).replace("\xa0", " ")
                for name, _, _, level, _, _ in ROWS: self.assertRegex(text, rf"\b{name}\b.*\b{level}\b")
                await pilot.press(key(app, "skip"), "down", key(app, "choose"), key(app, "start"))
                await until(pilot, lambda: isinstance(app.screen, KeysScreen))
                self.assertEqual(log, [("figma", False, False), ("brew", True, True), ("pi", False, False)])
                for _ in range(2):  # Back to keys returns to KeysScreen, then finishes again without rerunning anything
                    app.screen.dismiss(([], ["openrouter"])); await until(pilot, lambda: isinstance(app.screen, FinishScreen))
                    self.assertEqual([r for r in app.screen.results if r[0] != "token"], [("gh", "skipped"), ("figma", "done"), ("brew", "ok"), ("pi", "failed")])
                    app.screen.dismiss("keys"); await until(pilot, lambda: isinstance(app.screen, KeysScreen))
                self.assertNotIn("herdr", log)  # the ending applies herdr's config, not the steps
                app.exit(4)
            self.assertEqual(app.return_value, 4)

    def test_main_runs_this_checkout_and_exits_with_its_code(self):
        with mock.patch.object(setup_app.SetupApp, "run", autospec=True, return_value=4) as run, self.assertRaises(SystemExit) as cm:
            setup_app.main()
        self.assertEqual(cm.exception.code, 4); self.assertEqual(Path(run.call_args.args[0].checkout).resolve(), ROOT)


class AppFixes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):  # hermetic gave this test a temp HOME and COMPOSE_CONFIG; a second workspace is active there
        cfg = Path(os.environ["COMPOSE_CONFIG"])
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"workspace": "work", "workspaces": {"work": {}}}))
        rows = tuple((n, lambda c: (False, ""), "true", level, False, "run") for n, level in (("gh", "required"), ("figma", "designer"), ("uv", "default")))
        self.status, self.herdr = mock.Mock(return_value=dict.fromkeys(("openrouter", "typesafe", "linear", "figma"), False)), mock.Mock(return_value=("ok", []))
        self.finish = mock.Mock(return_value=(["not finished"], 3))
        for p in (mock.patch.object(fc_config, "CONFIG_PATH", cfg), mock.patch.object(fc_config, "AUTH_PATH", cfg.parent / "auth.json"),
                  mock.patch.object(fc_steps, "STEPS", rows), mock.patch.object(fc_steprun, "run_step", return_value=("ok", "")),
                  mock.patch.object(fc_herdrconf, "apply_herdr_config", self.herdr), mock.patch.object(fc_keys, "key_status", self.status),
                  mock.patch.object(fc_keys, "linear_connected", return_value=None), mock.patch.object(fc_finish, "finish", self.finish)):
            p.start(); self.addCleanup(p.stop)

    async def start(self, app, pilot):
        await pilot.press(key(app, "start")); await until(pilot, lambda: isinstance(app.screen, KeysScreen))

    async def test_keys_get_the_active_workspace_and_herdr_is_left_to_finish(self):
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await self.start(app, pilot)
            app.screen.dismiss(([], [])); await until(pilot, lambda: isinstance(app.screen, FinishScreen) and app.screen.query(Button))
            app.screen.dismiss("keys"); await until(pilot, lambda: isinstance(app.screen, KeysScreen))
            self.assertGreaterEqual(self.status.call_count, 2); self.assertEqual({c.args[1] for c in self.status.call_args_list}, {"work"})
            self.herdr.assert_not_called()

    async def test_ctrl_q_exits_1_until_finish_shows_a_code(self):
        for stage, code, want in (("steps", 3, 1), ("keys", 3, 1), ("loading", 3, 1), ("finish", 3, 3), ("finish", 0, 0)):
            with self.subTest(stage, code=code):
                self.finish.return_value, gate = (["done"], code), threading.Event()  # "loading": finish holds until the app has quit
                self.finish.side_effect = (lambda *a, g=gate, c=code, **k: g.wait(5) and (["done"], c)) if stage == "loading" else None
                app = setup_app.SetupApp(ROOT)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    if stage != "steps": await self.start(app, pilot)
                    if stage in ("loading", "finish"): app.screen.dismiss(([], [])); await until(pilot, lambda a=app, s=stage: isinstance(a.screen, FinishScreen) and (s == "loading" or a.screen.query(Button)))
                    self.assertIn("quit", (app.active_bindings["ctrl+q"].binding.description or "").lower())
                    await pilot.press("ctrl+q"); gate.set()
                self.assertEqual(app.return_value, want)

    async def test_s_undoes_a_skip_and_the_reason_line_survives_start(self):
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); before = lines(app)
            await pilot.press(key(app, "skip")); skipped = lines(app)
            reason = [l for l in skipped if l not in before]
            self.assertGreaterEqual(len(reason), 2)  # the gh row's state and its reason line
            await pilot.press(key(app, "skip")); self.assertEqual(lines(app), before)
            await pilot.press("down", key(app, "skip"), key(app, "skip")); self.assertEqual(lines(app), before)  # figma: unchosen again
            await pilot.press("up", key(app, "skip")); self.assertEqual(lines(app), skipped)
            await self.start(app, pilot); app.pop_screen(); await pilot.pause()
            for l in reason: self.assertIn(l, lines(app))


LOOK = tuple((n, lambda c: (False, ""), cmd, level, False, mode) for n, level, mode, cmd in (
    ("gh", "required", "run", "true"), ("figma", "designer", "run", "true"), ("token", "designer", "run", "true"),
    ("uvtool", "default", "run", "true"), ("brew", "default", "interactive", "fetch-tool --now"), ("longrow", "required", "run", "true")))
DETAIL = "boom " + " ".join(f"word{i}" for i in range(40)) + " TAILWORD"
CLEAR = r"\x1b(\[[0-3]?J|c)"

def style_after(app, row, word):  # the style of word on the first screen row that holds row before it
    for strip in app.screen._compositor.render_strips():
        col = strip.text.find(word, strip.text.find(row)) if row in strip.text else -1
        for seg in strip if col >= 0 else ():
            if col < len(seg.text): return seg.style
            col -= len(seg.text)


class StepsLook(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        AppFixes.setUp(self)
        self.tty, self.checked = Path(os.environ["HOME"]) / "tty", []
        def check(row, checkout): self.checked.append((row[0], Path(checkout))); return row[0] in ("gh", "figma"), ""
        def run_step(row, checkout, yes, claude, terminal):
            if row[0] == "brew": sys.stdout.flush(); os.write(1, b"<RUN>")
            return {"brew": ("done", ""), "longrow": ("failed", DETAIL)}.get(row[0], ("ok", ""))
        @contextmanager
        def suspend(app):  # the terminal while the app is away: fd 1 and sys.stdout both land in self.tty
            saved, old, fd = os.dup(1), (sys.stdout, sys.__stdout__), os.open(self.tty, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            os.dup2(fd, 1); os.close(fd); sys.stdout = sys.__stdout__ = open(os.dup(1), "w")
            try: yield
            finally: sys.stdout.close(); sys.stdout, sys.__stdout__ = old; os.dup2(saved, 1); os.close(saved)
        for p in (mock.patch.object(fc_steps, "STEPS", LOOK), mock.patch.object(fc_steps, "check", check),
                  mock.patch.object(fc_steprun, "run_step", run_step), mock.patch.object(App, "suspend", suspend)):
            p.start(); self.addCleanup(p.stop)

    async def test_real_states_header_wrapped_lines_colours_and_framed_interactive_step(self):
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await app.workers.wait_for_complete(); await pilot.pause()
            self.assertEqual(sorted(self.checked), sorted((r[0], ROOT) for r in LOOK))
            screen = lines(app)
            for name, state in (("gh", "ok"), ("figma", "ok"), ("token", "unchosen"), ("uvtool", "pending"), ("brew", "pending")):
                self.assertTrue(any(re.search(rf"\b{name}\b.*\b{state}\b", l) for l in screen), (name, state, screen))
            head = screen[:next(i for i, l in enumerate(screen) if re.search(r"\bgh\b", l))]
            terms = (r"install", r"configur", r"\bs\b", r"\bc\b", r"\br\b", r"move|↑|↓", r"required", r"default", r"designer")
            for t in terms: self.assertRegex(" ".join(head).lower(), t)
            hits = [i for i, l in enumerate(head) if any(re.search(t, l.lower()) for t in terms)]
            self.assertLessEqual(hits[-1] - hits[0], 2, head)
            await pilot.press("down", "down", "down", key(app, "skip"), key(app, "start"))
            await until(pilot, lambda: isinstance(app.screen, KeysScreen)); app.pop_screen(); await pilot.pause()
            screen = lines(app); n = next(l for l in screen if "longrow" in l).index("longrow")
            detail = [l for l in screen if re.search(r"boom|word\d|TAILWORD", l)]
            self.assertIn(DETAIL, " ".join(l.strip() for l in detail), screen)
            for l in detail: self.assertTrue(n <= len(l) - len(l.lstrip()) <= detail[0].index("boom"), (n, l))
            skipped, failed, error = style_after(app, "uvtool", "skipped"), style_after(app, "longrow", "failed"), style_after(app, "boom", "boom")
            self.assertTrue(skipped and failed and error); self.assertNotIn(skipped.color, (failed.color, error.color))
        before, run, after = self.tty.read_text().partition("<RUN>")
        self.assertTrue(run); self.assertRegex(before, rf"(?s){CLEAR}.*brew[^\n]*fetch-tool --now"); self.assertRegex(after, CLEAR)


class ScreenKeys(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        AppFixes.setUp(self)
        rows = tuple((n, lambda c: (False, ""), "true", level, False, "run") for n, level in (("gh", "required"), ("uv", "default"), ("figma", "designer")))
        self.run_step = mock.Mock(return_value=("done", ""))
        for p in (mock.patch.object(fc_steps, "STEPS", rows), mock.patch.object(fc_steprun, "run_step", self.run_step)):
            p.start(); self.addCleanup(p.stop)

    async def visit(self, stage, keys):  # choose figma and start with c and r, press keys on stage, return the steps screen's lines
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await pilot.press("down", "down", "c", "r")
            await until(pilot, lambda: isinstance(app.screen, KeysScreen))
            self.assertEqual([c.args[0][0] for c in self.run_step.call_args_list[-3:]], ["gh", "uv", "figma"])
            if stage is FinishScreen: app.screen.dismiss(([], [])); await until(pilot, lambda: isinstance(app.screen, FinishScreen) and app.screen.query(Button))
            app.screen.query(Button).first().focus(); await pilot.pause()
            screen, calls = app.screen, self.run_step.call_count
            await pilot.press(*keys); await app.workers.wait_for_complete(); await pilot.pause()
            self.assertIs(app.screen, screen); self.assertEqual(self.run_step.call_count, calls)
            self.assertFalse({"s", "c", "r"} & set(app.active_bindings))
            footer = " ".join(b.binding.description or "" for b in app.active_bindings.values()) + lines(app)[-1]
            self.assertNotRegex(footer.lower(), r"skip|choose|start")
            while len(app.screen_stack) > 1: app.pop_screen()
            await pilot.pause(); steps = lines(app)
            await pilot.press("s"); self.assertNotEqual(lines(app), steps)  # back on the steps screen s skips figma again
            return steps

    async def test_s_c_r_act_only_on_the_steps_screen(self):
        for stage in (KeysScreen, FinishScreen):
            with self.subTest(stage.__name__):
                self.assertEqual(await self.visit(stage, ("s", "c", "r")), await self.visit(stage, ()))


class LateCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):  # every startup check passes, but only once self.checks is set
        AppFixes.setUp(self)
        self.checks, self.running = threading.Event(), threading.Event()
        self.addCleanup(self.checks.set); self.addCleanup(self.running.set)
        def run_step(row, checkout, yes, claude, terminal):
            if row[0] == "held": self.running.wait(10)
            return {"broke": ("failed", "boom line")}.get(row[0], ("done", ""))
        for p in (mock.patch.object(fc_steps, "check", lambda row, c: (self.checks.wait(10), "")),
                  mock.patch.object(fc_steprun, "run_step", run_step)):
            p.start(); self.addCleanup(p.stop)

    def rows(self, *spec):
        p = mock.patch.object(fc_steps, "STEPS", tuple((n, lambda c: (False, ""), "true", level, False, "run") for n, level in spec))
        p.start(); self.addCleanup(p.stop)

    def shows(self, app, name, state):
        return any(re.search(rf"\b{name}\b.*\b{state}\b", l) for l in lines(app))

    async def release(self, app, pilot, late):  # pass the checks; only the rows in late may change
        before = lines(app); self.checks.set()
        await until(pilot, lambda: all(self.shows(app, n, "ok") for n in late)); await pilot.pause(0.2)
        after = lines(app)
        self.assertEqual(len(before), len(after), (before, after))
        changed = [(b, a) for b, a in zip(before, after) if b != a]
        self.assertTrue(changed and all(any(n in a for n in late) for b, a in changed), (before, after))

    async def test_skipped_and_chosen_rows_keep_their_state(self):
        self.rows(("gh", "required"), ("figma", "designer"), ("token", "designer"), ("uv", "default"))
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await pilot.press(key(app, "skip"), "down", key(app, "choose")); await pilot.pause()
            self.assertTrue(self.shows(app, "gh", "skipped") and self.shows(app, "figma", "chosen"))
            await self.release(app, pilot, ("token", "uv"))  # pending and unchosen rows still turn ok
            self.assertTrue(self.shows(app, "gh", "skipped") and self.shows(app, "figma", "chosen"))

    async def test_running_done_and_failed_rows_keep_their_state_and_results(self):
        self.rows(("fine", "required"), ("broke", "default"), ("held", "default"), ("last", "default"))
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await pilot.press(key(app, "start"))
            await until(pilot, lambda: self.shows(app, "held", "running"))
            await self.release(app, pilot, ("last",))
            for name, state in (("fine", "done"), ("broke", "failed"), ("held", "running")): self.assertTrue(self.shows(app, name, state), lines(app))
            self.assertIn("boom line", "\n".join(lines(app)))
            self.running.set(); await until(pilot, lambda: isinstance(app.screen, KeysScreen))
            app.screen.dismiss(([], [])); await until(pilot, lambda: isinstance(app.screen, FinishScreen))
            self.assertEqual(app.screen.results, [("fine", "done"), ("broke", "failed"), ("held", "done"), ("last", "done")])


P1 = "/Users/someone/workspace/tools/compose/.treehouse/compose-fdfef9/1/compose/.compose/easy-install/bin/compose"
PATHS = f"dangling link {P1} -> /Users/me/.local/bin/cmp"  # 150 characters
INSTALL = f"ln -sf {P1} /Users/someone/.local/bin/compose"


class PathWrap(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        AppFixes.setUp(self)
        rows = tuple((n, lambda c: (False, ""), cmd, "required", False, "run") for n, cmd in (("hand", INSTALL), ("linker", "true"), ("blank", "true"), ("after", "true")))
        states = {"linker": ("failed", PATHS), "blank": ("failed", ""), "after": ("done", "")}
        for p in (mock.patch.object(fc_steps, "STEPS", rows), mock.patch.object(fc_steps, "check", lambda row, c: (False, "")),
                  mock.patch.object(fc_steprun, "run_step", lambda row, *a: states[row[0]])):
            p.start(); self.addCleanup(p.stop)

    def block(self, screen, name):  # the rendered rows under the row named name, up to the next row
        i = next(i for i, l in enumerate(screen) if re.search(rf"\b{name}\b", l)); n = screen[i].index(name)
        out = []
        for l in screen[i + 1:-1]:
            if not l.strip() or any(l[n:].startswith(r) for r in ("hand", "linker", "blank", "after")): break
            out.append(l)
        return n, out

    def assertBreaksClean(self, text, rows, n):
        pos = 0
        for l in rows:
            self.assertTrue(n <= len(l) - len(l.lstrip()) <= len(rows[0]) - len(rows[0].lstrip()), (n, rows))
            self.assertTrue(text.startswith(l.strip(), pos), (text[pos:], rows)); pos += len(l.strip())
            if pos < len(text):  # every row ends at a space or right after a slash
                self.assertTrue(text[pos] == " " or text[pos - 1] == "/", (l, rows)); pos += text[pos] == " "
        self.assertEqual(pos, len(text), rows)

    async def test_long_path_details_break_at_a_space_or_after_a_slash(self):
        self.assertEqual(len(PATHS), 150)
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await app.workers.wait_for_complete()
            await pilot.press(key(app, "skip"), key(app, "start"))
            await until(pilot, lambda: isinstance(app.screen, KeysScreen)); app.pop_screen(); await pilot.pause()
            screen = lines(app)
            n, rows = self.block(screen, "linker")
            self.assertGreaterEqual(len(rows), 2, screen); self.assertBreaksClean(PATHS, rows, n)
            n, rows = self.block(screen, "hand")
            self.assertGreaterEqual(len(rows), 2, screen); self.assertBreaksClean(f"compose stops working without it; by hand: {INSTALL}", rows, n)
            self.assertEqual(self.block(screen, "blank")[1], [], screen)  # an empty detail shows no detail row
            self.assertTrue(any(re.search(r"\bblank\b.*\bfailed\b", l) for l in screen), screen)
