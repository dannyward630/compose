"""Setup's line prompts: frame lines, numbered, yes-or-no, and hidden questions, and a spinner line. Stdlib only; imports no fc_ module."""
import contextlib, getpass, os, sys, threading


FRAMES = "◒◐◓◑"


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
    print(f"◆  {question}")
    for number, option in enumerate(options, 1):
        print(f"│  {number}) {option}")
    while True:
        try:
            answer = input(f"│  number [{default + 1}]: ").strip()
        except EOFError:
            return default
        if not answer:
            return default
        try:
            number = int(answer)
        except ValueError:
            number = None
        if number is not None and 1 <= number <= len(options):
            return number - 1
        print(f"│  type a number from 1 to {len(options)}")


def confirm(question, default):
    prompt = f"◆  {question} (Y/n) " if default else f"◆  {question} (y/N) "
    while True:
        try:
            answer = input(prompt).strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def password(label):
    try:
        return getpass.getpass(f"◆  {label}: ").strip()
    except EOFError:
        return ""


def spin(label):
    @contextlib.contextmanager
    def spinner():
        out = sys.stdout
        if not out.isatty():
            yield
            return
        stop = threading.Event()

        def run():
            i = 0
            while not stop.wait(0.1):
                i += 1
                out.write(f"\r{FRAMES[i % len(FRAMES)]}  {label}")
                out.flush()

        out.write(f"\r{FRAMES[0]}  {label}")
        out.flush()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()
            out.write("\r\x1b[2K")
            out.flush()

    return spinner()
