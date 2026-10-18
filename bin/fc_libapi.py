"""The LIBRARY API section of an implementer prompt: signatures of the third-party names a task's files import, read from the
packages installed in the clone (Python through the clone's own interpreter, JS/TS from the package's type declarations).
Stdlib only."""
import ast, json, re, subprocess
from pathlib import Path

INSPECT = r"""
import sys, json, inspect, importlib, importlib.metadata as md, re
wt, (imports, words) = sys.argv[1], json.load(sys.stdin)
std = getattr(sys, "stdlib_module_names", sys.builtin_module_names)
tops = {}
for d in md.distributions():
    for t in (d.read_text("top_level.txt") or "").split():
        tops.setdefault(t, d)
def line(label, obj):
    try: sig = str(inspect.signature(obj))
    except Exception: sig = ""
    doc = (inspect.getdoc(obj) or "").strip().split("\n")[0]
    return label + sig + (" - " + doc if doc else "")
blocks = {}
for mod, names in imports:
    top = mod.split(".")[0]
    if top in std or top not in tops: continue
    try:
        m = importlib.import_module(mod)
        f = getattr(m, "__file__", None) or ""
        if f.startswith(wt) and ".venv" not in f and "site-packages" not in f: continue
    except Exception: continue
    d = tops[top]
    lines = blocks.setdefault(d.metadata["Name"] + " " + d.version, [[], []])
    for n in names:
        o = getattr(m, n, None)
        if o is None: continue
        lines[0].append(line(n, o))
        if inspect.isclass(o):
            for k, v in vars(o).items():
                if not k.startswith("_") and callable(v) and re.search(r"\b" + re.escape(k) + r"\b", words):
                    lines[1].append(line(n + "." + k, getattr(o, k)))
print(json.dumps([[h, list(dict.fromkeys(a + b))] for h, (a, b) in blocks.items()]))
"""


def python_api(wt, files, words):
    """One block (a string) per third-party distribution the task's existing .py files import: its name and version, a line per
    imported name (signature, first docstring line), then the public methods of an imported class that `words` names."""
    wt = Path(wt)
    groups = {}
    for f in files:
        path = wt / f
        if path.suffix != ".py" or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, ValueError, OSError):
            continue
        py = "python3"
        for d in [path.parent, *path.parent.parents]:
            if (d / ".venv" / "bin" / "python").exists():
                py = str(d / ".venv" / "bin" / "python")
                break
            if d == wt:
                break
        imports = groups.setdefault(py, [])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [[a.name, []] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.append([node.module, [a.name for a in node.names]])
    blocks = []
    for py, imports in groups.items():
        try:
            out = subprocess.run([py, "-I", "-c", INSPECT, str(wt)], input=json.dumps([imports, words]), capture_output=True, text=True)
            blocks += ["\n".join([h, *ls]) for h, ls in json.loads(out.stdout)] if out.returncode == 0 else []
        except Exception:
            pass
    return blocks


def js_api(wt, files, words):
    """The same blocks for the task's JS/TS files, from each imported package's type declarations in node_modules."""
    raise NotImplementedError("fc_libapi.js_api")


def section(wt, files, words, cap=3000):
    """"" with no block; else a `LIBRARY API` header line, then the Python blocks and the JS/TS blocks, cut after the last whole
    signature line that fits in `cap` characters."""
    blocks = python_api(wt, files, words)
    if not blocks:
        return ""
    lines = ["LIBRARY API"] + "\n".join(blocks).split("\n")
    while len("\n".join(lines)) > cap and lines:
        lines.pop()
    return "\n".join(lines)
