"""FinishScreen: setup's ending from fc_finish.finish, run in a worker."""
from typing import List, Tuple
from textual.app import ComposeResult
from textual.screen import Screen


class FinishScreen(Screen[str]):
    """results is the [(row name, state)] of the steps run; dismisses with "keys" for Back to keys, else exits the app with the code."""

    def __init__(self, results: List[Tuple[str, str]]):
        super().__init__()
        self.results = results

    def compose(self) -> ComposeResult:
        raise NotImplementedError("not implemented: task 024")
