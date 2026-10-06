"""
The weekend readout. Replays the weekend's support traffic through Friday's
code and through yours, then prints cache hit rate and dollars per
conversation on one screen.

    .venv/bin/python app.py                          # your code: starter.py
    .venv/bin/python app.py --requests 6             # show each request of the first 6 conversations
    .venv/bin/python app.py --log usage.jsonl        # also log your code's usage, for cache_check.py
    LAB_SOLUTION=reference .venv/bin/python app.py   # the finished version

Before it says "Case closed", it runs the tests' checks (checks.py) and bar.
"""
import argparse
import importlib
import json
import os
import sys
from collections import Counter
from datetime import datetime

import config
from checks import (clue_1_problem, clue_2_problem, clue_2_replay_problem, clue_3_problem, clue_4_problem,
                    pending, reason_kind, shortfalls)
from clients import make_client
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
        if "send_with_diagnostics" in self.offline:
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
    """Wren's request on Thursday, before Friday's deploy (data/friday.diff)."""
    system = [{"type": "text", "text": HANDBOOK, "cache_control": {"type": "ephemeral"}}]
    return make_request(system, history + [{"role": "user", "content": question}])


def tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:,}"


def cached(u) -> tuple[int, int]:
    return u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0


PENDING = "pending (check the next turn)"


def reason_type(reason) -> str:
    """What to print for a reason that isn't None."""
    return PENDING if pending(reason) else reason_kind(reason)


def problems(solution, online: set, friday, yours, diagnosed: bool) -> list[str]:
    """Each written clue's first problem, in clue order, by the tests' own checks (checks.py)."""
    found = [
        "meter" in online and clue_1_problem(solution.meter),
        diagnosed and (clue_2_problem(solution.send_with_diagnostics) or clue_2_replay_problem(friday, yours)),
        "build_request" in online and clue_3_problem(solution.build_request),
        "place_breakpoint" in online and clue_4_problem(solution.place_breakpoint),
    ]
    return [f"Clue {i}: {problem}" for i, problem in enumerate(found, 1) if problem]


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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests", type=int, default=3, metavar="N",
                        help="show each request of the first N conversations (default 3)")
    parser.add_argument("--log", metavar="FILE",
                        help="write your code's usage and miss reasons to FILE, one JSON line per request")
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

    if live:
        n = sum(len(c["turns"]) for c in conversations)
        print(f"\nLive on {config.PROVIDER}: {n} billed requests through Friday's code, then {n} through yours,"
              " one at a time. About 3 minutes.", file=sys.stderr)
    friday = replay(make_client(), conversations, friday_request, lab.send, label="Friday's code" if live else None)
    yours = replay(make_client(), conversations, lab.build, lab.send, label="Your code" if live else None)
    friday_meter, your_meter = lab.meter(friday), lab.meter(yours)
    # Offline only (live, it would be 17 more billed requests): the same weekend on Thursday's code.
    thursday_meter = None if live else lab.meter(replay(make_client(), conversations, thursday_request, send_plain))

    mode = f"live on {config.PROVIDER} (real calls, billed)" if live else "offline (simulated client, no API calls)"
    print()
    print(f"CACHE DETECTIVE  |  Kestrel Outdoor support chat, weekend of 09/26/26  |  {solution_name}.py")
    print(f"{mode}  |  {config.MODEL}  |  {len(conversations)} conversations, {len(yours)} requests")
    opening = conversations[0]["turns"][0]
    print(f'Wren\'s first customer, {conversations[0]["id"]} at {opening["at"][11:16]}: "{opening["text"]}"')
    print()
    diagnosed = "send_with_diagnostics" not in lab.offline
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
    print("  Prices: Claude API list prices in config.PRICES.")
    print()

    for i, (name, what) in enumerate(CLUES, 1):
        if name in lab.offline:
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
    found = problems(lab.solution, {name for name, _ in CLUES} - lab.offline, friday, yours, diagnosed)
    if todo:
        for line in found:
            print(f"  Not yet. {line}")
        print(f"  Next: {todo[0]}() in starter.py{', once that is fixed' if found else ''}. Then run this again.")
        reading = [sum(cached(t.usage)[0] > 0 for t in yours if (t.number == 1) is first) for first in (True, False)]
        if todo == ["place_breakpoint"] and not found and reading[0] == 0 and reading[1]:
            print("  First turns never read the cache. Why not?")
    elif friday_meter and your_meter:
        # What the tests check, in order: each clue's contract, then the numbers against config.BAR.
        short = found + shortfalls(friday, yours, n, live, diagnosed)
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
    if args.log:
        with open(args.log, "w") as log:
            for t in yours:  # the lines cache_check.py's CacheCheck writes
                reason = None if t.reason is None else reason_kind(t.reason)
                log.write(json.dumps({"usage": t.usage.to_dict(), "reason": reason}) + "\n")
        print(f"  Logged your code's {len(yours)} requests. Read them back: .venv/bin/python cache_check.py {args.log}")
    print()


if __name__ == "__main__":
    main()
