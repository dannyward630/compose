"""Harnesses other than Claude Code and pi: which model ids name Codex, and how to probe one."""

RESERVED = ()


def is_codex(model):
    raise NotImplementedError

def codex_id(model):
    raise NotImplementedError

def probe_command(model):
    raise NotImplementedError

def probe_result(p):
    raise NotImplementedError

def crew_argv(model, effort, prompt, skill, cwd, results, work=None):
    raise NotImplementedError
