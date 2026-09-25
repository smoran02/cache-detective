"""
first_divergence(): what changed between two requests, on any provider.
Copy it into your app; it needs nothing from this repo.

Cache diagnostics (Claude API only) names the first thing that changed
between a request and the one before it. On Bedrock, or before you turn
diagnostics on, log two consecutive requests of one conversation and
compare them here. The first part that differs is where the cache stops
matching. Like diagnostics, it compares hashes, so you can log
fingerprint() instead of the prompts.

It sees only the request body. A changed anthropic-beta header doesn't show,
and neither does an entry that expired: two requests with the same
fingerprint still miss if more than the TTL passed between them.
"""
import hashlib
import json

# Request parameters the docs list as cache busters: the prompt caching page's
# invalidation table (tool_choice, thinking, output_config.effort, speed) and
# the diagnostics unavailable reason (also context_management and output_format).
# Compared as sent: the docs treat an explicit default effort as omitted, and this doesn't.
PARAMS = ("tool_choice", "thinking", "output_config", "output_format", "context_management", "speed")
HEADER = ("model", "tools", "system", "params")  # the parts before the messages, in the order compared


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


def _header(request: dict) -> dict:
    system = request.get("system") or []
    if isinstance(system, str):
        system = [{"type": "text", "text": system}]  # the same prompt as a one-block list
    return {
        "model": request.get("model"),
        "tools": request.get("tools") or [],  # no tools and [] are the same request
        "system": system,
        "params": {key: request[key] for key in PARAMS if key in request},
    }


def fingerprint(request: dict) -> list[tuple[str, str]]:
    """(part, hash) in prefix order: the model, tools, system prompt, and parameters, then each message."""
    parts = [(part, _hash(value)) for part, value in _header(request).items()]
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
        return f"messages[{len(b) - len(HEADER)}]"  # later dropped messages from the end
    return None
