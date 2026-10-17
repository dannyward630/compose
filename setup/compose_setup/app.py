"""SetupApp: the steps screen, the herdr config, KeysScreen, then FinishScreen."""
import shutil
from pathlib import Path
from typing import List, Set, Tuple

import fc_config, fc_herdrconf, fc_keys, fc_steprun, fc_steps
from textual.app import App, ComposeResult

from .finish import FinishScreen
from .keys import KeysScreen
from textual.widgets import Footer, Label, ListItem, ListView


STATE_TEXT = {"claude": "waiting on Claude Code"}


class SetupApp(App[int]):
    """The guided setup for the compose checkout at checkout; exits with setup's code."""
    CSS_PATH = "setup.tcss"

    BINDINGS = [
        ("s", "skip", "skip"),
        ("c", "choose", "choose"),
        ("r", "start", "start"),
    ]

    def __init__(self, checkout: Path):
        super().__init__()
        self.checkout = checkout
        self.rows = fc_steps.STEPS
        self.results: List[Tuple[str, str]] = []
        self.skipped: Set[int] = set()
        self.chosen: Set[int] = set()
        self._labels: List[Label] = []

    def compose(self) -> ComposeResult:
        yield Label(f"compose setup: {len(self.rows)} steps", id="title")
        with ListView(id="steps"):
            for i, row in enumerate(self.rows):
                state = "unchosen" if row[3] == "designer" else "pending"
                label = Label(self._row_text(i, state), classes=f"row {state}")
                self._labels.append(label)
                with ListItem():
                    yield label
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#steps", ListView).focus()

    def _row_text(self, i: int, state: str, line: str = "") -> str:
        name, level = self.rows[i][0], self.rows[i][3]
        text = f"{name:<28}{level:<9}{STATE_TEXT.get(state, state)}"
        return f"{text}\n  {line}" if line else text

    def _set_row(self, i: int, state: str, line: str = "") -> None:
        self._labels[i].update(self._row_text(i, state, line))
        self._labels[i].set_classes(f"row {state}")
        if state == "running":
            self.query_one("#steps", ListView).index = i

    def action_skip(self) -> None:
        i = self.query_one("#steps", ListView).index
        self.skipped.add(i)
        self.chosen.discard(i)
        name, _, install, level, _, mode = self.rows[i]
        line = ""
        if level == "required":
            if mode == "key":
                kind = next((k for k in ("openrouter", "typesafe", "linear", "figma") if k in name.lower()), "")
                line = fc_keys.skipped_line(kind, fc_config.WORKSPACE) or ""
            else:
                line = f"compose stops working without it; by hand: {install}"
        self._set_row(i, "skipped", line)

    def action_choose(self) -> None:
        i = self.query_one("#steps", ListView).index
        if self.rows[i][3] != "designer":
            return
        self.chosen.add(i)
        self.skipped.discard(i)
        self._set_row(i, "chosen", "")

    def action_start(self) -> None:
        self.run_worker(self._run_steps, thread=True, exclusive=True)

    def _run_steps(self) -> None:
        claude = shutil.which("claude") is not None
        results = []
        for i, row in enumerate(self.rows):
            level, mode = row[3], row[5]
            if i in self.skipped or (level == "designer" and i not in self.chosen):
                state, line = "skipped", ""
            else:
                self.call_from_thread(self._set_row, i, "running")
                if mode == "interactive":
                    state, line = self.call_from_thread(self._run_interactive, row, claude)
                else:
                    state, line = fc_steprun.run_step(row, self.checkout, False, claude, False)
            results.append((row[0], state))
            self.call_from_thread(self._set_row, i, state, line)
        fc_herdrconf.apply_herdr_config(Path.home() / ".config" / "herdr" / "config.toml", self.checkout / "setup" / "herdr.toml")
        self.call_from_thread(self._show_keys, results)

    def _run_interactive(self, row, claude: bool):
        with self.suspend():
            return fc_steprun.run_step(row, self.checkout, False, claude, True)

    def _show_keys(self, results: List[Tuple[str, str]]) -> None:
        self.results = results
        self.push_screen(KeysScreen(), self._after_keys)

    def _after_keys(self, _result) -> None:
        self.push_screen(FinishScreen(self.results), self._after_finish)

    def _after_finish(self, result) -> None:
        if result == "keys":
            self.push_screen(KeysScreen(), self._after_keys)


def main() -> None:
    """Run SetupApp on the checkout this package lives in and exit with its code."""
    raise SystemExit(SetupApp(Path(__file__).resolve().parents[2]).run())
