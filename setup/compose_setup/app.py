"""SetupApp: the steps screen, the herdr config, KeysScreen, then FinishScreen."""
from pathlib import Path
from textual.app import App


class SetupApp(App[int]):
    """The guided setup for the compose checkout at checkout; exits with setup's code."""
    CSS_PATH = "setup.tcss"

    def __init__(self, checkout: Path):
        super().__init__()
        self.checkout = checkout

    def on_mount(self) -> None:
        raise NotImplementedError("not implemented: task 025")

def main() -> None:
    """Run SetupApp on the checkout this package lives in and exit with its code."""
    raise NotImplementedError("not implemented: task 025")
