"""KeysScreen: one masked input per key, presence beside it, never a value."""
from typing import List, Tuple

from textual.app import ComposeResult
from textual.containers import Grid
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static

import fc_auth, fc_config, fc_keys, fc_steps

KINDS = ("openrouter", "typesafe", "linear", "figma")
REQUIRED = ("openrouter", "typesafe", "linear")
LABELS = {"openrouter": "OpenRouter", "typesafe": "TypeSafe", "linear": "Linear", "figma": "Figma"}


class KeysScreen(Screen[Tuple[List[str], List[str]]]):
    """Keys for workspace; dismisses with (kinds saved, kinds skipped)."""

    DEFAULT_CSS = """
    KeysScreen {
        padding: 1 2;
    }
    KeysScreen Grid {
        height: auto;
        grid-size: 3 4;
        grid-columns: 14 1fr 22;
        grid-rows: 3;
    }
    KeysScreen Grid Label,
    KeysScreen Grid Static {
        height: 3;
        content-align: left middle;
    }
    KeysScreen #continue {
        margin-top: 1;
    }
    KeysScreen .present {
        color: $success;
    }
    KeysScreen .absent {
        color: $text-muted;
    }
    KeysScreen .skipped {
        color: $error;
    }
    """

    def __init__(self, workspace: str = "default"):
        super().__init__()
        self.workspace = workspace
        self.status = fc_keys.key_status(fc_auth.read_auth(fc_config.AUTH_PATH), self.workspace, fc_steps.FRAMELINK_ENV)
        self.state = fc_keys.linear_state(self.status, fc_keys.linear_connected())
        self.saved: List[str] = []
        self.warned = False

    def compose(self) -> ComposeResult:
        yield Label(f"Keys for workspace {self.workspace}", id="title")
        with Grid():
            for kind in KINDS:
                yield Label(LABELS[kind], classes="key-label")
                yield Input(password=True, id=kind)
                text, state_class = self._status(kind)
                yield Static(text, classes=f"key-status {state_class}", id=f"{kind}-status")
        button = Button("Continue", id="continue")
        button.active_effect_duration = 0
        yield button

    def _status(self, kind: str) -> Tuple[str, str]:
        """The presence line beside a key, and its color class; never a value."""
        if self.status[kind]:
            return "set", "present"
        if kind == "linear" and self.state == "connector":
            return "connector connected", "present"
        return "not set", "absent"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for kind in KINDS:
            value = self.query_one(f"#{kind}", Input).value.strip()
            if not value:
                continue
            fc_keys.save_key(kind, value, self.workspace, fc_steps.FRAMELINK_ENV)
            self.status[kind] = True
            if kind not in self.saved:
                self.saved.append(kind)
            self.query_one(f"#{kind}", Input).value = ""
            text, state_class = self._status(kind)
            shown = self.query_one(f"#{kind}-status", Static)
            shown.update(text)
            shown.set_classes(f"key-status {state_class}")
        missing = [k for k in REQUIRED if not self.status[k] and not (k == "linear" and self.state == "connector")]
        if missing and not self.warned:
            self.warned = True
            warnings = [Static(fc_keys.skipped_line(kind, self.workspace), classes="skipped") for kind in missing]
            warnings.append(Static("Press Continue again to go on without the missing keys.", classes="skipped"))
            self.mount(*warnings, before=self.query_one("#continue"))
            return
        self.dismiss((self.saved, missing))
