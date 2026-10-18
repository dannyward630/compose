"""KeysScreen: one masked input per key, presence beside it, never a value."""
from typing import List, Tuple

from textual.app import ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static

import fc_auth, fc_config, fc_keys, fc_steps

KINDS = ("openrouter", "typesafe", "linear", "figma")
REQUIRED = ("openrouter", "typesafe", "linear")
LABELS = {"openrouter": "OpenRouter", "typesafe": "TypeSafe", "linear": "Linear", "figma": "Figma"}
MARKS = {"openrouter": "required", "typesafe": "required", "linear": "required, or the claude.ai Linear connector", "figma": "optional"}
HINTS = {"openrouter": "openrouter.ai/keys", "typesafe": "your TypeSafe account", "linear": "linear.app/settings/api", "figma": "a Figma personal access token"}


class KeysScreen(Screen[Tuple[List[str], List[str]]]):
    """Keys for workspace; dismisses with (kinds saved, kinds skipped)."""

    AUTO_FOCUS = "#openrouter"

    DEFAULT_CSS = """
    KeysScreen {
        padding: 1 2;
    }
    KeysScreen Grid {
        height: auto;
        grid-size: 3 8;
        grid-columns: 14 1fr 22;
        grid-rows: 3 1;
    }
    KeysScreen Grid Label,
    KeysScreen Grid Static {
        height: 3;
        content-align: left middle;
    }
    KeysScreen Grid .key-hint {
        column-span: 3;
        height: 1;
        color: $text-muted;
    }
    KeysScreen Grid .key-status {
        padding-left: 1;
    }
    KeysScreen #keys-body {
        height: 1fr;
    }
    KeysScreen #continue {
        dock: bottom;
        margin-top: 1;
    }
    KeysScreen .present {
        color: $success;
    }
    KeysScreen .absent {
        color: $text-muted;
    }
    KeysScreen .skipped {
        color: $text-error;
    }
    KeysScreen #keys-title {
        text-style: bold;
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
        with VerticalScroll(id="keys-body"):
            yield Label(f"Keys for workspace {self.workspace}", id="keys-title")
            with Grid():
                for kind in KINDS:
                    yield Label(LABELS[kind], classes="key-label")
                    yield Input(password=True, id=kind)
                    text, state_class = self._status(kind)
                    yield Static(text, classes=f"key-status {state_class}", id=f"{kind}-status")
                    yield Static(f"{MARKS[kind]} · {HINTS[kind]}", classes="key-hint", id=f"{kind}-hint")
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        index = KINDS.index(event.input.id) + 1
        target = KINDS[index] if index < len(KINDS) else "continue"
        self.query_one(f"#{target}").focus()

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
            body = self.query_one("#keys-body")
            body.mount(*warnings)
            self.call_after_refresh(body.scroll_end, animate=False)
            return
        self.dismiss((self.saved, missing))
