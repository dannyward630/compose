"""FinishScreen: setup's ending from fc_finish.finish, run in a worker."""
import re
from typing import List, Tuple

import fc_finish
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static

from .wrap import Wrapped


class FinishScreen(Screen[str]):
    """results is the [(row name, state)] of the steps run; dismisses with "keys" for Back to keys, else exits the app with the code."""

    DEFAULT_CSS = """
    FinishScreen #loading, FinishScreen #buttons {
        height: auto;
    }
    FinishScreen #loading LoadingIndicator {
        width: auto;
        height: auto;
    }
    FinishScreen #loading Static {
        margin-left: 1;
    }
    FinishScreen .success {
        color: $success;
    }
    FinishScreen .error {
        color: $text-error;
    }
    FinishScreen .failed {
        color: $text-error;
        text-style: bold;
    }
    FinishScreen .warning {
        color: $warning;
    }
    """

    def __init__(self, results: List[Tuple[str, str]]):
        super().__init__()
        self.results = results

    def compose(self) -> ComposeResult:
        with Horizontal(id="loading"):
            yield LoadingIndicator()
            yield Static("checking your model…")

    def on_mount(self) -> None:
        self.run_worker(self._run, thread=True)

    def _run(self) -> None:
        lines, code = fc_finish.finish(self.results, yes=False)
        self.app.call_from_thread(self._show, lines, code)

    @staticmethod
    def _kind(line: str) -> str:
        if line.startswith("failed: "):
            return "failed"
        if (
            line.startswith(("waiting on Claude Code: ", "run by hand: ", "skipped: ", "[", "export "))
            or re.fullmatch(r"\s*[\w.-]+ = \S+", line)
            or "set these lines by hand" in line
            or "add this line" in line
        ):
            return "warning"
        if line == "compose is ready" or line.startswith("implementer "):
            return "success"
        if line.startswith("No ") or "not finished" in line or "missing" in line:
            return "error"
        return ""

    async def _show(self, lines: List[str], code: int) -> None:
        self.code = code
        self.query("#loading").remove()
        if code == 0:
            buttons = [Button("Done", id="done")]
        else:
            keys_case = not any("Claude Code is missing" in line for line in lines)
            buttons = [Button("Back to keys", id="keys")] if keys_case else []
            buttons.append(Button("Quit", id="quit"))
        lines_area = VerticalScroll(
                *(Wrapped(line, classes=self._kind(line), markup=False) for line in lines),
                id="lines",
        )
        await self.mount(lines_area, Horizontal(*buttons, id="buttons"))
        lines_area.focus()
        lines_area.scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "keys":
            self.dismiss("keys")
        else:
            self.app.exit(self.code)
