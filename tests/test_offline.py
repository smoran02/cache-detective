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
import importlib
import os
import sys
import types

import pytest
from anthropic.types import CacheCreation, Usage
from anthropic.types.beta import BetaMessage

import config
from app import clue_3_problem, thursday_request
from offline import OfflineClient
from support import HANDBOOK, WEEKEND, friday_request, make_request, replay, send_plain
from truth import truth

solution = importlib.import_module(os.environ.get("LAB_SOLUTION", "starter"))

# config.BAR is calibrated to the offline client, which counts an earlier
# breakpoint inside the read prefix as a use that refreshes its entry
# (README, "How offline mode works").
BAR = config.BAR
offline_only = pytest.mark.skipif(config.PROVIDER != "offline", reason="the readout tests run offline only")


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
    # 1,000 tokens written with a 1-hour TTL. cache_creation_input_tokens already counts them, so
    # price each once: at $5/MTok as the starter asks, or at $8 if you did Keep going's TTL step.
    one_hour = Usage(input_tokens=0, output_tokens=0, cache_creation_input_tokens=1000, cache_read_input_tokens=0,
                     cache_creation=CacheCreation(ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=1000))
    assert solution.meter([one_hour])[1] in (pytest.approx(0.005), pytest.approx(0.008)), (
        "price each written token once: cache_creation_input_tokens already includes the 1-hour writes")


def test_clue_2_diagnostics_names_the_culprit():
    turns = replay(OfflineClient(), WEEKEND[:10], friday_request, solution.send_with_diagnostics)
    first = [t for t in turns if t.number == 1]
    later = [t for t in turns if t.number > 1]
    assert later, "the first 10 conversations should include follow-up turns"
    assert all(t.reason is None for t in first), "a first turn has nothing to compare against: return None"
    assert all(t.reason is not None for t in later), "every follow-up turn should name a reason"
    assert not any(isinstance(t.reason, str) for t in later), (
        "return the cache_miss_reason itself, not its .type (the readout reads .type)")
    kinds = {t.reason.type for t in later}
    assert kinds == {"system_changed"}, (
        f"got {sorted(kinds)}. previous_message_not_found means the turn before went out without a diagnostics object")


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
    assert not isinstance(changed, str), "return the cache_miss_reason itself, not its .type"
    assert changed.type == "system_changed", "return the cache_miss_reason itself"


def test_clue_3_system_prompt_is_stable_and_the_time_moved():
    # Builds one turn at four times: 09:00 and 23:30 on Saturday, 00:30 on Sunday, and 09:00 on Monday.
    # The system prompt must be the same at all four, and the new message different at all four, so a
    # date left in the system prompt fails, and so does a time with no date. The readout runs the same
    # check (app.clue_3_problem) before it says "Case closed".
    problem = clue_3_problem(solution.build_request)
    assert problem is None, problem


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


def time_after_the_question(history, question, now):
    return make_request(HANDBOOK, history + [{"role": "user", "content": question},
                                             {"role": "user", "content": f"Current time: {now}"}])


def appends_to_history(history, question, now):
    history.append({"role": "user", "content": f"Current time: {now}\n\n{question}"})
    return make_request(HANDBOOK, history)


def returns_the_type(client, request, previous_id):
    response, reason = solution.send_with_diagnostics(client, request, previous_id)
    return response, getattr(reason, "type", reason)


def swaps_none_and_pending(client, request, previous_id):
    response, reason = solution.send_with_diagnostics(client, request, previous_id)
    return response, "pending" if reason is None else None if reason == "pending" else reason


def no_diagnostics_object(client, request, previous_id):
    return client.beta.messages.create(**request), None


@offline_only
@pytest.mark.parametrize("wrong_fix, says", [
    ({"place_breakpoint": lambda request: request}, "first turns read the cache on"),
    ({"build_request": friday_request}, "the system prompt must not change"),
    ({"place_breakpoint": no_automatic_breakpoint}, "follow-up turns read past the handbook on"),
    ({"build_request": thursday_request}, "Wren needs the time, date included"),
    ({"build_request": time_after_the_question}, "end on the customer's new message"),
    ({"build_request": appends_to_history}, "don't change history"),
    ({"send_with_diagnostics": returns_the_type}, "returned a string"),
    ({"send_with_diagnostics": swaps_none_and_pending}, "a first turn has nothing to compare"),
    ({"send_with_diagnostics": no_diagnostics_object}, "send a diagnostics object on every request"),
], ids=["no breakpoint", "time in the system prompt", "no automatic breakpoint", "Friday's deploy rolled back",
        "time after the question", "history.append", "reason.type", "None and pending swapped",
        "no diagnostics object"])
def test_the_readout_closes_the_case_only_on_a_real_fix(capsys, monkeypatch, wrong_fix, says):
    # With your other functions, each wrong fix must fall short on screen too, and say why.
    out = readout(monkeypatch, capsys, **wrong_fix)
    assert "Case closed" not in out
    assert "Next:" in out or says in out, f"the readout should say {says!r} (if a clue test fails too, fix that first)"


@offline_only
def test_the_readout_shows_the_readmes_numbers(capsys, monkeypatch):
    # The README's checkpoint table, on reference.py. Editing handbook.md or weekend.json moves
    # these, so update the README (and the numbers in config.py and offline.py) with them.
    reference = pytest.importorskip("reference")
    out = readout(monkeypatch, capsys, **{name: getattr(reference, name) for name in
                                          ("meter", "send_with_diagnostics", "build_request", "place_breakpoint")})
    for number in ("0.0%", "$0.0539", "$0.0172 per conversation", "3.1x", "90.8%", "$0.0171",
                   "3,098", "411 follow-up turns said system_changed, now 0", "on 0 of 252, now 202", "Case closed"):
        assert number in out, f"the readout no longer shows {number}: update the README's checkpoint table"
