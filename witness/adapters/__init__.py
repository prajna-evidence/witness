"""Adapter registry.

An adapter maps one host surface to observations and is pure: bytes in, observations
out. No writes, no network beyond its own collection call.
"""

from importlib import import_module

REGISTRY = {
    "claudecode": "witness.adapters.claudecode",
    "githubactions": "witness.adapters.githubactions",
}


def load(name: str):
    try:
        module_path = REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown adapter {name!r}; known: {', '.join(sorted(REGISTRY))}") from None
    return import_module(module_path)
