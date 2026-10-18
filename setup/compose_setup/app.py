"""SetupApp: the steps screen, the herdr config, KeysScreen, then FinishScreen."""
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import fc_config, fc_keys, fc_steprun, fc_steps
from textual.app import App, ComposeResult

from .finish import FinishScreen
from .keys import KeysScreen
from .wrap import Wrapped
from textual.widgets import Footer, Label, ListItem, ListView


HEADER = (
    "compose setup installs and configures what compose needs.\n"
    "Move with ↑/↓, skip with s, choose with c, start with r.\n"
    "required: needed  default: on unless skipped  designer: only if you choose it"
)
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
        self.states: Dict[int, str] = {}
        self._lines: Dict[int, str] = {}
        self._labels: List[Label] = []
        self._details: List[Wrapped] = []

    def compose(self) -> ComposeResult:
        yield Label(HEADER, id="title")
        with ListView(id="steps"):
            for i, row in enumerate(self.rows):
                state = "unchosen" if row[3] == "designer" else "pending"
                self.states[i] = state
                label = Label(self._row_text(i, state), classes=f"row {state}")
                self._labels.append(label)
                detail = Wrapped("", classes="detail")
                detail.display = False
                self._details.append(detail)
                with ListItem():
                    yield label
                    yield detail
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#steps", ListView).focus()
        self.run_worker(self._check_rows, thread=True, group="check")

    def _check_rows(self) -> None:
        for i, row in enumerate(self.rows):
            if fc_steps.check(row, self.checkout)[0]:
                self.call_from_thread(self._mark_ok, i)

    def _mark_ok(self, i: int) -> None:
        if self.states.get(i) in ("pending", "unchosen"):
            self._set_row(i, "ok")

    def _row_text(self, i: int, state: str, line: str = "") -> str:
        name, level = self.rows[i][0], self.rows[i][3]
        text = f"{name:<28}{level:<9}{STATE_TEXT.get(state, state)}"
        return text

    def _set_row(self, i: int, state: str, line: str = "") -> None:
        self.states[i] = state
        self._labels[i].update(self._row_text(i, state, line))
        self._labels[i].set_classes(f"row {state}")
        self._details[i].update(line)
        self._details[i].set_classes(f"detail {state}")
        self._details[i].display = bool(line)
        if state == "running":
            self.query_one("#steps", ListView).index = i

    def check_action(self, action: str, parameters) -> bool:
        if action in ("skip", "choose", "start"):
            return len(self.screen_stack) == 1
        return True

    def action_skip(self) -> None:
        i = self.query_one("#steps", ListView).index
        if i in self.skipped:
            self.skipped.discard(i)
            self._set_row(i, "unchosen" if self.rows[i][3] == "designer" else "pending")
            return
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
        self._lines[i] = line
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

    def action_quit(self) -> None:
        self.exit(getattr(self.screen, "code", 1))

    def _run_steps(self) -> None:
        claude = shutil.which("claude") is not None
        results = []
        for i, row in enumerate(self.rows):
            level, mode = row[3], row[5]
            if i in self.skipped or (level == "designer" and i not in self.chosen):
                state, line = "skipped", self._lines.get(i, "")
            else:
                self.call_from_thread(self._set_row, i, "running")
                if mode == "interactive":
                    state, line = self.call_from_thread(self._run_interactive, row, claude)
                else:
                    state, line = fc_steprun.run_step(row, self.checkout, False, claude, False)
            results.append((row[0], state))
            self.call_from_thread(self._set_row, i, state, line)
        self.call_from_thread(self._show_keys, results)

    def _run_interactive(self, row, claude: bool):
        with self.suspend():
            sys.stdout.write(f"\x1b[2J\x1b[H{row[0]}: {row[2]}\n")
            sys.stdout.flush()
            try:
                return fc_steprun.run_step(row, self.checkout, False, claude, True)
            finally:
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.flush()

    def _show_keys(self, results: List[Tuple[str, str]]) -> None:
        self.results = results
        self.push_screen(KeysScreen(fc_config.settings(fc_config.read_config())[0]), self._after_keys)

    def _after_keys(self, _result) -> None:
        self.push_screen(FinishScreen(self.results), self._after_finish)

    def _after_finish(self, result) -> None:
        if result == "keys":
            self.push_screen(KeysScreen(fc_config.settings(fc_config.read_config())[0]), self._after_keys)


def main() -> None:
    """Run SetupApp on the checkout this package lives in and exit with its code."""
    raise SystemExit(SetupApp(Path(__file__).resolve().parents[2]).run())
