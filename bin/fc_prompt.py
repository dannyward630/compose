"""Setup's line prompts: frame lines, numbered, yes-or-no, and hidden questions, and a spinner line. Stdlib only; imports no fc_ module."""
import os, sys


FRAMES = ""


def paint(text, code):
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return f"\x1b[{code}m{text}\x1b[0m"
    return text


def intro(title):
    print(f"┌  {paint(title, 1)}")
    print("│")


def note(title, lines):
    print("│")
    print(f"◇  {title}")
    for line in lines:
        print(f"│  {line}")


def step(name, word, lines=()):
    code = 32 if word in ("ok", "done") else 31 if word == "failed" else 36 if word.startswith("would") else 33
    print(f"◇  {name}: {paint(word, code)}")
    for entry in lines:
        for part in entry.split("\n"):
            if part:
                print(f"│  {part}")


def outro(line):
    print("│")
    print(f"└  {line}")


def select(question, options, default=0):
    raise NotImplementedError("select")


def confirm(question, default):
    raise NotImplementedError("confirm")


def password(label):
    raise NotImplementedError("password")


def spin(label):
    raise NotImplementedError("spin")
