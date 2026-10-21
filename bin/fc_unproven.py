"""Why a regression test is not proof yet, the re-prompt that says so, and the writer it goes to."""


def reason(proof, saved=True):
    """One line saying why `proof` is not proof; "" when it is."""
    raise NotImplementedError("reason")


def prompt_text(proof):
    """The re-prompt for the writer, quoting the failing run's output."""
    raise NotImplementedError("prompt_text")


def writer_live(proj, tid):
    """True when the task's `tests-<tid>` writer is live in the project's herdr space."""
    raise NotImplementedError("writer_live")


def reprompt(proj, tid, text):
    """Send `text` to the task's writer; whether herdr answered."""
    raise NotImplementedError("reprompt")


def restartable(proj, tid):
    """The saved unproven result whose fix clone is kept, else None."""
    raise NotImplementedError("restartable")
