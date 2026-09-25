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
    return isinstance(reason, str) and reason == "pending"


def print_requests(turns, n_conversations: int, diagnosed: bool):
    ids = list(dict.fromkeys(t.conversation for t in turns))  # in order of first request
    shown = set(ids[:n_conversations])
    if not shown:
        return
    print("  Your code, request by request (tokens)")
    print(f"    {'conv':<4}  {'turn':>4}  {'time':<8}  {'read':>6}  {'written':>8}  {'uncached':>8}"
          f"  {'output':>6}  cache_miss_reason")
    for t in turns:
        if t.conversation not in shown:
            continue
        read, written = cached(t.usage)
        if not diagnosed:
            why = "(diagnostics off)"
        elif pending(t.reason):
            why = PENDING
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
    print(f"    {'turn':<6} {'cache_miss_reason':<30} {'requests':>8}  {'read the cache':>14}")
    rows = Counter()
    reads = Counter()
    for t in turns:
        first = t.number == 1
        if pending(t.reason):
            kind = PENDING
        elif t.reason is not None:
            kind = t.reason.type
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
    changed = Counter(t.reason.type for t in later if diagnosed and t.reason is not None and not pending(t.reason))
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
    lab = Lab(importlib.import_module(solution_name))
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
    print_requests(yours, args.requests, diagnosed)

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
        short = shortfalls(friday_meter, your_meter, yours, n, live, diagnosed)
        if short:
            print("  Not yet. All four clues are online, but your numbers miss the tests' bar in config.py:")
            for line in short:
                print(f"    {line}")
        else:
            print(f"  Case closed: $ per conversation is down {1 - your_meter[1] / friday_meter[1]:.0%} from Friday's code."
                  " Run the tests to confirm.")
    print()


if __name__ == "__main__":
    main()
