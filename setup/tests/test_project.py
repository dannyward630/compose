import unittest
from importlib import metadata
from pathlib import Path

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Input, Static


class Ask(Screen):
    def compose(self) -> ComposeResult:
        yield Input(id="name")
        yield Button("Save", id="save")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one("#name", Input).value)


class Host(App[int]):
    def compose(self) -> ComposeResult:
        yield Static("home", id="home")

    def on_mount(self) -> None:
        self.push_screen(Ask(), self.done)

    def done(self, result: str) -> None:
        self.result = result
        self.exit(3)


class Project(unittest.IsolatedAsyncioTestCase):
    def test_textual_is_the_pinned_version(self):
        self.assertEqual(metadata.version("textual"), "8.2.8")

    def test_package_puts_bin_on_path(self):
        import compose_setup  # noqa: F401
        import fc_core

        root = Path(__file__).resolve().parents[2]
        self.assertEqual(Path(fc_core.__file__).resolve(), root / "bin" / "fc_core.py")

    async def test_pilot_drives_a_screen_headless(self):
        app = Host()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, Ask)
            await pilot.click("#name")
            await pilot.press("a", "b")
            await pilot.click("#save")
            await pilot.pause()
        self.assertEqual(app.result, "ab")
        self.assertEqual(app.return_value, 3)


if __name__ == "__main__":
    unittest.main()
