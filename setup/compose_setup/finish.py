"""FinishScreen: setup's ending from fc_finish.finish, run in a worker."""
from typing import List, Tuple

import fc_finish
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static


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
        color: $error;
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
        if line == "compose is ready" or line.startswith("implementer "):
            return "success"
        if "not finished" in line or "missing" in line or " key" in line:
            return "error"
        return ""

    def _show(self, lines: List[str], code: int) -> None:
        self.code = code
        self.query("#loading").remove()
        if code == 0:
            buttons = [Button("Done", id="done")]
        else:
            keys_case = not any("Claude Code is missing" in line for line in lines)
            buttons = [Button("Back to keys", id="keys")] if keys_case else []
            buttons.append(Button("Quit", id="quit"))
        self.mount(
            VerticalScroll(
                *(Static(line, classes=self._kind(line)) for line in lines),
                id="lines",
            ),
            Horizontal(*buttons, id="buttons"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "keys":
            self.dismiss("keys")
        else:
            self.app.exit(self.code)
