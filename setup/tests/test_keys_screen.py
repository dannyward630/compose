import contextlib, re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import hermetic  # noqa: F401  first: temp HOME and COMPOSE_CONFIG, no key variables
from unittest import mock
from textual.app import App
from textual.widgets import Button, Input, Static

from compose_setup.keys import KeysScreen
import fc_auth, fc_keys

LABELS = {"openrouter": "OpenRouter", "typesafe": "TypeSafe", "linear": "Linear", "figma": "Figma"}
REQUIRED = {"openrouter", "typesafe", "linear"}

class Host(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace, self.result = workspace, None
    def on_mount(self): self.push_screen(KeysScreen(self.workspace), self.done)
    def done(self, result): self.result = result


class KeysScreenTest(unittest.IsolatedAsyncioTestCase):
    async def keys(self, status, connected, typed={}, workspace="default", presses=1):
        saved = []
        def save(kind, value, workspace, framelink_env): saved.append((kind, value, workspace)); return f"saved {kind}"
        state = "key" if status[2] else "connector" if connected else "missing"
        with mock.patch.object(fc_auth, "read_auth", return_value={}), mock.patch.object(fc_keys, "key_status", return_value=dict(zip(LABELS, status))), \
             mock.patch.object(fc_keys, "linear_connected", return_value=connected), mock.patch.object(fc_keys, "linear_state", return_value=state), \
             mock.patch.object(fc_keys, "save_key", side_effect=save), mock.patch.object(fc_keys, "skipped_line", side_effect=lambda k, w: f"skip-{k}-{w}"):
            app = Host(workspace)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                inputs = list(app.screen.query(Input))
                self.assertTrue(len(inputs) == 4 and all(i.password and i.region.right <= 80 and i.region.bottom <= 24 for i in inputs))
                def beside(kind): return next(i for w in app.screen.query(Static) if LABELS[kind].lower() in str(w.render()).lower() for i in inputs if i.region.y <= w.region.y < i.region.bottom)
                self.assertEqual(len({id(beside(k)) for k in LABELS}), 4)
                for kind, value in typed.items(): beside(kind).focus(); await pilot.press(*value)
                for _ in range(presses):
                    await pilot.click(next(b for b in app.screen.query(Button) if "Continue" in str(b.label))); await pilot.pause()
                text = "" if app.result else "\n".join(str(w.render()) for w in app.screen.query(Static))
                self.assertFalse(any(v in text for v in typed.values()))
        return app.result, saved, text

    async def test_statuses_never_show_values(self):
        _, _, text = await self.keys((True, False, False, False), True, presses=0)
        self.assertIn("connector connected", text)
        self.assertEqual((text.count("not set"), len(re.findall(r"(?<!not )\bset\b", text))), (2, 1))

    async def test_continue_saves_non_empty_inputs_only(self):
        result, saved, _ = await self.keys((False, True, False, True), False, {"openrouter": "sk-or-test", "linear": "lin-test"}, "work")
        self.assertEqual(sorted(saved), [("linear", "lin-test", "work"), ("openrouter", "sk-or-test", "work")])
        self.assertEqual((sorted(result[0]), {"typesafe", "figma"} & set(result[1])), (["linear", "openrouter"], set()))

    async def test_missing_keys_warn_then_second_continue_skips(self):
        result, _, text = await self.keys((False,) * 4, False)
        self.assertEqual((result, [k for k in LABELS if f"skip-{k}-default" in text]), (None, ["openrouter", "typesafe", "linear"]))
        result, saved, _ = await self.keys((False,) * 4, False, presses=2)
        self.assertEqual((result[0], saved, REQUIRED <= set(result[1])), ([], [], True))

    async def test_set_keys_and_linear_connector_continue_at_once(self):
        result, saved, _ = await self.keys((True, True, False, False), True)
        self.assertEqual((result[0], saved, REQUIRED & set(result[1])), ([], [], set()))


HINTS = {"openrouter": "openrouter.ai/keys", "typesafe": "your TypeSafe account", "linear": "linear.app/settings/api", "figma": "a Figma personal access token"}


class KeysLook(unittest.IsolatedAsyncioTestCase):
    async def look(self, status, check, skip=lambda k, w: f"skip-{k}-{w}", presses=0):
        with mock.patch.object(fc_auth, "read_auth", return_value={}), mock.patch.object(fc_keys, "key_status", return_value=dict(zip(LABELS, status))), \
             mock.patch.object(fc_keys, "linear_connected", return_value=False), mock.patch.object(fc_keys, "linear_state", return_value="key" if status[2] else "missing"), \
             mock.patch.object(fc_keys, "save_key", return_value="saved"), mock.patch.object(fc_keys, "skipped_line", side_effect=skip):
            app = Host("default")
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                for _ in range(presses):
                    await pilot.click(next(b for b in app.screen.query(Button) if "Continue" in str(b.label))); await pilot.pause()
                await check(app, pilot, [s.text for s in app.screen._compositor.render_strips()])
        return app.result

    def rows(self, app, lines):
        inputs = list(app.screen.query(Input))
        tops = sorted([i.region.y for i in inputs] + [b.region.y for b in app.screen.query(Button) if "Continue" in str(b.label)])
        out = {}
        for kind, label in LABELS.items():
            y = next(n for n, line in enumerate(lines) if label in line)
            inp = next(i for i in inputs if i.region.y <= y < i.region.bottom)
            out[kind] = inp, lines[inp.region.y:next((t for t in tops if t > inp.region.y), len(lines))]
        return out

    async def test_marks_hints_columns_and_status_gap(self):
        async def check(app, pilot, lines):
            top = next(line for line in lines if line.strip())
            for kind, (inp, rows) in self.rows(app, lines).items():
                statics = " ".join(" ".join(str(w.render()).split()) for w in app.screen.query(Static) if inp.region.y <= w.region.y < inp.region.y + len(rows))
                text = " ".join(" ".join(rows).split()) + " | " + statics
                mark, other = ("optional", "required") if kind == "figma" else ("required", "optional")
                self.assertTrue(mark in text and other not in text, (kind, text))
                if kind == "linear": self.assertIn("required, or the claude.ai Linear connector", text)
                self.assertEqual(len([line for line in rows[inp.region.height:] if HINTS[kind] in line]), 1, (kind, rows))
                self.assertEqual(next(line for line in rows if LABELS[kind] in line).index(LABELS[kind]), len(top) - len(top.lstrip()), (top, rows))
                after = [line[inp.region.right:] for line in rows[:inp.region.height]]
                self.assertTrue(all(a[:1] in ("", " ") for a in after) and any(a.strip() for a in after), (kind, after))
        for status in ((False,) * 4, (True,) * 4): await self.look(status, check)

    async def test_continue_stays_on_screen_with_every_warning(self):
        async def check(app, pilot, lines):
            button = next(b for b in app.screen.query(Button) if "Continue" in str(b.label))
            r = button.region
            self.assertTrue(r.x >= 0 and r.y >= 0 and r.right <= 80 and r.bottom <= 24, r)
            self.assertIs(app.screen.get_widget_at(r.x + r.width // 2, r.y + r.height // 2)[0], button)
            warned = [(w, k) for w in app.screen.query(Static) for k in REQUIRED if f"skip-{k}-default" in str(w.render())]
            self.assertEqual({k for _, k in warned}, REQUIRED)
            if long: self.assertTrue(any(a.max_scroll_y > 0 for a in warned[0][0].ancestors_with_self if hasattr(a, "max_scroll_y")))
            await pilot.click(button); await pilot.pause()
        for long in (False, True):
            skip = (lambda k, w: f"skip-{k}-{w}" + "\nmore" * 6) if long else (lambda k, w: f"skip-{k}-{w}")
            result = await self.look((False,) * 4, check, skip, presses=1)
            self.assertTrue(result and result[0] == [] and REQUIRED <= set(result[1]), result)


class KeysKeyboard(unittest.IsolatedAsyncioTestCase):
    async def drive(self, status, steps):
        saved = []
        with mock.patch.object(fc_auth, "read_auth", return_value={}), mock.patch.object(fc_keys, "key_status", return_value=dict(zip(LABELS, status))), \
             mock.patch.object(fc_keys, "linear_connected", return_value=False), mock.patch.object(fc_keys, "linear_state", return_value="key" if status[2] else "missing"), \
             mock.patch.object(fc_keys, "save_key", side_effect=lambda k, v, w, f: saved.append((k, v)) or "saved"), \
             mock.patch.object(fc_keys, "skipped_line", side_effect=lambda k, w: f"skip-{k}-{w}"):
            app = Host("default")
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await steps(self, app, pilot, saved)
        return app.result, saved

    def inputs(self, app):
        return {kind: app.screen.query_one(f"#{kind}", Input) for kind in LABELS}

    async def test_opens_on_openrouter_and_enter_walks_kinds_to_continue(self):
        async def steps(self, app, pilot, saved):
            inputs = self.inputs(app)
            self.assertIs(app.focused, inputs["openrouter"])
            await pilot.press(*"sk-or-test")
            self.assertEqual([i.value for i in inputs.values()], ["sk-or-test", "", "", ""])
            for kind in ("typesafe", "linear", "figma"):
                await pilot.press("enter"); await pilot.pause()
                self.assertIs(app.focused, inputs[kind])
            await pilot.press("enter"); await pilot.pause()
            self.assertTrue(isinstance(app.focused, Button) and "Continue" in str(app.focused.label))
            self.assertEqual((saved, app.result), ([], None))
            await pilot.press("enter"); await pilot.pause()
            text = "\n".join(str(w.render()) for w in app.screen.query(Static))
            self.assertEqual((saved, app.result, [k for k in LABELS if f"skip-{k}-default" in text]), ([("openrouter", "sk-or-test")], None, ["typesafe", "linear"]))
            self.assertNotIn("sk-or-test", text)
            await pilot.press("enter"); await pilot.pause()
            self.assertEqual((app.result[0], set(app.result[1])), (["openrouter"], {"typesafe", "linear"}))
        await self.drive((False,) * 4, steps)

    async def test_enter_from_a_clicked_input_and_a_new_screen_refocuses(self):
        async def steps(self, app, pilot, saved):
            inputs = self.inputs(app)
            await pilot.click(inputs["linear"]); await pilot.press(*"lin-test", "enter"); await pilot.pause()
            self.assertIs(app.focused, inputs["figma"])
            await pilot.press("enter", "enter"); await pilot.pause()
            self.assertEqual((saved, app.result), ([("linear", "lin-test")], (["linear"], [])))
            app.push_screen(KeysScreen("default")); await pilot.pause()
            self.assertIs(app.focused, self.inputs(app)["openrouter"])
            await pilot.press(*"x")
            self.assertEqual([i.value for i in self.inputs(app).values()], ["x", "", "", ""])
        await self.drive((True, True, False, True), steps)


class WarningsInView(unittest.IsolatedAsyncioTestCase):
    async def warn(self, status=(False,) * 4, skip=None, workspace="default", whole=True):
        patches = [mock.patch.object(fc_auth, "read_auth", return_value={}), mock.patch.object(fc_keys, "key_status", return_value=dict(zip(LABELS, status))),
                   mock.patch.object(fc_keys, "linear_connected", return_value=False), mock.patch.object(fc_keys, "linear_state", return_value="key" if status[2] else "missing"),
                   mock.patch.object(fc_keys, "save_key", side_effect=AssertionError("nothing to save"))]
        missing = [k for k in LABELS if k in REQUIRED and not dict(zip(LABELS, status))[k]]
        texts = [(skip or fc_keys.skipped_line)(k, workspace) for k in missing] + ["Press Continue again to go on without the missing keys."]
        with contextlib.ExitStack() as stack:
            for p in patches + ([mock.patch.object(fc_keys, "skipped_line", side_effect=skip)] if skip else []): stack.enter_context(p)
            app = Host(workspace)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                button = app.screen.query_one("#continue", Button)
                await pilot.click(button); await pilot.pause(); await pilot.pause()
                self.assertIsNone(app.result)
                body = app.screen.query_one("#keys-body")
                view = body.scrollable_content_region
                shown = {t: next(w for w in body.query(Static) if t in str(w.render())) for t in texts}
                for t in texts if whole else texts[-1:]:
                    self.assertTrue(view.contains_region(shown[t].region), (t, shown[t].region, view, body.scroll_y))
                self.assertEqual(body.scroll_y, body.max_scroll_y)
                r = button.region
                self.assertTrue(r.x >= 0 and r.y >= 0 and r.right <= 80 and r.bottom <= 24 and not r.overlaps(view), (r, view))
                self.assertIs(app.screen.get_widget_at(r.x + r.width // 2, r.y + r.height // 2)[0], button)
                await pilot.click(button); await pilot.pause()
        self.assertEqual((app.result[0], set(app.result[1])), ([], set(missing)))
        return body

    async def test_every_real_warning_and_continue_again_line_in_view(self):
        await self.warn()

    async def test_long_workspace_name_still_shows_every_warning(self):
        await self.warn(workspace="client-acme-mobile-checkout-redesign")

    async def test_single_missing_key_shows_its_warning_and_the_last_line(self):
        await self.warn((True, False, True, False))

    async def test_warnings_taller_than_the_body_scroll_it_to_the_end(self):
        body = await self.warn(skip=lambda k, w: f"skip-{k}-{w}" + "\nmore" * 12, whole=False)
        self.assertGreater(body.max_scroll_y, 0)



class EnteredStatus(unittest.IsolatedAsyncioTestCase):
    async def test_typed_key_reads_entered_until_cleared_or_saved(self):
        saved = []
        with mock.patch.object(fc_auth, "read_auth", return_value={}), mock.patch.object(fc_keys, "key_status", return_value=dict(zip(LABELS, (False, True, False, False)))), \
             mock.patch.object(fc_keys, "linear_connected", return_value=True), mock.patch.object(fc_keys, "linear_state", return_value="connector"), \
             mock.patch.object(fc_keys, "save_key", side_effect=lambda k, v, w, f: saved.append((k, v)) or "saved"), \
             mock.patch.object(fc_keys, "skipped_line", side_effect=lambda k, w: f"skip-{k}-{w}"):
            app = Host("default")
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                def status(kind):
                    w = app.screen.query_one(f"#{kind}-status", Static)
                    return str(w.render()).strip(), "present" in w.classes, "absent" in w.classes
                async def keys(kind, *presses):
                    app.screen.query_one(f"#{kind}", Input).focus(); await pilot.press(*presses); await pilot.pause()
                before = {k: status(k) for k in LABELS}
                self.assertEqual(before, {"openrouter": ("not set", False, True), "typesafe": ("set", True, False),
                                          "linear": ("connector connected", True, False), "figma": ("not set", False, True)})
                for kind, value in (("openrouter", "sk-or-test"), ("typesafe", "ts-test"), ("linear", "lin-test")):
                    await keys(kind, *value)
                    self.assertEqual({k: status(k) for k in LABELS}, before | {kind: ("entered", True, False)}, kind)
                    await keys(kind, *["backspace"] * (len(value) - 1))
                    self.assertEqual(status(kind), ("entered", True, False), kind)
                    await keys(kind, "backspace")
                    self.assertEqual(status(kind), before[kind], kind)
                await keys("figma", *"   ")
                self.assertEqual((status("figma"), app.screen.query_one("#figma", Input).value), (("not set", False, True), "   "))
                await keys("figma", *["backspace"] * 3, *"fig-test")
                shown = "\n".join(str(w.render()) for w in app.screen.query(Static))
                self.assertEqual((status("figma"), "fig-" in shown), (("entered", True, False), False))
                await pilot.click(app.screen.query_one("#continue", Button)); await pilot.pause(); await pilot.pause()
                self.assertEqual((saved, app.result, status("figma"), status("openrouter")), ([("figma", "fig-test")], None, ("set", True, False), before["openrouter"]))
                await keys("openrouter", *"sk-or-test")
                self.assertEqual(status("openrouter"), ("entered", True, False))
                await pilot.click(app.screen.query_one("#continue", Button)); await pilot.pause()
        self.assertEqual((saved, app.result), ([("figma", "fig-test"), ("openrouter", "sk-or-test")], (["figma", "openrouter"], [])))
