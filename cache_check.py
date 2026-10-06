"""
cache_check.py: cache hit rate, cost, and miss reasons for your own Claude app.
Copy this one file into your app (it needs only the anthropic SDK) and set PRICES to your model's.

    check = CacheCheck(client, log="usage.jsonl")      # diagnostics=False off the Claude API
    response = check.create(conversation_id, model=..., max_tokens=..., system=..., messages=...)
    print(check.report())
    python cache_check.py usage.jsonl                   # the same report from the log

create() turns cache diagnostics on, sending each conversation's last response id as
previous_message_id, and records the usage and cache_miss_reason.type (or "pending": the
comparison was still running, so check the next turn). Diagnostics is Claude API only: with
diagnostics=False, create() names the first part of the request that changed from the
conversation's last one instead ("system", "messages[3]"). Streaming? Send
diagnostics={"previous_message_id": check.last_id.get(conversation_id)} to client.beta.messages.stream(),
then call check.record(conversation_id, request, stream.get_final_message()).
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter

from anthropic.types import Usage

# $ per token for your model: set these to yours. Opus 5.5's Claude API list prices
# (https://platform.claude.com/docs/en/about-claude/pricing).
PRICES = {
    "input": 4.00 / 1_000_000, "cache_write_5m": 5.00 / 1_000_000, "cache_write_1h": 8.00 / 1_000_000,
    "cache_read": 0.20 / 1_000_000, "output": 20.00 / 1_000_000,
}


def meter(usages, prices: dict) -> tuple[float, float]:
    """(hit_rate, dollars): cache reads as a share of all input, and the cost at prices."""
    read = total = 0
    dollars = 0.0
    for u in usages:
        # None counts as 0.
        r, w = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        w_1h = u.cache_creation.ephemeral_1h_input_tokens if u.cache_creation else 0  # 1-hour writes cost more
        read, total = read + r, total + r + w + u.input_tokens
        dollars += (u.input_tokens * prices["input"] + (w - w_1h) * prices["cache_write_5m"]
                    + w_1h * prices["cache_write_1h"] + r * prices["cache_read"] + u.output_tokens * prices["output"])
    return (read / total if total else 0.0), dollars


def miss_reason(response) -> str | None:
    """What response.diagnostics says: a cache_miss_reason's type, "pending", or None."""
    if response.diagnostics is None:
        return None  # nothing changed, or nothing to compare
    if response.diagnostics.cache_miss_reason is None:
        return "pending"  # the comparison was still running: check the next turn
    return response.diagnostics.cache_miss_reason.type


# Request parameters the docs list as cache busters: the prompt caching invalidation table and the diagnostics
# unavailable reason. Compared as sent: the docs treat an explicit default effort as omitted, and this doesn't.
PARAMS = ("tool_choice", "thinking", "output_config", "output_format", "context_management", "speed")
HEADER = ("model", "tools", "system", "params")  # the parts before the messages, in the order compared


def _hash(value) -> str:
    def unmarked(v):  # every cache_control removed: a moved breakpoint doesn't change the cached bytes
        if isinstance(v, dict):
            return {k: unmarked(x) for k, x in v.items() if k != "cache_control"}
        return [unmarked(x) for x in v] if isinstance(v, list) else v
    # Keys keep the order they were sent in: a reordered key is a changed request.
    return hashlib.sha256(json.dumps(unmarked(value), default=str).encode()).hexdigest()[:16]


def fingerprint(request: dict) -> list[tuple[str, str]]:
    """(part, hash) in prefix order: the model, tools, system prompt, and parameters, then each message."""
    system = request.get("system") or []
    if isinstance(system, str):
        system = [{"type": "text", "text": system}]  # the same prompt as a one-block list
    header = {"model": request.get("model"), "tools": request.get("tools") or [],  # no tools and [] match
              "system": system, "params": {key: request[key] for key in PARAMS if key in request}}
    parts = [(part, _hash(header[part])) for part in HEADER]
    return parts + [(f"messages[{i}]", _hash(m)) for i, m in enumerate(request.get("messages", []))]


def first_divergence(earlier, later) -> str | None:
    """The first part of `later` that differs from `earlier` (a request or its fingerprint()), or None if
    `later` only adds messages. It sees only request bodies: not an anthropic-beta header or an expired entry."""
    a = earlier if isinstance(earlier, list) else fingerprint(earlier)
    b = later if isinstance(later, list) else fingerprint(later)
    for (part, x), (_, y) in zip(a, b):
        if x != y:
            return part
    if len(b) < len(a):
        return f"messages[{len(b) - len(HEADER)}]"  # later dropped messages from the end
    return None


class CacheCheck:
    """Sends your requests and records what report() needs. Use one for all your conversations."""

    def __init__(self, client, prices: dict = PRICES, log: str | None = None, diagnostics: bool = True):
        self.client, self.prices, self.log, self.diagnostics = client, prices, log, diagnostics
        self.last_id, self.last_request = {}, {}  # per conversation: its last response id and request fingerprint
        self.records = []  # (usage, reason), one per request

    def create(self, conversation, **request):
        """client.beta.messages.create(**request) with diagnostics on, recorded under conversation (any id)."""
        if not self.diagnostics:
            return self.record(conversation, request, self.client.messages.create(**request))
        diagnostics = {"previous_message_id": self.last_id.get(conversation)}  # None on a first turn
        return self.record(conversation, request, self.client.beta.messages.create(**request, diagnostics=diagnostics))

    def record(self, conversation, request: dict, response):
        """Record one response and return it. Call it yourself for a streamed one."""
        if self.diagnostics:
            reason = miss_reason(response)
        else:
            now, before = fingerprint(request), self.last_request.get(conversation)
            reason = first_divergence(before, now) if before else None
            self.last_request[conversation] = now
        self.last_id[conversation] = response.id
        self.records.append((response.usage, reason))
        if self.log:
            with open(self.log, "a") as log:
                log.write(json.dumps({"usage": response.usage.to_dict(), "reason": reason}) + "\n")
        return response

    def report(self) -> str:
        return report(self.records, self.prices)


def report(records, prices: dict = PRICES) -> str:
    """Requests, hit rate, total cost, and miss reasons counted by type."""
    hit_rate, dollars = meter([usage for usage, _ in records], prices)
    kinds = Counter(reason.split("[")[0] for _, reason in records if reason)  # messages[3] counts as messages
    reasons = ", ".join(f"{kind} {count}" for kind, count in kinds.most_common()) or "none"
    return (f"{len(records)} requests: {hit_rate:.1%} of input read from the cache, ${dollars:,.2f}\n"
            f"Miss reasons: {reasons}")


def load(path: str) -> list:
    """The (usage, reason) records in a log that CacheCheck (or the lab's app.py --log) wrote."""
    with open(path) as log:
        lines = [json.loads(line) for line in log if line.strip()]
    return [(Usage(**line["usage"]), line["reason"]) for line in lines]


if __name__ == "__main__":
    print(report(load(sys.argv[1] if len(sys.argv) > 1 else "usage.jsonl")))
