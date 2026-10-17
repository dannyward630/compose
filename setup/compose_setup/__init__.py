"""The guided `compose setup`: a Textual app run from this uv project. The CLI's bin/ goes on sys.path, so the screens use the
same fc_* modules as the plain path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))
