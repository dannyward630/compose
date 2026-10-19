"""Setup's line prompts: frame lines, numbered, yes-or-no, and hidden questions, and a spinner line. Stdlib only; imports no fc_ module."""


FRAMES = ""


def paint(text, code):
    raise NotImplementedError("paint")


def intro(title):
    raise NotImplementedError("intro")


def note(title, lines):
    raise NotImplementedError("note")


def step(name, word, lines=()):
    raise NotImplementedError("step")


def outro(line):
    raise NotImplementedError("outro")


def select(question, options, default=0):
    raise NotImplementedError("select")


def confirm(question, default):
    raise NotImplementedError("confirm")


def password(label):
    raise NotImplementedError("password")


def spin(label):
    raise NotImplementedError("spin")
