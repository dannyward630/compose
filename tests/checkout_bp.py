"""Put the checkout's own bp first on PATH, whatever bp the machine has: verify launches `bp` by bare name."""
import os, tempfile
from pathlib import Path


def use_checkout_bp():
    """The temporary directory holding a `bp` link to <checkout>/bp/bin/bp.mjs, put first on os.environ["PATH"] once."""
    raise NotImplementedError("not implemented: task 012")
