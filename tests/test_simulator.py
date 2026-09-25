"""
Checks the offline client against the documented caching rules, one rule per
test, each with its doc link. Everything else in the lab rests on these.
They pass whatever is in starter.py.

    .venv/bin/python -m pytest -q tests/test_simulator.py
"""
import pytest

import config
from offline import OfflineClient, SimulatedAPIError
from support import HANDBOOK, WEEKEND, friday_request, make_request, replay, send_plain
from truth import truth

BP = {"type": "ephemeral"}
BP_1H = {"type": "ephemeral", "ttl": "1h"}


def block(tokens: int, tag: str = "s", cache_control: dict | None = None) -> dict:
    """A text block of exactly `tokens` simulated tokens (4 characters each)."""
    b = {"type": "text", "text": (tag * 4 * tokens)[: 4 * tokens]}
    if cache_control:
        b["cache_control"] = cache_control
    return b


def ask(client, at: float, system, content="hello", **extra):
    client.set_clock(at)
    return client.messages.create(model=config.MODEL, max_tokens=100, system=system,
                                  messages=[{"role": "user", "content": content}], **extra)


def test_writes_happen_only_at_a_breakpoint():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-automatic-prefix-checking-works
    client = OfflineClient()
    for at in (0, 1):
        plain = ask(client, at, [block(1000)])
        assert (plain.usage.cache_creation_input_tokens, plain.usage.cache_read_input_tokens) == (0, 0)
    marked = ask(client, 2, [block(1000, cache_control=BP)])
    assert marked.usage.cache_creation_input_tokens == 1000
    assert ask(client, 3, [block(1000, cache_control=BP)]).usage.cache_read_input_tokens == 1000


@pytest.mark.parametrize("blocks_after, reads", [(19, True), (20, False)])
def test_the_lookback_reaches_20_blocks_counting_the_breakpoint(blocks_after, reads):
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-automatic-prefix-checking-works
    client = OfflineClient()
    ask(client, 0, [block(1000, cache_control=BP)])  # writes the prefix that ends at the system block
    content = [block(10, str(i)) for i in range(blocks_after)]
    content[-1]["cache_control"] = BP
    response = ask(client, 1, [block(1000)], content)
    assert (response.usage.cache_read_input_tokens == 1000) is reads


def test_a_prefix_under_512_tokens_runs_uncached_with_no_error():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#cache-limitations
    assert config.MIN_CACHEABLE_TOKENS == 512
    assert ask(OfflineClient(), 0, [block(511, cache_control=BP)]).usage.cache_creation_input_tokens == 0
    assert ask(OfflineClient(), 0, [block(512, cache_control=BP)]).usage.cache_creation_input_tokens == 512


def test_1h_entries_must_come_before_5m_entries():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#mixing-different-ttls
    ok = ask(OfflineClient(), 0, [block(600, "a", BP_1H), block(600, "b", BP)])
    assert ok.usage.cache_creation.ephemeral_1h_input_tokens == 600
    assert ok.usage.cache_creation.ephemeral_5m_input_tokens == 600
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, [block(600, "a", BP), block(600, "b", BP_1H)])


def test_at_most_4_breakpoints_and_automatic_caching_takes_one():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#combining-with-block-level-caching
    four = [block(10, str(i), BP) for i in range(4)]
    ask(OfflineClient(), 0, four)
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, four + [block(10, "4", BP)])
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, four, cache_control=BP)


def test_an_entry_lives_5_minutes_from_its_last_use():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-prompt-caching-works
    client = OfflineClient()
    system = [block(1000, cache_control=BP)]
    ask(client, 0, system)
    assert ask(client, 299, system).usage.cache_read_input_tokens == 1000  # 4:59 after the write
    assert ask(client, 598, system).usage.cache_read_input_tokens == 1000  # 4:59 after that read
    assert ask(client, 899, system).usage.cache_read_input_tokens == 0  # 5:01 after the last use


def test_diagnostics_compares_only_with_requests_that_sent_it():
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#basic-usage
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types
    client = OfflineClient()
    request = dict(model=config.MODEL, max_tokens=100, cache_control=BP, system=block(1000)["text"],
                   messages=[{"role": "user", "content": "hello"}])
    first = client.beta.messages.create(**request, diagnostics={"previous_message_id": None})
    assert first.diagnostics is None  # a first turn: nothing to compare
    same = client.beta.messages.create(**request, diagnostics={"previous_message_id": first.id})
    assert same.diagnostics is None  # compared, and nothing changed
    changed = client.beta.messages.create(**{**request, "system": block(1000, "t")["text"]},
                                          diagnostics={"previous_message_id": same.id})
    assert changed.diagnostics.cache_miss_reason.type == "system_changed"
    unmarked = client.beta.messages.create(**request)  # no diagnostics object: no fingerprint kept
    after = client.beta.messages.create(**request, diagnostics={"previous_message_id": unmarked.id})
    assert after.diagnostics.cache_miss_reason.type == "previous_message_not_found"


def thursday_request(history: list, question: str, now: str) -> dict:
    """Wren's request before Friday's deploy (data/friday.diff): no time, and a breakpoint on the handbook."""
    system = [{"type": "text", "text": HANDBOOK, "cache_control": BP}]
    return make_request(system, history + [{"role": "user", "content": question}])


def test_fridays_deploy_tripled_the_bill():
    # The README's first line, on this simulator: the same weekend on Thursday's code and on Friday's.
    _, thursday = truth(t.usage for t in replay(OfflineClient(), WEEKEND, thursday_request, send_plain))
    _, friday = truth(t.usage for t in replay(OfflineClient(), WEEKEND, friday_request, send_plain))
    assert friday / thursday >= 3.0
