"""Model tiers: cheap, standard and frontier, the highest tier each role may start on, and the model a tier and a pin give."""

ORDER = ()
PINS = ()
CEILINGS = {}


def ceiling(role):
    return None

def tier_of(model):
    return None

def tier_for(ceiling, pin=None):
    return None

def chain(tier, entries):
    return []

def start_tier(depth, pin=None):
    return None

def implementer_model(tier):
    return None

def escalate(model):
    return None
