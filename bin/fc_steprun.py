"""Run one setup step: the plain path and the Textual app both go through run_step."""
import shutil, subprocess
import fc_core, fc_config, fc_pi, fc_keys, fc_steps, fc_links


WRITERS = {}  # task 018: write row name -> callable(checkout) returning its line(s)

def run_step(row, checkout, yes, claude, terminal):
    """(state, line): state is ok, claude, skipped, manual, done, or failed; the line never holds a key value."""
    raise NotImplementedError("not implemented: task 018")
