from textual.widgets import Static


def _break_line(line: str, width: int) -> list:
    out = []
    while len(line) > width:
        space = line.rfind(" ", 0, width + 1)
        slash = line.rfind("/", 0, width) + 1
        at = max(space, slash)
        if at <= 0:
            out.append(line[:width])
            line = line[width:]
        elif at == space:
            out.append(line[:at])
            line = line[at + 1 :]
        else:
            out.append(line[:at])
            line = line[at:]
    return out + [line]


def break_paths(text: str, width: int) -> str:
    """text with breaks at spaces or after slashes so no line is wider than width; width < 1 leaves it as is."""
    if width < 1:
        return text
    return "\n".join(row for line in text.split("\n") for row in _break_line(line, width))


class Wrapped(Static):
    """A Static that breaks its text at spaces and after slashes, again on every resize."""

    def __init__(self, content: str = "", **kwargs):
        super().__init__(content, **kwargs)
        self._text = content

    def update(self, content: str = "") -> None:
        self._text = content
        super().update(break_paths(content, self.content_size.width))

    def on_resize(self) -> None:
        super().update(break_paths(self._text, self.content_size.width))
