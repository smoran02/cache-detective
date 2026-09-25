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
    raise NotImplementedError("Clue 1: add up the three input fields and output_tokens,"
                              " price them with prices, return (hit_rate, dollars)")


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
    raise NotImplementedError("Clue 2: call client.beta.messages.create"
                              " with diagnostics={'previous_message_id': previous_id}")


# ── Clue 3. Move the cache buster ─────────────────────────────────────────
# Build one turn's request (question is the customer's new message). It must:
#   - send a system prompt that's the same bytes on every request, with the
#     handbook in it;
#   - still show Wren the time, date included (Friday's deploy added it so
#     Wren stops offering phone callbacks when the line is closed), worded
#     any way you like;
#   - send history as it is, then the customer's new message. Don't change
#     history: history + [message] makes a new list.
# Where the time goes is the clue. Stuck? README, "Explain clue 3".
# Hint: compare with friday_request() in support.py. make_request(system, messages) fills in the rest.
def build_request(history: list, question: str, now: str) -> dict:
    raise NotImplementedError("Clue 3: keep the system prompt the same on every request, and still show Wren the time")


# ── Clue 4. Place the breakpoint ──────────────────────────────────────────
# The handbook is the same on every request, yet first turns never read the
# cache. Why? make_request() turns on automatic caching (the top-level
# cache_control); leave it in place. Add one explicit breakpoint where a new
# conversation's first turn could read what an earlier request wrote.
# Stuck? README, "Explain clue 4".
# Changing request in place is fine; return it either way.
# Hint: a breakpoint is cache_control on a block, like
#   {"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}
# and request["system"] can be a string or a list of text blocks.
def place_breakpoint(request: dict) -> dict:
    raise NotImplementedError("Clue 4: add a breakpoint where a first turn could read what an earlier request wrote")
