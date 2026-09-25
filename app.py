"""
The weekend readout. Replays the weekend's support traffic through Friday's
code and through yours, then prints cache hit rate and dollars per
conversation on one screen.

    .venv/bin/python app.py                          # your code: starter.py
    .venv/bin/python app.py --requests 6             # show each request of the first 6 conversations
    LAB_SOLUTION=reference .venv/bin/python app.py   # the finished version
"""
import argparse
import importlib
import os
from collections import Counter

import config
from clients import has_diagnostics, make_client
from support import WEEKEND, friday_request, replay, send_plain

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


def tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:,}"


def cached(u) -> tuple[int, int]:
    return u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0


def pending(reason) -> bool:
    """send_with_diagnostics() returns "pending" when the comparison hadn't finished."""
    return isinstance(reason, str) and reason == "pending"


def print_requests(turns, n_conversations: int, diagnosed: bool):
    ids = list(dict.fromkeys(t.conversation for t in turns))  # in order of first request
    shown = set(ids[:n_conversations])
    if not shown:
        return
    print("  Your code, request by request (tokens)")
    print("    conv  turn  time      read   written  uncached  output  cache_miss_reason")
    for t in turns:
        if t.conversation not in shown:
            continue
        read, written = cached(t.usage)
        if not diagnosed:
            why = "(diagnostics off)"
        elif pending(t.reason):
            why = "pending (check the next turn)"
        elif t.reason is not None:
            missed = getattr(t.reason, "cache_missed_input_tokens", None)
            why = t.reason.type + (f" (~{missed:,} tokens missed)" if missed else "")
        else:
            why = "none" if t.number > 1 else "none (first turn)"
        print(f"    {t.conversation}  {t.number:>4}  {t.at[11:19]}  {read:>6,}  {written:>8,}"
              f"  {t.usage.input_tokens:>8,}  {t.usage.output_tokens:>6,}  {why}")
    print()


def print_reasons(turns):
    print("  Why requests missed (cache diagnostics, your code)")
    print("    turn   cache_miss_reason            requests  read the cache")
    rows = Counter()
    reads = Counter()
    for t in turns:
        first = t.number == 1
        if pending(t.reason):
            kind = "pending (check next turn)"
        elif t.reason is not None:
            kind = t.reason.type
        else:
            kind = "none (nothing to compare)" if first else "none (no change)"
        key = ("first" if first else "later", kind)
        rows[key] += 1
        reads[key] += cached(t.usage)[0] > 0
    for key in sorted(rows):
        print(f"    {key[0]:<6} {key[1]:<28} {rows[key]:>8}  {reads[key]:>14}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests", type=int, default=3, metavar="N",
                        help="show each request of the first N conversations (default 3)")
    args = parser.parse_args()

    solution_name = os.environ.get("LAB_SOLUTION", "starter")
    lab = Lab(importlib.import_module(solution_name))
    live = config.PROVIDER != "offline"
    conversations = WEEKEND[: config.LIVE_CONVERSATIONS] if live else WEEKEND

    friday = replay(make_client(), conversations, friday_request, lab.send)
    yours = replay(make_client(), conversations, lab.build, lab.send)
    friday_meter, your_meter = lab.meter(friday), lab.meter(yours)

    mode = f"live on {config.PROVIDER} (real calls, billed)" if live else "offline (simulated tokens, no API calls)"
    print()
    print(f"CACHE DETECTIVE  |  Kestrel Outdoor support chat, weekend of 09/26/26  |  {solution_name}.py")
    print(f"{mode}  |  {config.MODEL}  |  {len(conversations)} conversations, {len(yours)} requests")
    print()
    diagnosed = has_diagnostics() and "send_with_diagnostics" not in lab.offline
    print_requests(yours, args.requests, diagnosed)

    n = len(conversations)
    print("                           Friday's code      Your code")
    if friday_meter and your_meter:
        (fh, fd), (yh, yd) = friday_meter, your_meter
        change = f"   ({(yd - fd) / fd:+.0%})" if fd else ""
        print(f"  Cache hit rate          {fh:>14.1%} {yh:>14.1%}")
        print(f"  $ per conversation      {f'${fd / n:.4f}':>14} {f'${yd / n:.4f}':>14}")
        print(f"  Weekend bill            {f'${fd:.2f}':>14} {f'${yd:.2f}':>14}{change}")
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
        print(f"  Case closed: $ per conversation is down {1 - your_meter[1] / friday_meter[1]:.0%} from Friday's code."
              " Run the tests to confirm.")
    print()


if __name__ == "__main__":
    main()
