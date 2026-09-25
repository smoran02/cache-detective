"""
Cache Detective: finished versions of the 4 functions in starter.py.
Compare with yours, or copy one over if you're stuck.
"""
import config
from support import HANDBOOK, make_request


# ── Clue 1. The meter ─────────────────────────────────────────────────────
def meter(usages: list) -> tuple[float, float]:
    read = written = uncached = 0
    dollars = 0.0
    for u in usages:
        r = u.cache_read_input_tokens or 0
        w = u.cache_creation_input_tokens or 0
        # usage.cache_creation splits writes by TTL. 1h writes cost more (Keep going: TTL).
        w_1h = u.cache_creation.ephemeral_1h_input_tokens if u.cache_creation else 0
        read, written, uncached = read + r, written + w, uncached + u.input_tokens
        dollars += (
            u.input_tokens * config.PRICES["input"]
            + (w - w_1h) * config.PRICES["cache_write_5m"]
            + w_1h * config.PRICES["cache_write_1h"]
            + r * config.PRICES["cache_read"]
            + u.output_tokens * config.PRICES["output"]
        )
    total = read + written + uncached
    return (read / total if total else 0.0), dollars


# ── Clue 2. The witness ───────────────────────────────────────────────────
def send_with_diagnostics(client, request: dict, previous_id: str | None):
    response = client.beta.messages.create(**request, diagnostics={"previous_message_id": previous_id})
    if response.diagnostics is None:
        return response, None  # nothing changed, or nothing to compare
    if response.diagnostics.cache_miss_reason is None:
        return response, "pending"  # the comparison was still running: check the next turn
    return response, response.diagnostics.cache_miss_reason


# ── Clue 3. Move the cache buster ─────────────────────────────────────────
def build_request(history: list, question: str, now: str) -> dict:
    message = {"role": "user", "content": f"Current time: {now}\n\n{question}"}
    return make_request(HANDBOOK, history + [message])


# ── Clue 4. Place the breakpoint ──────────────────────────────────────────
def place_breakpoint(request: dict) -> dict:
    request["system"] = [
        {"type": "text", "text": request["system"], "cache_control": {"type": "ephemeral"}}
    ]
    return request
