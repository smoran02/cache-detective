"""
The lab's checks, shared by the readout (app.py) and the tests (tests/test_offline.py), so
"Case closed" and a passing test suite mean the same thing. Each clue_N_problem() returns the
first way your function breaks its clue's contract, or None. truth() is the tests' own meter,
so a bug in your meter() can't hide a bad fix, and shortfalls() holds your numbers to
config.BAR.
"""
import copy
import math
from collections import Counter

from anthropic.types import CacheCreation, Usage
from anthropic.types.beta import BetaMessage

import config
from support import HANDBOOK, make_request


def truth(usages) -> tuple[float, float]:
    """(hit_rate, dollars) across usages, priced with config.PRICES."""
    read = written = uncached = 0
    dollars = 0.0
    for u in usages:
        r, w = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        w_1h = u.cache_creation.ephemeral_1h_input_tokens if u.cache_creation else 0
        read, written, uncached = read + r, written + w, uncached + u.input_tokens
        dollars += (u.input_tokens * config.PRICES["input"] + (w - w_1h) * config.PRICES["cache_write_5m"]
                    + w_1h * config.PRICES["cache_write_1h"] + r * config.PRICES["cache_read"]
                    + u.output_tokens * config.PRICES["output"])
    total = read + written + uncached
    return (read / total if total else 0.0), dollars


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content if b.get("type") == "text")


def pending(reason) -> bool:
    """send_with_diagnostics() returns "pending" when the comparison hadn't finished."""
    return reason == "pending"


def reason_kind(reason) -> str:
    """A reason's .type. A string (a clue 2 slip) is its own kind; anything else without .type, its class."""
    if isinstance(reason, str):
        return reason
    return getattr(reason, "type", None) or type(reason).__name__


def close(a, b) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-12)


# ── Clue 1 ────────────────────────────────────────────────────────────────
# Three usages whose four dollar terms all differ, so a term left out or mispriced shows:
# 150 uncached at $4/MTok, 1,000 written at $5, 1,000 read at $0.20, 110 output at $20.
CLUE_1_TERMS = ("150 uncached at $4/MTok ($0.0006) + 1,000 written at $5 ($0.0050) + 1,000 read at $0.20 ($0.0002)"
                " + 110 output at $20 ($0.0022)")
CLUE_1_SLIPS = [  # (your dollars minus the right answer, the likely cause)
    (-0.0022, "output_tokens are left out: price them at prices['output']"),
    (-0.0006, "input_tokens are left out: price them at prices['input']"),
    (-0.0050, "cache writes are left out: price cache_creation_input_tokens at prices['cache_write_5m']"),
    (-0.0002, "cache reads are left out: price cache_read_input_tokens at prices['cache_read']"),
    (-0.0010, "cache writes are priced at prices['input']: a write costs more than input, prices['cache_write_5m']"),
    (+0.0002, "cache reads are priced at 0.1x input: on Opus 5.5 they cost 0.05x, prices['cache_read']"),
    (+0.0038, "cache reads are priced at prices['input']: price them at prices['cache_read']"),
]


def _clue_1_usages() -> list:
    return [
        Usage(input_tokens=100, output_tokens=50, cache_creation_input_tokens=1000, cache_read_input_tokens=0),
        Usage(input_tokens=20, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=1000),
        Usage(input_tokens=30, output_tokens=10, cache_creation_input_tokens=None, cache_read_input_tokens=None),
    ]


def _written(five_minute: int, one_hour: int) -> Usage:
    """A usage that only writes to the cache, split by TTL in usage.cache_creation."""
    return Usage(input_tokens=0, output_tokens=0, cache_creation_input_tokens=five_minute + one_hour,
                 cache_read_input_tokens=0, cache_creation=CacheCreation(
                     ephemeral_5m_input_tokens=five_minute, ephemeral_1h_input_tokens=one_hour))


def _metered(meter, usages, *prices):
    """meter()'s answer, or the error it raised as a string."""
    try:
        return meter(usages, *prices), None
    except NotImplementedError:
        raise
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"


def clue_1_problem(meter) -> str | None:
    """The first way meter() misreads or misprices the usage fields, or None."""
    result, error = _metered(meter, _clue_1_usages())
    if error:
        return f"meter() raised {error} (the two cache fields can be None: count None as 0)"
    hit_rate, dollars = result
    if not close(hit_rate, 1000 / 2150):
        return (f"a hit rate of {hit_rate:.1%} where 1,000 of 2,150 input tokens were read ({1000 / 2150:.1%}):"
                " divide cache_read_input_tokens by all input,"
                " input_tokens + cache_creation_input_tokens + cache_read_input_tokens")
    if not close(dollars, 0.008):
        cause = next((why for off, why in CLUE_1_SLIPS if close(dollars - 0.008, off)), None)
        return f"${dollars:.4f} where the right answer is $0.0080: {CLUE_1_TERMS}" + (f". Likely {cause}" if cause else "")
    doubled = {name: 2 * price for name, price in config.PRICES.items()}
    result, error = _metered(meter, _clue_1_usages(), doubled)
    if error or not close(result[1], 2 * dollars):
        return "double every price and the bill should double: price with the prices argument, not config.PRICES"
    result, error = _metered(meter, [])
    if error or tuple(result) != (0.0, 0.0):
        return f"meter([]) gave {error or result}: with no usages, return a 0.0 hit rate and $0"
    # cache_creation_input_tokens already counts 1-hour writes, so price each written token once:
    # all at $5/MTok as the starter asks, or split by usage.cache_creation if you did Keep going's TTL step.
    for five_minute, one_hour, answers in ((0, 1000, (0.005, 0.008)), (600, 400, (0.005, 0.0062))):
        result, error = _metered(meter, [_written(five_minute, one_hour)])
        if error or not any(close(result[1], a) for a in answers):
            return (f"{five_minute:,} tokens written at 5 minutes and {one_hour:,} at 1 hour cost"
                    f" {error or f'${result[1]:.4f}'}: price each written token once, all at prices['cache_write_5m']"
                    f" (${answers[0]:.4f}), or the 1-hour ones at prices['cache_write_1h'] (${answers[1]:.4f})")
    return None


# ── Clue 2 ────────────────────────────────────────────────────────────────
class CannedClient:
    """Answers client.beta.messages.create with one fixed diagnostics value, and keeps what it was sent."""

    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        self.sent = self.response = None
        self.beta = self
        self.messages = self

    def create(self, **request):
        self.sent = request
        self.response = BetaMessage.model_validate({
            "id": "msg_canned", "type": "message", "role": "assistant", "model": config.MODEL,
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5}, "diagnostics": self.diagnostics,
        })
        return self.response


# The documented states of response.diagnostics, and what send_with_diagnostics() returns for each.
CLUE_2_CASES = [
    (None, None, "diagnostics None means nothing changed (or nothing to compare): return None"),
    ({"cache_miss_reason": None}, "pending",
     'diagnostics {"cache_miss_reason": null} means the comparison was still running: return "pending"'),
    ({"cache_miss_reason": {"type": "system_changed", "cache_missed_input_tokens": 3200}}, "system_changed",
     "a system_changed reason names what changed: return the cache_miss_reason"),
    ({"cache_miss_reason": {"type": "unavailable"}}, "unavailable",
     "unavailable means the comparison couldn't run, not that nothing changed: return the cache_miss_reason"),
    ({"cache_miss_reason": {"type": "previous_message_not_found"}}, "previous_message_not_found",
     "previous_message_not_found means there was nothing to compare with, not that nothing changed:"
     " return the cache_miss_reason"),
]


def reason_problem(reason) -> str | None:
    """What's wrong with the shape of one reason send_with_diagnostics() returned, or None."""
    if reason is None or pending(reason):
        return None
    if isinstance(reason, str):
        return "send_with_diagnostics() returned a string: return the cache_miss_reason itself (its .type is the string)"
    if hasattr(reason, "cache_miss_reason"):
        return "send_with_diagnostics() returned response.diagnostics: return response.diagnostics.cache_miss_reason"
    if not hasattr(reason, "type"):
        return f"send_with_diagnostics() returned a {type(reason).__name__}: return the cache_miss_reason itself"
    return None


def clue_2_problem(send_with_diagnostics) -> str | None:
    """The first way send_with_diagnostics() breaks its contract on canned responses, or None."""
    request = make_request(HANDBOOK, [{"role": "user", "content": "Do you rent bear canisters?"}])
    for diagnostics, expected, rule in CLUE_2_CASES:
        client = CannedClient(diagnostics)
        response, reason = send_with_diagnostics(client, copy.deepcopy(request), "msg_previous")
        if client.sent is None:
            return "call client.beta.messages.create(**request, diagnostics=...)"
        if "diagnostics" not in client.sent:
            return "send a diagnostics object on every request: diagnostics={'previous_message_id': previous_id}"
        if client.sent["diagnostics"] != {"previous_message_id": "msg_previous"}:
            return f"send diagnostics={{'previous_message_id': previous_id}}, not {client.sent['diagnostics']!r}"
        if response is not client.response:
            return "return (response, reason), the response first"
        problem = reason_problem(reason)
        if problem:
            return problem
        if expected in (None, "pending"):
            if reason != expected:
                return rule
        elif getattr(reason, "type", None) != expected:
            return rule
    return None


def clue_2_replay_problem(friday, yours) -> str | None:
    """The first way send_with_diagnostics() broke its contract during the readout's replay, or None."""
    problem = next(filter(None, (reason_problem(t.reason) for t in friday + yours)), None)
    if problem:
        return problem
    first = [t for t in yours if t.number == 1]
    odd = [t.reason for t in first if t.reason is not None]
    if odd:
        what = '"pending"' if pending(odd[0]) else odd[0].type
        return (f"send_with_diagnostics() returned {what} on {len(odd)} of {len(first)} first turns: a first turn"
                " has nothing to compare, so response.diagnostics is None. Return None")
    if not any(t.reason is not None for t in friday if t.number > 1):
        return ("send_with_diagnostics() named no reason on Friday's code, where every follow-up turn changes"
                " the system prompt: send a diagnostics object on every request")
    return None


# ── Clue 3 ────────────────────────────────────────────────────────────────
# Morning, night, just past midnight, Monday at the morning's time, and the next Saturday at it:
# a date left in the system prompt still changes it once a day, a time without its date looks
# the same on Saturday and Monday, and a weekday without its date looks the same a week later.
CLUE_3_TIMES = ["2026-09-26T09:00:00-07:00", "2026-09-26T23:30:00-07:00", "2026-09-27T00:30:00-07:00",
                "2026-09-28T09:00:00-07:00", "2026-10-03T09:00:00-07:00"]
CLUE_3_HISTORY = [
    {"role": "user", "content": "Do you rent bear canisters?"},
    {"role": "assistant", "content": "Yes, from the Bend store."},
]
CLUE_3_QUESTION = "How much for five days?"


def new_text(request, history) -> str:
    """The text of every message this turn adds after the history."""
    return "".join(text_of(m["content"]) for m in request["messages"][len(history):])


def clue_3_problem(build_request) -> str | None:
    """The first way build_request() breaks clue 3's rules, or None."""
    history = copy.deepcopy(CLUE_3_HISTORY)
    requests = [build_request(history, CLUE_3_QUESTION, now) for now in CLUE_3_TIMES]
    morning = requests[0]
    new = morning["messages"][len(history):]
    if history != CLUE_3_HISTORY:
        return "don't change history: build a new list, like history + [message]"
    if morning["messages"][: len(history)] != history:
        return "send the history unchanged, then the new message"
    if len({text_of(r["system"]) for r in requests}) > 1:
        return "the system prompt must not change with the time, or the date"
    if HANDBOOK not in text_of(morning["system"]):
        return "keep the handbook as the system prompt"
    if len({new_text(r, history) for r in requests}) < len(CLUE_3_TIMES):
        return ("Wren needs the time, date included: Friday's deploy added it so Wren stops offering"
                " phone callbacks when the line is closed. Keep it, after the part every request shares")
    if not (new and new[0]["role"] == "user" and CLUE_3_QUESTION in text_of(new[0]["content"])):
        return "the customer's new message comes right after the history"
    # On Opus 5.5 a {"role": "system"} message can follow the new user message (one before it is a 400).
    if any(m["role"] != "system" for m in new[1:]):
        return "end on the customer's new message"
    return None


# ── Clue 4 ────────────────────────────────────────────────────────────────
# System prompts other than the bare handbook, as a string and as a list of blocks, so a
# place_breakpoint() that swaps in its own system prompt, or marks only one shape, shows.
CLUE_4_SYSTEMS = [
    f"{HANDBOOK}\n\nSign every reply as Wren.",
    [{"type": "text", "text": HANDBOOK}, {"type": "text", "text": "Sign every reply as Wren."}],
]


def clue_4_problem(place_breakpoint) -> str | None:
    """The first way place_breakpoint() breaks clue 4's contract, or None."""
    messages = [{"role": "user", "content": f"Current time: {CLUE_3_TIMES[0]}\n\n{CLUE_3_QUESTION}"}]
    for system in CLUE_4_SYSTEMS:
        shape = "a list of blocks" if isinstance(system, list) else "a string"
        try:
            out = place_breakpoint(make_request(copy.deepcopy(system), copy.deepcopy(messages)))
        except NotImplementedError:
            raise
        except Exception as error:
            return (f"with {shape} as the system prompt, place_breakpoint() raised {type(error).__name__}: {error}"
                    ' (request["system"] can be a string or a list of text blocks)')
        if not isinstance(out, dict):
            return "return the request"
        blocks = out.get("system")
        if isinstance(blocks, str):
            return ("a system prompt that's a string can't carry cache_control:"
                    ' make request["system"] a list of text blocks')
        if not (isinstance(blocks, list) and blocks and all(
                isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str) for b in blocks)):
            return (f'with {shape} as the system prompt, request["system"] came back as something other than'
                    ' a list of text blocks, each with a string "text"')
        if text_of(blocks) != text_of(system):
            return f"with {shape} as the system prompt, its text changed: mark the system prompt the request has"
        if not any(b.get("cache_control") for b in blocks):
            return (f"with {shape} as the system prompt, no system block has a breakpoint"
                    ' (request["system"] can be a string or a list of text blocks)')
        if "cache_control" not in out:
            return "leave the top-level cache_control (automatic caching) in place"
    return None


# ── The bar ───────────────────────────────────────────────────────────────
def shortfalls(friday, yours, n: int, live: bool, diagnosed: bool) -> list[str]:
    """What stands between your weekend and config.BAR, priced by truth(). An empty list clears it."""
    (_, friday_dollars), (hit_rate, dollars) = truth(t.usage for t in friday), truth(t.usage for t in yours)
    if live:
        # Real token counts on 6 conversations: the live test's hit rate, and a lower bill.
        out = []
        if hit_rate < config.LIVE_HIT_RATE_AT_LEAST:
            out.append(f"hit rate {hit_rate:.1%} (live, the bar is at least {config.LIVE_HIT_RATE_AT_LEAST:.0%})")
        if dollars >= friday_dollars:
            out.append("the bill isn't lower than Friday's")
        return out

    # The first cause found, then the numbers.
    bar, out = config.BAR, []
    first = [t for t in yours if t.number == 1]
    later = [t for t in yours if t.number > 1]
    reasons = [t.reason for t in later if t.reason is not None and not pending(t.reason)] if diagnosed else []
    changed = Counter(reason_kind(r) for r in reasons)
    reads = [t.usage.cache_read_input_tokens or 0 for t in first]
    reading = sum(r > 0 for r in reads)
    # The smallest read on a first turn is the handbook, which every conversation shares.
    handbook = min((r for r in reads if r), default=0)
    past = sum((t.usage.cache_read_input_tokens or 0) > handbook for t in later)
    if changed:
        out += [f"{count} follow-up turns still say {kind}" for kind, count in changed.most_common()]
    elif reading < bar["first_turns_reading"] * len(first):
        out.append(f"first turns read the cache on {reading} of {len(first)} (the bar is {bar['first_turns_reading']:.0%})")
    elif past < bar["follow_ups_past_handbook"] * len(later):
        out.append(f"follow-up turns read past the handbook on {past} of {len(later)}, so they pay again"
                   " for the conversation so far: keep the automatic breakpoint as well as yours")
    if hit_rate < bar["hit_rate"]:
        out.append(f"hit rate {hit_rate:.1%} (the bar is at least {bar['hit_rate']:.0%})")
    if dollars / n > bar["dollars_per_conversation"]:
        out.append(f"${dollars / n:.4f} per conversation (the bar is at most ${bar['dollars_per_conversation']:.4f})")
    return out
