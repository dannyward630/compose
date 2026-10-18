"""`compose linear <verb>`: read and write Linear with the workspace key, printing compact text."""
import fc_core, fc_config, fc_linear


def issue_line(issue):
    raise NotImplementedError

def read_body(a):
    raise NotImplementedError

def linear_project(repo):
    raise NotImplementedError

def in_scope(issue, a):
    raise NotImplementedError

def state_and_labels(team, a):
    raise NotImplementedError

def replace_section(body, heading, text):
    raise NotImplementedError

def verb_project(a):
    raise NotImplementedError

def verb_get(a):
    raise NotImplementedError

def verb_list(a):
    raise NotImplementedError

def verb_create(a):
    raise NotImplementedError

def verb_update(a):
    raise NotImplementedError

def verb_comment(a):
    raise NotImplementedError

def verb_labels(a):
    raise NotImplementedError

def verb_doc(a):
    raise NotImplementedError

def cmd_linear(a):
    raise NotImplementedError
