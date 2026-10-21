"""The route's record: the reason the CLI composes, and the CLI-owned `## Route` section of the task issue."""


def route_reason(route, state):
    """The recorded reason: Jev's answers or the fallback, the context, the Bug flags, the floor, and the policy note."""
    raise NotImplementedError("route_reason")


def route_section(route):
    """The `## Route` section text for one route."""
    raise NotImplementedError("route_section")


def parse_route(desc):
    """The Route section's bullets keyed by their labels; None without the section."""
    raise NotImplementedError("parse_route")


def with_route(desc, section):
    """`desc` with its Route section replaced in place, else inserted right above the compose block."""
    raise NotImplementedError("with_route")
