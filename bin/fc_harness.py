"""Harnesses other than Claude Code and pi: one table of them, and the accessors every other module reads it through."""


def _codex_probe(cid):
    raise NotImplementedError

def _codex_result(p):
    raise NotImplementedError

def _git_dirs(f):
    raise NotImplementedError

def _codex_argv(cid, effort, prompt, skill, cwd, results, work=None, more=()):
    raise NotImplementedError

def _codex_hash(event, group):
    raise NotImplementedError

HARNESSES = {}

RESERVED = ()


def harness_of(model):
    raise NotImplementedError

def model_id(model):
    raise NotImplementedError

def rows():
    raise NotImplementedError

def installed():
    raise NotImplementedError

def home_dir(key):
    raise NotImplementedError

def skills_dir(key):
    raise NotImplementedError

def probe_command(model):
    raise NotImplementedError

def probe_result(model, p):
    raise NotImplementedError

def crew_argv(model, effort, prompt, skill, cwd, results, work=None, more=()):
    raise NotImplementedError

def hook_groups(key, checkout):
    raise NotImplementedError
