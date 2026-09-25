"""
Live end-to-end test: the before-and-after check against the real API.
Skipped unless LAB_LIVE=1. It makes real, billed requests: Friday's code and
the fix each replay the first config.LIVE_CONVERSATIONS conversations.

    LAB_LIVE=1 LAB_PROVIDER=anthropic LAB_SOLUTION=reference .venv/bin/python -m pytest -q -s tests/test_live.py
    LAB_LIVE=1 LAB_PROVIDER=bedrock   LAB_SOLUTION=reference .venv/bin/python -m pytest -q -s tests/test_live.py
"""
import importlib
import os

import pytest

import config
from clients import has_diagnostics, make_client
from support import WEEKEND, friday_request, replay, send_plain
from truth import truth

pytestmark = pytest.mark.skipif(
    os.environ.get("LAB_LIVE") != "1", reason="live test: set LAB_LIVE=1 (makes billed API calls)"
)


def test_live_weekend_before_and_after_the_fix():
    if config.PROVIDER == "offline":
        pytest.skip("set LAB_PROVIDER=anthropic or LAB_PROVIDER=bedrock (or PROVIDER in config.py)")
    solution = importlib.import_module(os.environ.get("LAB_SOLUTION", "starter"))
    client = make_client()
    conversations = WEEKEND[: config.LIVE_CONVERSATIONS]
    send = solution.send_with_diagnostics if has_diagnostics() else send_plain

    def fixed_request(history, question, now):
        return solution.place_breakpoint(solution.build_request(history, question, now))

    friday = replay(client, conversations, friday_request, send)
    fixed = replay(client, conversations, fixed_request, send)

    # The test's own meter, as offline, so a bug in meter() can't hide a bad fix.
    friday_hit, friday_dollars = truth(t.usage for t in friday)
    fixed_hit, fixed_dollars = truth(t.usage for t in fixed)
    # Caching changes what input costs, not output, so compare input spend too.
    no_output = lambda turns: [t.usage.model_copy(update={"output_tokens": 0}) for t in turns]
    friday_input = truth(no_output(friday))[1]
    fixed_input = truth(no_output(fixed))[1]
    n = len(conversations)
    print(f"\n{config.PROVIDER} {config.MODEL}: {n} conversations, {len(fixed)} requests per run")
    print(f"Friday: hit rate {friday_hit:.1%}, ${friday_dollars / n:.4f} per conversation")
    print(f"Fixed:  hit rate {fixed_hit:.1%}, ${fixed_dollars / n:.4f} per conversation")

    assert friday_hit < 0.05, "Friday's code shouldn't read the cache"
    assert fixed_hit >= 0.70, (
        "the fix should read most input from the cache. On Bedrock, a 0% hit rate can also mean "
        "the response's usage fields have different names: print response.usage to check."
    )
    assert fixed_dollars < friday_dollars
    assert fixed_input <= 0.4 * friday_input, "input spend should fall by more than half"
    if has_diagnostics():
        # Diagnostics can come back pending ({"cache_miss_reason": null}) on a fast
        # response, so ask for the culprit on at least one follow-up turn, not all.
        assert any(getattr(t.reason, "type", None) == "system_changed" for t in friday if t.number > 1)
