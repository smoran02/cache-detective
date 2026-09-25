"""
Cache Detective: the only file you edit.

Four functions, one clue each. After each one, run `.venv/bin/python app.py`
and watch the readout change. Check your work with
`.venv/bin/python -m pytest -q tests`. Stuck? reference.py has the finished
versions.
"""
import config
from support import HANDBOOK, make_request


# ── Clue 1. The meter ─────────────────────────────────────────────────────
# Every response has a usage object. Across a list of them, return
# (hit_rate, dollars):
#   hit_rate: cache_read_input_tokens as a share of all input tokens, where
#             all input = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
#   dollars:  each token count times its price in config.PRICES. Price cache
#             writes at "cache_write_5m", and output_tokens at "output".
# The two cache fields can be None. Count None as 0.
# Hint: u.input_tokens, u.cache_creation_input_tokens, u.cache_read_input_tokens, u.output_tokens
def meter(usages: list) -> tuple[float, float]:
    raise NotImplementedError("Clue 1: sum the four usage fields, price them with config.PRICES, return (hit_rate, dollars)")


# ── Clue 2. The witness ───────────────────────────────────────────────────
# Cache diagnostics compares a request with an earlier one and names the
# first thing that changed. Opt in on every request with a diagnostics
# object: previous_message_id is previous_id, which is None on a
# conversation's first turn and the previous response's id after that.
# Return (response, reason). reason is response.diagnostics.cache_miss_reason,
# or None when response.diagnostics is None (nothing changed, or nothing to compare).
# Hint: client.beta.messages.create(**request, diagnostics={...})
def send_with_diagnostics(client, request: dict, previous_id: str | None):
    raise NotImplementedError("Clue 2: call client.beta.messages.create with diagnostics={'previous_message_id': previous_id}")


# ── Clue 3. Move the cache buster ─────────────────────────────────────────
# Build one turn's request so the system prompt is byte-identical on every
# request: just HANDBOOK. Wren still needs the time, so put `now` in the new
# user message, after the part that gets cached.
# history is the conversation so far; send it unchanged, then the new message.
# Hint: compare with friday_request() in support.py. make_request(system, messages) fills in the rest.
def build_request(history: list, question: str, now: str) -> dict:
    raise NotImplementedError("Clue 3: return make_request(HANDBOOK, ...) with `now` in the new user message")


# ── Clue 4. Place the breakpoint ──────────────────────────────────────────
# make_request() uses automatic caching, which puts the breakpoint on the last
# block: the new user message, which is different on every request. Writes
# happen only at a breakpoint, so no request ever writes the handbook on its
# own, and a new conversation has nothing to read. Put an explicit breakpoint
# on the last block that every request shares: the system prompt. Keep the
# automatic one too; it caches each conversation as it grows.
# Hint: request["system"] = [{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]
def place_breakpoint(request: dict) -> dict:
    raise NotImplementedError("Clue 4: turn request['system'] into a text block with cache_control, return request")
