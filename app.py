"""
The weekend readout. Replays the weekend's support traffic through Friday's
code and through yours, then prints cache hit rate and dollars per
conversation on one screen.

    .venv/bin/python app.py                          # your code: starter.py
    .venv/bin/python app.py --requests 6             # show each request of the first 6 conversations
    LAB_SOLUTION=reference .venv/bin/python app.py   # the finished version
"""
import argparse
import copy
import importlib
import os
import sys
from collections import Counter
from datetime import datetime

import config
from clients import has_diagnostics, make_client
from support import HANDBOOK, WEEKEND, friday_request, make_request, replay, send_plain

CLUES = [
    ("meter", "hit rate and dollars"),
    ("send_with_diagnostics", "why each request missed"),
    ("build_request", "move the cache buster"),
    ("place_breakpoint", "place the breakpoint"),
]


class Lab:
    """Calls your 4 functions, and falls back to Friday's code for any you haven't written yet."""

    def __init__(self, solution):
        self.solution = solution
        self.offline = set()  # functions that still raise NotImplementedError

    def build(self, history, question, now):
        try:
            request = self.solution.build_request(history, question, now)
        except NotImplementedError:
            self.offline.add("build_request")
            request = friday_request(history, question, now)
        try:
            return self.solution.place_breakpoint(request)
        except NotImplementedError:
            self.offline.add("place_breakpoint")
            return request

    def send(self, client, request, previous_id):
        if "send_with_diagnostics" in self.offline or not has_diagnostics():
            return send_plain(client, request, previous_id)
        try:
            return self.solution.send_with_diagnostics(client, request, previous_id)
        except NotImplementedError:
            self.offline.add("send_with_diagnostics")
            return send_plain(client, request, previous_id)

    def meter(self, turns):
        try:
            return self.solution.meter([t.usage for t in turns])
        except NotImplementedError:
            self.offline.add("meter")
            return None


def thursday_request(history: list, question: str, now: str) -> dict:
    """Wren's request before Friday's deploy (data/friday.diff): no time, and a breakpoint on the handbook."""
    system = [{"type": "text", "text": HANDBOOK, "cache_control": {"type": "ephemeral"}}]
    return make_request(system, history + [{"role": "user", "content": question}])


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content if b.get("type") == "text")


def new_text(request, history) -> str:
    """The text of every message this turn adds after the history."""
    return "".join(text_of(m["content"]) for m in request["messages"][len(history):])


# Clue 3's check, shared by the readout and tests/test_offline.py so they can't disagree.
# Morning, night, just past midnight, and Monday at the morning's time: a date left in the
# system prompt still changes it once a day, and a time without its date looks the same on
# Saturday and Monday.
CLUE_3_TIMES = ["2026-09-26T09:00:00-07:00", "2026-09-26T23:30:00-07:00",
                "2026-09-27T00:30:00-07:00", "2026-09-28T09:00:00-07:00"]
CLUE_3_HISTORY = [
    {"role": "user", "content": "Do you rent bear canisters?"},
    {"role": "assistant", "content": "Yes, from the Bend store."},
]
CLUE_3_QUESTION = "How much for five days?"


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


def clue_2_problem(friday, yours) -> str | None:
    """The first way send_with_diagnostics() broke its contract during the replay, or None."""
    turns = friday + yours
    if any(isinstance(t.reason, str) and not pending(t.reason) for t in turns):
        return ("send_with_diagnostics() returned a string: return the cache_miss_reason itself"
                " (its .type is the string)")
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


def tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:,}"


def cached(u) -> tuple[int, int]:
    return u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0


PENDING = "pending (check the next turn)"


def pending(reason) -> bool:
    """send_with_diagnostics() returns "pending" when the comparison hadn't finished."""
    return reason == "pending"


def reason_type(reason) -> str:
    """What to print for a reason that isn't None. A string (a clue 2 slip) prints as is."""
    if pending(reason):
        return PENDING
    return reason if isinstance(reason, str) else reason.type


def print_requests(turns, n_conversations: int, diagnosed: bool, live: bool):
    ids = list(dict.fromkeys(t.conversation for t in turns))  # in order of first request
    shown = set(ids[:n_conversations])
    if not shown:
        return
    print("  Your code, request by request (tokens)")
    print(f"    {'conv':<4}  {'turn':>4}  {'time':<8}  {'read':>6}  {'written':>8}  {'uncached':>8}"
          f"  {'output':>6}  cache_miss_reason")
    last = None  # when the request before this one went out, in any conversation
    for t in turns:
        at = datetime.fromisoformat(t.at)
        quiet = (at - last).total_seconds() / 60 if last else 0  # minutes
        last = at
        if t.conversation not in shown:
            continue
        read, written = cached(t.usage)
        if not diagnosed:
            why = "(diagnostics off)"
        elif t.reason is not None:
            missed = getattr(t.reason, "cache_missed_input_tokens", None)
            why = reason_type(t.reason) + (f" (~{missed:,} tokens missed)" if missed else "")
        elif t.number > 1:
            why = "none"
        elif quiet > 5 and not live:
            # Offline, requests run on the traffic's clock. (Live runs go back to back.)
            why = f"none (first turn; {int(quiet)} quiet minutes before it)"
        else:
            why = "none (first turn)"
        print(f"    {t.conversation}  {t.number:>4}  {t.at[11:19]}  {read:>6,}  {written:>8,}"
              f"  {t.usage.input_tokens:>8,}  {t.usage.output_tokens:>6,}  {why}")
    print()


def print_reasons(turns):
    print("  Why requests missed (cache diagnostics, your code)")
    print(f"    {'turn':<6} {'cache_miss_reason':<30} {'requests':>8}  {'read the cache':>14}")
    rows = Counter()
    reads = Counter()
    for t in turns:
        first = t.number == 1
        if t.reason is not None:
            kind = reason_type(t.reason)
        else:
            kind = "none (nothing to compare)" if first else "none (no change)"
        key = ("first" if first else "later", kind)
        rows[key] += 1
        reads[key] += cached(t.usage)[0] > 0
    for key in sorted(rows):
        print(f"    {key[0]:<6} {key[1]:<30} {rows[key]:>8}  {reads[key]:>14}")


def shortfalls(friday_meter, your_meter, turns, n: int, live: bool, diagnosed: bool) -> list[str]:
    """What still stands between your numbers and config.BAR. An empty list closes the case."""
    (_, friday_dollars), (hit_rate, dollars) = friday_meter, your_meter
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
    first = [t for t in turns if t.number == 1]
    later = [t for t in turns if t.number > 1]
    changed = Counter(reason_type(t.reason) for t in later if diagnosed and t.reason is not None and not pending(t.reason))
    reads = [cached(t.usage)[0] for t in first]
    reading = sum(r > 0 for r in reads)
    # The smallest read on a first turn is the handbook, which every conversation shares.
    handbook = min((r for r in reads if r), default=0)
    past = sum(cached(t.usage)[0] > handbook for t in later)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests", type=int, default=3, metavar="N",
                        help="show each request of the first N conversations (default 3)")
    args = parser.parse_args()

    solution_name = os.environ.get("LAB_SOLUTION", "starter")
    try:
        lab = Lab(importlib.import_module(solution_name))
    except ModuleNotFoundError as error:
        if error.name != solution_name:
            raise
        sys.exit(f"No module named {solution_name!r}: LAB_SOLUTION must name a .py file in this folder,"
                 " like starter or reference.")
    live = config.PROVIDER != "offline"
    conversations = WEEKEND[: config.LIVE_CONVERSATIONS] if live else WEEKEND

    friday = replay(make_client(), conversations, friday_request, lab.send)
    yours = replay(make_client(), conversations, lab.build, lab.send)
    friday_meter, your_meter = lab.meter(friday), lab.meter(yours)
    # Offline only (live, it would be 17 more billed requests): the same weekend on Thursday's code.
    thursday_meter = None if live else lab.meter(replay(make_client(), conversations, thursday_request, send_plain))

    mode = f"live on {config.PROVIDER} (real calls, billed)" if live else "offline (simulated tokens, no API calls)"
    print()
    print(f"CACHE DETECTIVE  |  Kestrel Outdoor support chat, weekend of 09/26/26  |  {solution_name}.py")
    print(f"{mode}  |  {config.MODEL}  |  {len(conversations)} conversations, {len(yours)} requests")
    print()
    diagnosed = has_diagnostics() and "send_with_diagnostics" not in lab.offline
    print_requests(yours, args.requests, diagnosed, live)

    n = len(conversations)
    print("                           Friday's code      Your code")
    if friday_meter and your_meter:
        (fh, fd), (yh, yd) = friday_meter, your_meter
        change = ""
        if fd:
            change = "   (no change)" if round((yd - fd) / fd, 2) == 0 else f"   ({(yd - fd) / fd:+.0%})"
        print(f"  Cache hit rate          {fh:>14.1%} {yh:>14.1%}")
        print(f"  $ per conversation      {f'${fd / n:.4f}':>14} {f'${yd / n:.4f}':>14}")
        print(f"  Weekend bill            {f'${fd:.2f}':>14} {f'${yd:.2f}':>14}{change}")
        if thursday_meter and thursday_meter[1]:
            th, td = thursday_meter
            print(f"  Thursday's code, before the deploy: {th:.1%} and ${td / n:.4f} per conversation.")
            print(f"  Friday's code costs {fd / td:.1f}x that: ${fd / n * 10_000:,.0f} vs ${td / n * 10_000:,.0f}"
                  " per 10,000 conversations.")
    else:
        print("  Cache hit rate          clue 1 offline: write meter() in starter.py")
        print("  $ per conversation      clue 1 offline")
    read = sum(cached(t.usage)[0] for t in yours)
    written = sum(cached(t.usage)[1] for t in yours)
    print(f"  Your code's input tokens: {tokens(read)} read from cache, {tokens(written)} written to cache,"
          f" {tokens(sum(t.usage.input_tokens for t in yours))} uncached."
          f" Output: {tokens(sum(t.usage.output_tokens for t in yours))}.")
    print(f"  Prices: Claude API list prices in config.PRICES{' (Bedrock bills at AWS rates)' if config.PROVIDER == 'bedrock' else ''}.")
    print()

    for i, (name, what) in enumerate(CLUES, 1):
        if name == "send_with_diagnostics" and not has_diagnostics():
            status = "Claude API only: cache diagnostics isn't available on Bedrock"
        elif name in lab.offline:
            status = f"offline: write {name}() in starter.py"
            if name == "build_request":
                status += " (until then, your code sends Friday's request)"
        else:
            status = "online"
        print(f"  Clue {i}  {what:<26} {status}")
    print()

    if diagnosed:
        print_reasons(yours)
        print()

    todo = [name for name, _ in CLUES if name in lab.offline]
    if todo:
        print(f"  Next: {todo[0]}() in starter.py. Then run this again.")
        if todo == ["place_breakpoint"]:
            print("  First turns never read the cache. Why not?")
    elif friday_meter and your_meter:
        # What the tests check, in order: clue 2's contract, clue 3's rules, then the numbers against config.BAR.
        short = [p for p in (clue_2_problem(friday, yours) if diagnosed else None,
                             clue_3_problem(lab.solution.build_request)) if p]
        short += shortfalls(friday_meter, your_meter, yours, n, live, diagnosed)
        if short:
            print("  Not yet. All four clues are online, but your code misses the tests' bar:")
            for line in short:
                print(f"    {line}")
        else:
            down = 1 - your_meter[1] / friday_meter[1]
            print(f"  Case closed: $ per conversation is down {down:.0%} from Friday's code.")
            if diagnosed:
                said = [sum(getattr(t.reason, "type", None) == "system_changed" for t in turns if t.number > 1)
                        for turns in (friday, yours)]
                print(f"    The time in the system prompt: {said[0]} follow-up turns said system_changed,"
                      f" now {said[1]}.")
            first = [sum(cached(t.usage)[0] > 0 for t in turns if t.number == 1) for turns in (friday, yours)]
            print(f"    No breakpoint on the handbook: first turns read the cache on {first[0]} of"
                  f" {sum(t.number == 1 for t in yours)}, now {first[1]}.")
            print("  Run the tests to confirm.")
    print()


if __name__ == "__main__":
    main()
