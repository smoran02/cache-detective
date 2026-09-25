"""
first_divergence(): what changed between two requests, on any provider.
Copy it into your app; it needs nothing from this repo.

Cache diagnostics (Claude API only) names the first thing that changed
between a request and the one before it. On Bedrock, or before you turn
diagnostics on, log two consecutive requests of one conversation and
compare them here. The first part that differs is where the cache stops
matching. Like diagnostics, it compares hashes, so you can log
fingerprint() instead of the prompts.
"""
import hashlib
import json


def _without_markers(value):
    """The value with every cache_control removed: a moved breakpoint doesn't change the cached bytes."""
    if isinstance(value, dict):
        return {k: _without_markers(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [_without_markers(v) for v in value]
    return value


def _hash(value) -> str:
    # Keys keep the order they were sent in: a reordered key is a changed request.
    return hashlib.sha256(json.dumps(_without_markers(value), default=str).encode()).hexdigest()[:16]


def fingerprint(request: dict) -> list[tuple[str, str]]:
    """(part, hash) in prefix order: the model, the tools, the system prompt, then each message."""
    parts = [(key, _hash(request.get(key))) for key in ("model", "tools", "system")]
    return parts + [(f"messages[{i}]", _hash(m)) for i, m in enumerate(request.get("messages", []))]


def first_divergence(earlier, later) -> str | None:
    """The first part of `later` that differs from `earlier`, or None if `later` only adds messages.

    Each argument is a request dict or its fingerprint().
    """
    a = earlier if isinstance(earlier, list) else fingerprint(earlier)
    b = later if isinstance(later, list) else fingerprint(later)
    for (part, x), (_, y) in zip(a, b):
        if x != y:
            return part
    if len(b) < len(a):
        return f"messages[{len(b) - 3}]"  # later dropped messages from the end
    return None
