"""
Offline end-to-end test: the whole lab on the simulated client, with no API
key and no network. It imports the 4 functions from the module named by
LAB_SOLUTION (default: starter), checks each against its clue's contract
(checks.py, which the readout runs too), replays the weekend through Friday's
code and through the fix, and checks the fix against config.BAR, the same bar
app.py uses before it says "Case closed".

    .venv/bin/python -m pytest -q tests                           # your starter.py
    .venv/bin/python -m pytest -q tests -k clue_1                 # one clue (clue_1 to clue_4)
    LAB_SOLUTION=reference .venv/bin/python -m pytest -q tests    # the finished version
"""
import importlib
import json
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

import app
import cache_check
import config
from app import thursday_request
from checks import clue_1_problem, clue_2_problem, clue_3_problem, clue_4_problem, reason_problem, shortfalls, truth
from offline import OfflineClient
from support import HANDBOOK, WEEKEND, friday_request, make_request, replay, send_plain

solution = importlib.import_module(os.environ.get("LAB_SOLUTION", "starter"))
FUNCTIONS = ("meter", "send_with_diagnostics", "build_request", "place_breakpoint")

# config.BAR is calibrated to the offline client, which counts an earlier
# breakpoint inside the read prefix as a use that refreshes its entry
# (README, "How offline mode works").
BAR = config.BAR
offline_only = pytest.mark.skipif(config.PROVIDER != "offline", reason="the readout tests run offline only")


def fixed_request(history, question, now):
    return solution.place_breakpoint(solution.build_request(history, question, now))


def test_clue_1_meter_reads_and_prices_the_usage_fields():
    # Three usages whose four dollar terms all differ, your own prices, no usages at all, and
    # writes split by TTL (checks.clue_1_problem). The readout runs the same check.
    problem = clue_1_problem(solution.meter)
    assert problem is None, problem


def test_clue_2_diagnostics_names_the_culprit():
    turns = replay(OfflineClient(), WEEKEND[:10], friday_request, solution.send_with_diagnostics)
    first = [t for t in turns if t.number == 1]
    later = [t for t in turns if t.number > 1]
    assert later, "the first 10 conversations should include follow-up turns"
    assert all(t.reason is None for t in first), "a first turn has nothing to compare against: return None"
    assert all(t.reason is not None for t in later), "every follow-up turn should name a reason"
    problem = next(filter(None, (reason_problem(t.reason) for t in later)), None)
    assert problem is None, problem
    kinds = {t.reason.type for t in later}
    assert kinds == {"system_changed"}, (
        f"got {sorted(kinds)}. previous_message_not_found means the turn before went out without a diagnostics object")


def test_clue_2_returns_each_documented_state():
    # None, pending, and three reasons, from a canned client (checks.clue_2_problem): the offline
    # client never returns pending, unavailable, or previous_message_not_found on the lab's traffic.
    problem = clue_2_problem(solution.send_with_diagnostics)
    assert problem is None, problem


def test_clue_3_system_prompt_is_stable_and_the_time_moved():
    # Builds one turn at five times (checks.CLUE_3_TIMES). The system prompt must be the same at all
    # five, and the new message different at all five, so a date left in the system prompt fails, and
    # so does a time with no date, or a weekday with no date. The readout runs the same check.
    problem = clue_3_problem(solution.build_request)
    assert problem is None, problem


def test_clue_4_marks_the_system_prompt_it_was_given():
    # A system prompt other than the bare handbook, as a string and as a list of blocks
    # (checks.clue_4_problem): its text must survive, with a breakpoint on it.
    problem = clue_4_problem(solution.place_breakpoint)
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
    assert not shortfalls(friday, fixed, n, live=False, diagnosed=True)


def readout(monkeypatch, capsys, *args, **swap) -> str:
    """What app.py prints for your solution, with any of its 4 functions swapped out."""
    module = types.ModuleType("readout_under_test")
    for name in FUNCTIONS:
        setattr(module, name, swap.get(name, getattr(solution, name)))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("LAB_SOLUTION", module.__name__)
    monkeypatch.setattr(sys, "argv", ["app.py", *args])
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


def replaces_the_system_prompt(request):
    return {**request, "system": [{"type": "text", "text": HANDBOOK, "cache_control": {"type": "ephemeral"}}]}


def time_after_the_question(history, question, now):
    return make_request(HANDBOOK, history + [{"role": "user", "content": question},
                                             {"role": "user", "content": f"Current time: {now}"}])


def time_at_the_end_of_the_system_prompt(history, question, now):
    return make_request(f"{HANDBOOK}\n\nCurrent time: {now}", history + [{"role": "user", "content": question}])


def weekday_and_clock(history, question, now):
    when = datetime.fromisoformat(now)
    return make_request(HANDBOOK, history + [{"role": "user", "content": f"Current time: {when:%A %I:%M %p}\n\n{question}"}])


def appends_to_history(history, question, now):
    history.append({"role": "user", "content": f"Current time: {now}\n\n{question}"})
    return make_request(HANDBOOK, history)


def returns_the_type(client, request, previous_id):
    response, reason = solution.send_with_diagnostics(client, request, previous_id)
    return response, getattr(reason, "type", reason)


def swaps_none_and_pending(client, request, previous_id):
    response, reason = solution.send_with_diagnostics(client, request, previous_id)
    return response, "pending" if reason is None else None if reason == "pending" else reason


def pending_as_none(client, request, previous_id):
    response, reason = solution.send_with_diagnostics(client, request, previous_id)
    return response, None if reason == "pending" else reason


def unavailable_as_none(client, request, previous_id):
    response, reason = solution.send_with_diagnostics(client, request, previous_id)
    return response, None if getattr(reason, "type", None) in ("unavailable", "previous_message_not_found") else reason


def returns_the_diagnostics(client, request, previous_id):
    response = client.beta.messages.create(**request, diagnostics={"previous_message_id": previous_id})
    return response, response.diagnostics


def no_diagnostics_object(client, request, previous_id):
    return client.beta.messages.create(**request), None


def metered(output=True, write_price="cache_write_5m", read_price="cache_read", one_hour_for_all=False):
    """A meter() with one pricing slip."""
    def meter(usages, prices=None):
        prices = prices or config.PRICES
        read = total = 0
        dollars = 0.0
        for u in usages:
            r, w = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
            one_hour = u.cache_creation and u.cache_creation.ephemeral_1h_input_tokens
            read, total = read + r, total + r + w + u.input_tokens
            write = prices["cache_write_1h"] if one_hour_for_all and one_hour else prices[write_price]
            reads = 0.1 * prices["input"] if read_price == "0.1x" else prices[read_price]
            dollars += u.input_tokens * prices["input"] + w * write + r * reads + output * u.output_tokens * prices["output"]
        return (read / total if total else 0.0), dollars
    return meter


@offline_only
@pytest.mark.parametrize("wrong_fix, says", [
    ({"place_breakpoint": lambda request: request}, "first turns read the cache on"),
    ({"build_request": friday_request}, "the system prompt must not change"),
    ({"build_request": time_at_the_end_of_the_system_prompt}, "the system prompt must not change"),
    ({"place_breakpoint": no_automatic_breakpoint}, "follow-up turns read past the handbook on"),
    ({"place_breakpoint": replaces_the_system_prompt}, "its text changed"),
    ({"build_request": thursday_request}, "Wren needs the time, date included"),
    ({"build_request": weekday_and_clock}, "Wren needs the time, date included"),
    ({"build_request": time_after_the_question}, "end on the customer's new message"),
    ({"build_request": appends_to_history}, "don't change history"),
    ({"send_with_diagnostics": returns_the_type}, "returned a string"),
    ({"send_with_diagnostics": swaps_none_and_pending}, "diagnostics None means nothing changed"),
    ({"send_with_diagnostics": pending_as_none}, "the comparison was still running"),
    ({"send_with_diagnostics": unavailable_as_none}, "unavailable means the comparison couldn't run"),
    ({"send_with_diagnostics": returns_the_diagnostics}, "returned response.diagnostics"),
    ({"send_with_diagnostics": no_diagnostics_object}, "send a diagnostics object on every request"),
    ({"meter": metered(output=False)}, "output_tokens are left out"),
    ({"meter": metered(write_price="input")}, "cache writes are priced at prices['input']"),
    ({"meter": metered(read_price="0.1x")}, "cache reads are priced at 0.1x input"),
    ({"meter": metered(one_hour_for_all=True)}, "at 1 hour cost"),
], ids=["no breakpoint", "time in the system prompt", "time at the end of the system prompt",
        "no automatic breakpoint", "system prompt replaced", "Friday's deploy rolled back", "weekday, no date",
        "time after the question", "history.append", "reason.type", "None and pending swapped",
        "pending as None", "unavailable as None", "response.diagnostics", "no diagnostics object",
        "meter without output", "writes at the input price", "reads at 0.1x", "all writes at 1 hour"])
def test_the_readout_closes_the_case_only_on_a_real_fix(capsys, monkeypatch, wrong_fix, says):
    # With your other functions, each wrong fix must fall short on screen too, and say why.
    out = readout(monkeypatch, capsys, **wrong_fix)
    assert "Case closed" not in out
    assert "Next:" in out or says in out, f"the readout should say {says!r} (if a clue test fails too, fix that first)"


def not_written(*args):
    raise NotImplementedError


@offline_only
def test_the_readout_checks_clue_3_before_pointing_to_clue_4(capsys, monkeypatch):
    # With place_breakpoint() still to write, a wrong clue 3 is named before "Next:", and the
    # clue 4 teaser shows only once follow-up turns read the cache and first turns don't.
    reference = pytest.importorskip("reference")
    stage = {name: getattr(reference, name) for name in FUNCTIONS} | {"place_breakpoint": not_written}
    out = readout(monkeypatch, capsys, **stage)
    assert "Next: place_breakpoint()" in out and "First turns never read the cache. Why not?" in out
    out = readout(monkeypatch, capsys, **stage | {"build_request": time_at_the_end_of_the_system_prompt})
    assert "Clue 3: the system prompt must not change" in out
    assert "First turns never read" not in out


@offline_only
def test_the_readout_shows_the_readmes_numbers(capsys, monkeypatch):
    # The README's checkpoint table, on reference.py. Editing handbook.md or weekend.json moves
    # these, so update the README (and the numbers in config.py and offline.py) with them.
    reference = pytest.importorskip("reference")
    out = readout(monkeypatch, capsys, **{name: getattr(reference, name) for name in FUNCTIONS})
    for number in ("0.0%", "$0.0890", "$0.0299 per conversation", "3.0x", "90.7%", "$0.0293",
                   "4,972", "411 follow-up turns said system_changed, now 0", "on 0 of 252, now 202", "Case closed"):
        assert number in out, f"the readout no longer shows {number}: update the README's checkpoint table"


def through_cache_check(build, diagnostics=True):
    """The weekend, every request sent by one CacheCheck, which carries each conversation's last id itself."""
    client = OfflineClient()
    check = cache_check.CacheCheck(client, config.PRICES, diagnostics=diagnostics)
    conversation_of = {}  # response id -> conversation: replay() hands send() only the previous id

    def send(client, request, previous_id):
        conversation = conversation_of[previous_id] if previous_id else object()
        assert check.last_id.get(conversation) == previous_id, "create() should carry the id forward as replay() does"
        response = check.create(conversation, **request)
        conversation_of[response.id] = conversation
        return response, None

    replay(client, WEEKEND, build, send)
    return check


@offline_only
def test_cache_check_reports_what_the_readout_does(capsys, monkeypatch, tmp_path):
    # README, Take it to your app: cache_check.py on the weekend, sending the reference's fix through
    # create() or reading back app.py --log, gives the readout's hit rate and weekend bill for your code.
    reference = pytest.importorskip("reference")
    log = tmp_path / "usage.jsonl"
    out = readout(monkeypatch, capsys, "--log", str(log), **{name: getattr(reference, name) for name in FUNCTIONS})
    hit_rate = next(line.split()[-1] for line in out.splitlines() if "Cache hit rate" in line)  # your code's column
    bill = next(line.split()[3] for line in out.splitlines() if "Weekend bill" in line)
    requests = sum(len(c["turns"]) for c in WEEKEND)
    readouts = f"{requests} requests: {hit_rate} of input read from the cache, {bill}\nMiss reasons: none"
    assert cache_check.report(cache_check.load(str(log)), config.PRICES) == readouts

    def fixed(history, question, now):
        return reference.place_breakpoint(reference.build_request(history, question, now))

    # With diagnostics it names diagnostics' reason; with diagnostics=False, the part that changed.
    follow_ups = requests - len(WEEKEND)
    for diagnostics, friday in ((True, "system_changed"), (False, "system")):
        assert through_cache_check(fixed, diagnostics).report() == readouts
        assert through_cache_check(friday_request, diagnostics).report().endswith(
            f"Miss reasons: {friday} {follow_ups}")


def test_cache_check_reports_a_usage_log(tmp_path):
    # python cache_check.py usage.jsonl on 4 requests, at Opus 5.5 prices. Two write 100,000 tokens
    # ($0.50 each), one reads them ($0.02) and writes 2,000 at 1 hour ($0.016), one has 1,000 uncached
    # and no cache fields ($0.004), and each outputs 1,000 ($0.02): $1.12, and 100,000 of 303,000 input read.
    write = {"input_tokens": 0, "output_tokens": 1000, "cache_creation_input_tokens": 100_000,
             "cache_read_input_tokens": 0}
    read = {"input_tokens": 0, "output_tokens": 1000, "cache_creation_input_tokens": 2000,
            "cache_read_input_tokens": 100_000,
            "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 2000}}
    bare = {"input_tokens": 1000, "output_tokens": 1000, "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None}
    log = tmp_path / "usage.jsonl"
    log.write_text("".join(json.dumps({"usage": usage, "reason": reason}) + "\n" for usage, reason in
                           ((write, None), (write, "system_changed"), (read, "pending"), (bare, None))))
    run = subprocess.run([sys.executable, "cache_check.py", str(log)], cwd=Path(__file__).parent.parent,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert run.stdout == ("4 requests: 33.0% of input read from the cache, $1.12\n"
                          "Miss reasons: system_changed 1, pending 1\n")
    assert cache_check.PRICES == config.PRICES, "cache_check.py's prices should match config.PRICES"
