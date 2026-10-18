"""The LIBRARY API section of an implementer prompt: signatures of the third-party names a task's files import, read from the
packages installed in the clone (Python through the clone's own interpreter, JS/TS from the package's type declarations).
Stdlib only."""
import ast, json, re, subprocess
from pathlib import Path

INSPECT = ""  # the inline script the clone's interpreter runs with -I: signatures, versions, stdlib names, as JSON


def python_api(wt, files, words):
    """One block (a string) per third-party distribution the task's existing .py files import: its name and version, a line per
    imported name (signature, first docstring line), then the public methods of an imported class that `words` names."""
    raise NotImplementedError("fc_libapi.python_api")


def js_api(wt, files, words):
    """The same blocks for the task's JS/TS files, from each imported package's type declarations in node_modules."""
    raise NotImplementedError("fc_libapi.js_api")


def section(wt, files, words, cap=3000):
    """"" with no block; else a `LIBRARY API` header line, then the Python blocks and the JS/TS blocks, cut after the last whole
    signature line that fits in `cap` characters."""
    raise NotImplementedError("fc_libapi.section")
