"""Put the checkout's own bp first on PATH, whatever bp the machine has: verify launches `bp` by bare name."""
import os, tempfile
from pathlib import Path

_DIR = None


def use_checkout_bp():
    """The temporary directory holding a `bp` link to <checkout>/bp/bin/bp.mjs, put first on os.environ["PATH"] once."""
    global _DIR
    if _DIR is None:
        _DIR = tempfile.mkdtemp(prefix="compose-e2e-bp-")
        os.symlink(Path(__file__).resolve().parents[1] / "bp" / "bin" / "bp.mjs", Path(_DIR) / "bp")
    rest = [p for p in os.environ["PATH"].split(os.pathsep) if p != _DIR]
    os.environ["PATH"] = os.pathsep.join([_DIR] + rest)
    return _DIR
