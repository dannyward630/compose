"""KeysScreen: one masked input per key, presence beside it, never a value."""
from typing import List, Tuple
from textual.app import ComposeResult
from textual.screen import Screen


class KeysScreen(Screen[Tuple[List[str], List[str]]]):
    """Keys for workspace; dismisses with (kinds saved, kinds skipped)."""

    def __init__(self, workspace: str = "default"):
        super().__init__()
        self.workspace = workspace

    def compose(self) -> ComposeResult:
        raise NotImplementedError("not implemented: task 023")
