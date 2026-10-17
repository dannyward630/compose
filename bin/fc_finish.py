"""The end of every setup run: models merged, key rules, the implementer probe, the exit code."""
import shutil
import fc_auth, fc_config, fc_keys, fc_steps, fc_defaults


def finish(results, yes):
    """(lines, code) from results, the [(row name, state)] of run_step; code 0 when compose is ready, else 1."""
    raise NotImplementedError("not implemented: task 019")
