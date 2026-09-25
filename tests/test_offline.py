"""
Offline end-to-end test: the whole lab on the simulated client, with no API
key and no network. It imports the 4 functions from the module named by
LAB_SOLUTION (default: starter), replays the weekend through Friday's code
and through the fix, and checks the fixed hit rate and $ per conversation.

    .venv/bin/python -m pytest -q tests                           # your starter.py
    LAB_SOLUTION=reference .venv/bin/python -m pytest -q tests    # the finished version
"""
import importlib
import os

import pytest
from anthropic.types import Usage

import config
from offline import OfflineClient
from support import HANDBOOK, WEEKEND, friday_request, replay

solution = importlib.import_module(os.environ.get("LAB_SOLUTION", "starter"))

# What the fix should reach on the weekend traffic. The reference gets a
# 90.8% hit rate and $0.0171 per conversation, about a third of Friday's
# $0.0539. The bounds leave room for small differences, like how you word
# the time in the user message.
FIXED_HIT_RATE_AT_LEAST = 0.88
FIXED_DOLLARS_PER_CONVERSATION_AT_MOST = 0.0190
FRIDAY_OVER_FIXED_AT_LEAST = 2.8


def truth(usages) -> tuple[float, float]:
    """The test's own meter, so a bug in meter() can't hide a bad fix."""
    read = written = uncached = 0
    dollars = 0.0
    for u in usages:
        r, w = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        w_1h = u.cache_creation.ephemeral_1h_input_tokens if u.cache_creation else 0
        read, written, uncached = read + r, written + w, uncached + u.input_tokens
        dollars += (u.input_tokens * config.PRICES["input"] + (w - w_1h) * config.PRICES["cache_write_5m"]
                    + w_1h * config.PRICES["cache_write_1h"] + r * config.PRICES["cache_read"]
                    + u.output_tokens * config.PRICES["output"])
    return read / (read + written + uncached), dollars


def system_text(request) -> str:
    system = request["system"]
    if isinstance(system, str):
        return system
    return "".join(b["text"] for b in system)


def last_user_text(request) -> str:
    content = request["messages"][-1]["content"]
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content if b.get("type") == "text")


def fixed_request(history, question, now):
    return solution.place_breakpoint(solution.build_request(history, question, now))


def test_clue_1_meter_reads_and_prices_the_usage_fields():
    usages = [
        Usage(input_tokens=100, output_tokens=50, cache_creation_input_tokens=1000, cache_read_input_tokens=0),
        Usage(input_tokens=20, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=1000),
        Usage(input_tokens=30, output_tokens=10, cache_creation_input_tokens=None, cache_read_input_tokens=None),
    ]
    hit_rate, dollars = solution.meter(usages)
    # 1,000 of 2,150 input tokens came from the cache.
    assert hit_rate == pytest.approx(1000 / 2150)
    # 150 uncached at $4/MTok + 1,000 written at $5 + 1,000 read at $0.20 + 110 output at $20.
    assert dollars == pytest.approx(0.0006 + 0.005 + 0.0002 + 0.0022)


def test_clue_2_diagnostics_names_the_culprit():
    turns = replay(OfflineClient(), WEEKEND[:10], friday_request, solution.send_with_diagnostics)
    first = [t for t in turns if t.number == 1]
    later = [t for t in turns if t.number > 1]
    assert later, "the first 10 conversations should include follow-up turns"
    assert all(t.reason is None for t in first), "a first turn has nothing to compare against"
    assert {t.reason.type for t in later if t.reason is not None} == {"system_changed"}
    assert all(t.reason is not None for t in later), "every follow-up turn should name a reason"


def test_clue_3_system_prompt_is_stable_and_the_time_moved():
    history = [
        {"role": "user", "content": "Do you rent bear canisters?"},
        {"role": "assistant", "content": "Yes, from the Bend store."},
    ]
    morning = solution.build_request(history, "How much for five days?", "2026-09-26T09:00:00-07:00")
    night = solution.build_request(history, "How much for five days?", "2026-09-26T23:30:00-07:00")
    assert system_text(morning) == system_text(night), "the system prompt must not change with the time"
    assert HANDBOOK in system_text(morning), "keep the handbook as the system prompt"
    assert "2026-09-26T09:00:00-07:00" not in system_text(morning)
    assert "2026-09-26T09:00:00-07:00" in last_user_text(morning), "Wren still needs the time: put it in the new user message"
    assert "How much for five days?" in last_user_text(morning)
    assert morning["messages"][: len(history)] == history, "send the history unchanged, then the new message"


def test_clue_4_new_conversations_read_the_handbook_from_the_cache():
    turns = replay(OfflineClient(), WEEKEND, fixed_request, solution.send_with_diagnostics)
    first = [t for t in turns if t.number == 1]
    reading = [t for t in first if (t.usage.cache_read_input_tokens or 0) > 0]
    # Most first turns read the handbook another conversation wrote. The rest
    # come after a quiet stretch longer than the 5-minute TTL.
    assert len(reading) / len(first) >= 0.75


def test_the_weekend_before_and_after_the_fix():
    friday = replay(OfflineClient(), WEEKEND, friday_request, solution.send_with_diagnostics)
    fixed = replay(OfflineClient(), WEEKEND, fixed_request, solution.send_with_diagnostics)
    n = len(WEEKEND)

    friday_hit, friday_dollars = truth(t.usage for t in friday)
    fixed_hit, fixed_dollars = truth(t.usage for t in fixed)

    assert friday_hit < 0.01, "Friday's code should almost never read the cache"
    assert fixed_hit >= FIXED_HIT_RATE_AT_LEAST, f"fixed hit rate {fixed_hit:.1%}"
    assert fixed_dollars / n <= FIXED_DOLLARS_PER_CONVERSATION_AT_MOST, f"fixed ${fixed_dollars / n:.4f} per conversation"
    assert friday_dollars / fixed_dollars >= FRIDAY_OVER_FIXED_AT_LEAST, "the fix should cut the bill to about a third"

    # After the fix, diagnostics finds nothing changing between turns.
    assert not [t for t in fixed if t.reason is not None]

    # And your meter agrees with the test's. (If you tried the 1h TTL, meter()
    # needs usage.cache_creation to price those writes; see Keep going.)
    hit_rate, dollars = solution.meter([t.usage for t in fixed])
    assert hit_rate == pytest.approx(fixed_hit, rel=1e-6)
    if not any(t.usage.cache_creation and t.usage.cache_creation.ephemeral_1h_input_tokens for t in fixed):
        assert dollars == pytest.approx(fixed_dollars, rel=1e-6)
