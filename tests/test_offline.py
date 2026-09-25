"""
Offline end-to-end test: the whole lab on the simulated client, with no API
key and no network. It imports the 4 functions from the module named by
LAB_SOLUTION (default: starter), replays the weekend through Friday's code
and through the fix, and checks the fix against config.BAR, the same bar
app.py uses before it says "Case closed".

    .venv/bin/python -m pytest -q tests                           # your starter.py
    .venv/bin/python -m pytest -q tests -k clue_1                 # one clue (clue_1 to clue_4)
    LAB_SOLUTION=reference .venv/bin/python -m pytest -q tests    # the finished version
"""
import copy
import importlib
import os
import sys
import types

import pytest
from anthropic.types import Usage
from anthropic.types.beta import BetaMessage

import config
from offline import OfflineClient
from support import HANDBOOK, WEEKEND, friday_request, make_request, replay, send_plain
from truth import truth

solution = importlib.import_module(os.environ.get("LAB_SOLUTION", "starter"))

# config.BAR is calibrated to the offline client, which counts an earlier
# breakpoint inside the read prefix as a use that refreshes its entry
# (README, "Where the docs are silent").
BAR = config.BAR
offline_only = pytest.mark.skipif(config.PROVIDER != "offline", reason="the readout tests run offline only")


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content if b.get("type") == "text")


def system_text(request) -> str:
    return text_of(request["system"])


def new_text(request, history) -> str:
    """The text of every message this turn adds after the history."""
    return "".join(text_of(m["content"]) for m in request["messages"][len(history):])


def fixed_request(history, question, now):
    return solution.place_breakpoint(solution.build_request(history, question, now))


class CannedClient:
    """Answers client.beta.messages.create with one fixed diagnostics value."""

    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        self.beta = self
        self.messages = self

    def create(self, **request):
        assert "diagnostics" in request, "send a diagnostics object on every request"
        return BetaMessage.model_validate({
            "id": "msg_canned", "type": "message", "role": "assistant", "model": config.MODEL,
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5}, "diagnostics": self.diagnostics,
        })


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
    # Your own prices (Take it to your app): double every price, double the bill.
    doubled = {name: 2 * price for name, price in config.PRICES.items()}
    assert solution.meter(usages, doubled)[1] == pytest.approx(2 * dollars), "price with the prices argument"
    assert solution.meter([]) == (0.0, 0.0), "no usages: a 0.0 hit rate and $0"


def test_clue_2_diagnostics_names_the_culprit():
    turns = replay(OfflineClient(), WEEKEND[:10], friday_request, solution.send_with_diagnostics)
    first = [t for t in turns if t.number == 1]
    later = [t for t in turns if t.number > 1]
    assert later, "the first 10 conversations should include follow-up turns"
    assert all(t.reason is None for t in first), "a first turn has nothing to compare against"
    assert all(t.reason is not None for t in later), "every follow-up turn should name a reason"
    assert {t.reason.type for t in later} == {"system_changed"}


def test_clue_2_tells_pending_from_no_change():
    # The three documented states of response.diagnostics. The offline client
    # never returns pending, so this uses a canned response for each.
    request = make_request(HANDBOOK, [{"role": "user", "content": "Do you rent bear canisters?"}])
    _, none = solution.send_with_diagnostics(CannedClient(None), request, "msg_previous")
    _, still_running = solution.send_with_diagnostics(CannedClient({"cache_miss_reason": None}), request, "msg_previous")
    _, changed = solution.send_with_diagnostics(
        CannedClient({"cache_miss_reason": {"type": "system_changed", "cache_missed_input_tokens": 3200}}),
        request, "msg_previous")
    assert none is None, "diagnostics None means nothing changed (or nothing to compare): return None"
    assert still_running == "pending", 'diagnostics {"cache_miss_reason": null} means the comparison was still running: return "pending"'
    assert changed.type == "system_changed", "return the cache_miss_reason itself"


def test_clue_3_system_prompt_is_stable_and_the_time_moved():
    history = [
        {"role": "user", "content": "Do you rent bear canisters?"},
        {"role": "assistant", "content": "Yes, from the Bend store."},
    ]
    before = copy.deepcopy(history)
    # Morning, night, and just past midnight: a date left in the system prompt still changes it once a day.
    times = ["2026-09-26T09:00:00-07:00", "2026-09-26T23:30:00-07:00", "2026-09-27T00:30:00-07:00"]
    requests = [solution.build_request(history, "How much for five days?", now) for now in times]
    morning = requests[0]
    assert history == before, "don't change history: build a new list, like history + [message]"
    assert morning["messages"][: len(history)] == history, "send the history unchanged, then the new message"
    assert len({system_text(r) for r in requests}) == 1, "the system prompt must not change with the time, or the date"
    assert HANDBOOK in system_text(morning), "keep the handbook as the system prompt"
    assert len({new_text(r, history) for r in requests}) == len(times), "Wren still needs the time: put `now` in the new user message"
    new = morning["messages"][len(history):]
    assert new[0]["role"] == "user" and "How much for five days?" in text_of(new[0]["content"]), (
        "the customer's new message comes right after the history")
    # On Opus 5.5 a {"role": "system"} message can follow the new user message (one before it is a 400).
    assert all(m["role"] == "system" for m in new[1:]), "end on the customer's new message"


def test_clue_4_new_conversations_read_the_handbook_from_the_cache():
    turns = replay(OfflineClient(), WEEKEND, fixed_request, send_plain)
    first = [t for t in turns if t.number == 1]
    reading = [t for t in first if (t.usage.cache_read_input_tokens or 0) > 0]
    # Most first turns read the handbook another conversation wrote. The rest
    # come after a quiet stretch longer than the 5-minute TTL.
    assert len(reading) / len(first) >= BAR["first_turns_reading"]


def test_clue_4_follow_up_turns_still_read_the_conversation():
    turns = replay(OfflineClient(), WEEKEND, fixed_request, send_plain)
    # The smallest read on a first turn is the handbook, which every conversation shares.
    handbook = min((t.usage.cache_read_input_tokens for t in turns
                    if t.number == 1 and t.usage.cache_read_input_tokens), default=0)
    later = [t for t in turns if t.number > 1]
    past_handbook = [t for t in later if (t.usage.cache_read_input_tokens or 0) > handbook]
    assert len(past_handbook) / len(later) >= BAR["follow_ups_past_handbook"], (
        "follow-up turns read only the handbook, and pay full price for the conversation so far: "
        "keep the automatic breakpoint (the top-level cache_control) as well as yours"
    )


def test_the_weekend_before_and_after_the_fix():
    friday = replay(OfflineClient(), WEEKEND, friday_request, solution.send_with_diagnostics)
    fixed = replay(OfflineClient(), WEEKEND, fixed_request, solution.send_with_diagnostics)
    n = len(WEEKEND)

    friday_hit, friday_dollars = truth(t.usage for t in friday)
    fixed_hit, fixed_dollars = truth(t.usage for t in fixed)

    assert friday_hit < 0.01, "Friday's code should almost never read the cache"
    assert fixed_hit >= BAR["hit_rate"], f"fixed hit rate {fixed_hit:.1%}"
    assert fixed_dollars / n <= BAR["dollars_per_conversation"], f"fixed ${fixed_dollars / n:.4f} per conversation"
    assert friday_dollars / fixed_dollars >= BAR["friday_over_fixed"], "the fix should cut the bill to about a third"

    # After the fix, diagnostics finds nothing changing between turns.
    assert not [t for t in fixed if t.reason is not None]

    # And your meter agrees with the test's. (If you tried the 1h TTL, meter()
    # needs usage.cache_creation to price those writes; see Keep going.)
    hit_rate, dollars = solution.meter([t.usage for t in fixed])
    assert hit_rate == pytest.approx(fixed_hit, rel=1e-6)
    if not any(t.usage.cache_creation and t.usage.cache_creation.ephemeral_1h_input_tokens for t in fixed):
        assert dollars == pytest.approx(fixed_dollars, rel=1e-6)

    # A fix that clears this test's bar clears the readout's too, so app.py says "Case closed".
    import app
    assert not app.shortfalls((friday_hit, friday_dollars), (fixed_hit, fixed_dollars), fixed, n,
                              live=False, diagnosed=True)


def readout(monkeypatch, capsys, **swap) -> str:
    """What app.py prints for your solution, with any of its 4 functions swapped out."""
    import app

    module = types.ModuleType("readout_under_test")
    for name in ("meter", "send_with_diagnostics", "build_request", "place_breakpoint"):
        setattr(module, name, swap.get(name, getattr(solution, name)))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("LAB_SOLUTION", module.__name__)
    monkeypatch.setattr(sys, "argv", ["app.py"])
    app.main()
    return capsys.readouterr().out


@offline_only
def test_the_readout_runs(capsys, monkeypatch):
    out = readout(monkeypatch, capsys)
    assert "CACHE DETECTIVE" in out
    assert any(s in out for s in ("Next:", "Not yet", "Case closed")), (
        "the readout should name the next function, say what's still wrong, or close the case")


def no_automatic_breakpoint(request):
    request = solution.place_breakpoint(request)
    return {key: value for key, value in request.items() if key != "cache_control"}


@offline_only
@pytest.mark.parametrize("wrong_fix", [
    {"place_breakpoint": lambda request: request},  # no breakpoint: first turns never read
    {"build_request": friday_request},  # the time still in the system prompt
    {"place_breakpoint": no_automatic_breakpoint},  # follow-up turns read only the handbook
], ids=["no breakpoint", "time in the system prompt", "no automatic breakpoint"])
def test_the_readout_closes_the_case_only_on_a_real_fix(capsys, monkeypatch, wrong_fix):
    # With your other functions, each wrong fix must fall short of config.BAR on screen too.
    assert "Case closed" not in readout(monkeypatch, capsys, **wrong_fix)
