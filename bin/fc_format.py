"""Deterministic formatting of a passed task's own changed files: the repo's gofmt or prettier, and one final newline."""
import json
import fc_core


PRETTIER_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".scss", ".json", ".html", ".vue"}

def prettier_opted_in(wt, path):
    """Whether the repo chose prettier for `path`: a prettier config file or a package.json `prettier` key on the way from the
    file's directory up to `wt`, or prettier as a direct dependency of the nearest package.json."""
    names = [".prettierrc"] + [".prettierrc." + e for e in ("json", "yaml", "yml", "json5", "js", "cjs", "mjs", "ts", "cts", "mts", "toml")] \
        + ["prettier.config." + e for e in ("js", "cjs", "mjs", "ts", "cts", "mts")]
    nearest = None
    d = path.parent
    while d == wt or wt in d.parents:
        if any((d / n).exists() for n in names):
            return True
        pkg = d / "package.json"
        if pkg.exists():
            cfg = json.loads(pkg.read_text())
            if "prettier" in cfg:
                return True
            if nearest is None:
                nearest = cfg
        d = d.parent
    if nearest is None:
        return False
    return "prettier" in {**nearest.get("dependencies", {}), **nearest.get("devDependencies", {})}

def format_files(wt, files, base="HEAD"):
    """Format a passed task's own changed files with the repo's formatter, deterministically and with no model, so verify's
    fix rounds never spend one on formatting: gofmt for Go, the repo's installed prettier for web files. Whatever the formatter,
    a text file ends with exactly one final newline, unless it had none on base. Returns what changed."""
    import shutil
    out = []
    for f in files:
        p = wt / f
        cmd = None
        if p.suffix == ".go" and shutil.which("gofmt"):
            cmd = ["gofmt", "-w", str(p)]
        elif p.suffix in PRETTIER_EXT and prettier_opted_in(wt, p):
            d = p.parent
            while cmd is None and (d == wt or wt in d.parents):  # the nearest node_modules, up to the clone root
                bin_ = d / "node_modules" / ".bin" / "prettier"
                cmd = [str(bin_), "--write", str(p)] if bin_.exists() else None
                d = d.parent
        before = p.read_bytes()
        if cmd:
            fc_core.sh(cmd, wt, timeout=120, check=False)
        data = p.read_bytes()
        text = b"\0" not in data and data.strip()
        old = fc_core.sh(["git", "show", f"{base}:{f}"], wt, check=False) if text else None  # only text is decoded
        if text and (old.returncode != 0 or old.stdout.endswith("\n")):
            data = data.rstrip(b"\n") + b"\n"
            p.write_bytes(data)
        if data != before:
            out.append(f)
    return out
