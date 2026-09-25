"""
Cache Detective: the only file you edit.

Four functions, one clue each. After each one, run `.venv/bin/python app.py`
and watch the readout change. Check your work with
`.venv/bin/python -m pytest -q tests`, or one clue at a time with
`-k clue_1` (to clue_4). Stuck? reference.py has the finished versions.
"""
import config
from support import HANDBOOK, make_request


# ── Clue 1. The meter ─────────────────────────────────────────────────────
# Every response has a usage object. Across a list of them, return
# (hit_rate, dollars):
#   hit_rate: cache_read_input_tokens as a share of all input tokens, where
#             all input = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
#             (0.0 if there's no input at all)
#   dollars:  the total across all the usages: each token count times its
#             price in prices. Price cache writes at "cache_write_5m", and
#             output_tokens at "output". app.py divides per conversation.
# The two cache fields can be None. Count None as 0.
# prices defaults to config.PRICES (Opus 5.5); pass your own model's to use
# meter() in your app (README, "Take it to your app").
# Hint: u.input_tokens, u.cache_creation_input_tokens, u.cache_read_input_tokens, u.output_tokens
def meter(usages: list, prices: dict | None = None) -> tuple[float, float]:
    prices = prices or config.PRICES
    raise NotImplementedError("Clue 1: add up the three input fields and output_tokens, price them with prices, return (hit_rate, dollars)")


# ── Clue 2. The witness ───────────────────────────────────────────────────
# Cache diagnostics compares a request with an earlier one and names the
# first thing that changed. Opt in on every request with a diagnostics
# object: previous_message_id is previous_id, which is None on a
# conversation's first turn and the previous response's id after that.
# response.diagnostics comes back in one of three documented states.
# Return (response, reason), where reason is:
#   None       if response.diagnostics is None (nothing changed, or nothing to compare)
#   "pending"  if response.diagnostics.cache_miss_reason is None (the comparison
#              was still running; check the next turn)
#   response.diagnostics.cache_miss_reason otherwise (its .type names what changed)
# Hint: client.beta.messages.create(**request, diagnostics={...})
def send_with_diagnostics(client, request: dict, previous_id: str | None):
    raise NotImplementedError("Clue 2: call client.beta.messages.create with diagnostics={'previous_message_id': previous_id}")


# ── Clue 3. Move the cache buster ─────────────────────────────────────────
# Build one turn's request so the system prompt is byte-identical on every
# request: just HANDBOOK. Wren still needs the time, so put `now` in the new
# user message. Any wording works, as long as `now` is in it. Earlier
# messages never change, so each turn can still read the prefix the turn
# before it wrote.
# history is the conversation so far: don't change it. Send it as it is,
# then the new message (history + [message] makes a new list).
# Hint: compare with friday_request() in support.py. make_request(system, messages) fills in the rest.
def build_request(history: list, question: str, now: str) -> dict:
    raise NotImplementedError("Clue 3: return make_request(HANDBOOK, ...) with `now` in the new user message")


# ── Clue 4. Place the breakpoint ──────────────────────────────────────────
# First turns never read the cache. make_request() uses automatic caching,
# which puts the breakpoint on the last block: the new user message, which is
# different on every request. Writes happen only at a breakpoint, and a read
# only finds an entry an earlier request wrote. So what could a new
# conversation's first turn read? Add an explicit breakpoint where it would
# find one. Keep the automatic one too; it caches each conversation as it grows.
# Changing request in place is fine; return it either way.
# Hint: a breakpoint is cache_control on a block, like
#   {"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}
# and request["system"] can be a string or a list of text blocks.
def place_breakpoint(request: dict) -> dict:
    raise NotImplementedError("Clue 4: add an explicit cache_control breakpoint, keep the top-level one, then return request")
