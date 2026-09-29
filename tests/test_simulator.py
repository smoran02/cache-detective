"""
Checks the offline client against the documented caching rules, one rule per
test, each with its doc link, and the readings offline.py marks Unconfirmed.
Everything else in the lab rests on these. The last tests check
cache_check.py's first_divergence() against the client's diagnostics, and the
story: Friday's deploy tripled the bill. They pass whatever is in starter.py.

    .venv/bin/python -m pytest -q tests/test_simulator.py
"""
import pytest

import config
import offline
# thursday_request lives in app.py, not support.py: clue 3's hint sends learners to support.py.
from app import thursday_request
from cache_check import first_divergence, fingerprint
from offline import OfflineClient, SimulatedAPIError
from support import HANDBOOK, WEEKEND, friday_request, make_request, replay, send_plain
from checks import truth

BP = {"type": "ephemeral"}
BP_1H = {"type": "ephemeral", "ttl": "1h"}
TOOL = {"name": "lookup_order", "description": "Look up an order.",
        "input_schema": {"type": "object", "properties": {}}}


def block(tokens: int, tag: str = "s", cache_control: dict | None = None) -> dict:
    """A text block of exactly `tokens` simulated tokens (4 characters each)."""
    b = {"type": "text", "text": (tag * 4 * tokens)[: 4 * tokens]}
    if cache_control:
        b["cache_control"] = cache_control
    return b


def ask(client, at: float, system, content="hello", **extra):
    client.set_clock(at)
    return client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=system,
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


def test_each_breakpoint_has_its_own_lookback_window():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-automatic-prefix-checking-works
    client = OfflineClient()
    ask(client, 0, [block(1000, cache_control=BP)])  # writes the prefix that ends at the system block
    content = [block(10, str(i)) for i in range(25)]
    content[-1]["cache_control"] = BP
    # The last breakpoint's 20 positions stop short of the system block; the system breakpoint's own window finds it.
    assert ask(client, 1, [block(1000, cache_control=BP)], content).usage.cache_read_input_tokens == 1000


def test_a_tool_change_invalidates_the_system_and_messages_caches_too():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#what-invalidates-the-cache
    client = OfflineClient()
    system = [block(1000, cache_control=BP)]
    ask(client, 0, system, tools=[TOOL])
    assert ask(client, 1, system, tools=[TOOL]).usage.cache_read_input_tokens > 1000  # tools and system
    changed = {**TOOL, "description": "Find an order."}
    assert ask(client, 2, system, tools=[changed]).usage.cache_read_input_tokens == 0


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


def test_mixed_ttls_bill_reads_to_a_then_1h_writes_to_b_then_5m_writes_to_c():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#mixing-different-ttls
    client = OfflineClient()
    ask(client, 0, [block(600, "a", BP)])  # writes the prefix that ends at block a
    u = ask(client, 1, [block(600, "a", BP_1H), block(700, "b", BP_1H), block(800, "c", BP)]).usage
    # A = 600 (the highest hit), B = 1,300 (the highest 1h breakpoint), C = 2,100 (the last breakpoint).
    assert u.cache_read_input_tokens == 600
    assert (u.cache_creation.ephemeral_1h_input_tokens, u.cache_creation.ephemeral_5m_input_tokens) == (700, 800)


def test_at_most_4_breakpoints_and_automatic_caching_takes_one():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#combining-with-block-level-caching
    four = [block(10, str(i), BP) for i in range(4)]
    ask(OfflineClient(), 0, four)
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, four + [block(10, "4", BP)])
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, four, cache_control=BP)
    # Unconfirmed reading (offline.py, _breakpoints): with the 4th explicit breakpoint on the last
    # block, the docs call automatic caching a no-op there and also say 4 explicit is a 400. The sim 400s.
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, four[:3], [block(10, "m", BP)], cache_control=BP)


def test_an_entry_lives_5_minutes_from_its_last_use():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-prompt-caching-works
    client = OfflineClient()
    system = [block(1000, cache_control=BP)]
    ask(client, 0, system)
    assert ask(client, 299, system).usage.cache_read_input_tokens == 1000  # 4:59 after the write
    assert ask(client, 598, system).usage.cache_read_input_tokens == 1000  # 4:59 after that read
    assert ask(client, 899, system).usage.cache_read_input_tokens == 0  # 5:01 after the last use


def test_a_read_found_by_looking_back_refreshes_that_entry():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-prompt-caching-works
    client = OfflineClient()
    hello = {"role": "user", "content": "hello"}
    ask(client, 0, [block(1000)], cache_control=BP)  # automatic caching writes through "hello"
    client.set_clock(200)
    follow_up = client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)],
                                       messages=[hello, {"role": "assistant", "content": "hi"},
                                                 {"role": "user", "content": "and?"}], cache_control=BP)
    assert follow_up.usage.cache_read_input_tokens == 1002  # found looking back from "and?"
    # 450 seconds after the write, 250 after that read: the entry is alive only if the read refreshed it.
    client.set_clock(450)
    other = client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)],
                                   messages=[hello, {"role": "assistant", "content": "another reply"},
                                             {"role": "user", "content": "so?"}], cache_control=BP)
    assert other.usage.cache_read_input_tokens == 1002


@pytest.mark.parametrize("refresh, reads", [(True, 1000), (False, 0)], ids=["the sim's reading", "the other reading"])
def test_a_breakpoint_inside_the_read_refreshes_its_entry(monkeypatch, refresh, reads):
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#mixing-different-ttls
    # Unconfirmed reading (offline.py, REFRESH_BREAKPOINTS_INSIDE_THE_READ); the lab's numbers rest on it.
    assert offline.REFRESH_BREAKPOINTS_INSIDE_THE_READ is True, "the README's numbers assume this reading"
    monkeypatch.setattr(offline, "REFRESH_BREAKPOINTS_INSIDE_THE_READ", refresh)
    client = OfflineClient()
    system = [block(1000, cache_control=BP)]
    ask(client, 0, system, cache_control=BP)  # writes at the system block and at "hello"
    later = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"},
             {"role": "user", "content": "and?"}]
    client.set_clock(200)
    follow_up = client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=system,
                                       messages=later, cache_control=BP)
    assert follow_up.usage.cache_read_input_tokens == 1002  # reads through "hello", past the system breakpoint
    # 450 seconds after the write, only the system entry could match. It's alive only if the follow-up refreshed it.
    assert ask(client, 450, system, "something else", cache_control=BP).usage.cache_read_input_tokens == reads


def test_diagnostics_compares_only_with_requests_that_sent_it():
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#basic-usage
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types
    client = OfflineClient()
    request = dict(model=config.MODEL, max_tokens=config.MAX_TOKENS, cache_control=BP, system=block(1000)["text"],
                   messages=[{"role": "user", "content": "hello"}])
    first = client.beta.messages.create(**request, diagnostics={"previous_message_id": None})
    assert first.diagnostics is None  # a first turn: nothing to compare
    same = client.beta.messages.create(**request, diagnostics={"previous_message_id": first.id})
    assert same.diagnostics is None  # compared, and nothing changed
    changed = client.beta.messages.create(**{**request, "system": block(1000, "t")["text"]},
                                          diagnostics={"previous_message_id": same.id})
    assert changed.diagnostics.cache_miss_reason.type == "system_changed"
    # Unconfirmed reading (offline.py, _diagnose): missed tokens are counted per block from the change on.
    assert changed.diagnostics.cache_miss_reason.cache_missed_input_tokens == 1000 + 2  # the system prompt and "hello"
    # With tools ahead of the system prompt, the tools aren't missed.
    with_tools = client.beta.messages.create(**request, tools=[TOOL], diagnostics={"previous_message_id": None})
    changed = client.beta.messages.create(**{**request, "system": block(1000, "t")["text"]}, tools=[TOOL],
                                          diagnostics={"previous_message_id": with_tools.id})
    assert changed.diagnostics.cache_miss_reason.cache_missed_input_tokens == 1000 + 2
    unmarked = client.beta.messages.create(**request)  # no diagnostics object: no fingerprint kept
    after = client.beta.messages.create(**request, diagnostics={"previous_message_id": unmarked.id})
    assert after.diagnostics.cache_miss_reason.type == "previous_message_not_found"


def test_a_1h_entry_lives_an_hour():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#1-hour-cache-duration
    client = OfflineClient()
    system = [block(1000, cache_control=BP_1H)]
    assert ask(client, 0, system).usage.cache_creation.ephemeral_1h_input_tokens == 1000
    assert ask(client, 3599, system).usage.cache_read_input_tokens == 1000
    assert ask(client, 3599 + 3601, system).usage.cache_read_input_tokens == 0


def test_automatic_and_explicit_breakpoints_on_one_block_must_agree_on_ttl():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#edge-cases
    same = ask(OfflineClient(), 0, [block(1000)], [block(10, "m", BP)], cache_control=BP)
    assert same.usage.cache_creation_input_tokens == 1010  # automatic caching is a no-op
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, [block(1000)], [block(10, "m", BP)], cache_control=BP_1H)


@pytest.mark.parametrize("last", [
    {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig"}]},
    {"role": "user", "content": [{"type": "text", "text": ""}]},
], ids=["a thinking block", "an empty text block"])
def test_the_automatic_breakpoint_walks_back_past_a_block_that_cant_be_cached(last):
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#edge-cases
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#what-cannot-be-cached
    # Unconfirmed reading (offline.py, _breakpoints): thinking blocks and empty text blocks can't be cached,
    # so the sim skips them.
    client = OfflineClient()
    client.set_clock(0)
    response = client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)],
                                      cache_control=BP, messages=[{"role": "user", "content": "hello"}, last])
    assert response.usage.cache_creation_input_tokens == 1000 + 2
    # The entry ends at "hello", not at the block after it, so a request that ends at "hello" reads it.
    assert ask(client, 1, [block(1000)], cache_control=BP).usage.cache_read_input_tokens == 1000 + 2


def test_the_cache_is_per_model():
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types
    client = OfflineClient()
    system = [block(1000, cache_control=BP)]
    ask(client, 0, system)
    client.set_clock(1)
    other = client.messages.create(model="another-model", max_tokens=config.MAX_TOKENS, system=system,
                                   messages=[{"role": "user", "content": "hello"}])
    assert other.usage.cache_read_input_tokens == 0


@pytest.mark.parametrize("before, after", [
    ({"tool_choice": {"type": "auto"}}, {"tool_choice": {"type": "none"}}),
    ({"output_config": {"effort": "high"}}, {"output_config": {"effort": "max"}}),
    ({}, {"thinking": {"type": "adaptive"}}),
], ids=["tool_choice", "effort", "thinking"])
def test_request_parameters_invalidate_the_messages_cache_only(before, after):
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#what-invalidates-the-cache
    # Simplification (offline.py docstring): thinking and effort are treated like tool_choice, compared as sent.
    client = OfflineClient()
    system = [block(1000, cache_control=BP)]
    for at, params in ((0, before), (1, before), (2, after)):
        response = ask(client, at, system, [block(600, "m")], tools=[TOOL], cache_control=BP, **params)
        if at == 1:
            assert response.usage.cache_read_input_tokens > 1600  # tools, system, and the message
    assert 1000 < response.usage.cache_read_input_tokens < 1600  # tools and system only


def test_a_run_of_tool_use_blocks_is_one_lookback_position():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-automatic-prefix-checking-works
    client = OfflineClient()
    ask(client, 0, [block(1000, cache_control=BP)])  # writes the prefix that ends at the system block
    calls = [{"type": "tool_use", "id": f"toolu_{i}", "name": "lookup_order", "input": {}} for i in range(25)]
    results = [{"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": "ok"} for i in range(25)]
    results[-1]["cache_control"] = BP
    client.set_clock(1)
    # 52 blocks after the system prompt, but 3 lookback positions: the question, the calls, the results.
    response = client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)], messages=[
        {"role": "user", "content": "Where are my orders?"},
        {"role": "assistant", "content": calls},
        {"role": "user", "content": results},
    ])
    assert response.usage.cache_read_input_tokens == 1000


def test_a_thinking_block_replayed_after_the_system_prompt_changed_is_a_400():
    # https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5#thinking-blocks-are-tied-to-the-model-that-produced-them
    client = OfflineClient()
    question = {"role": "user", "content": "hello"}
    first = ask(client, 0, [block(1000)], question["content"])
    assert first.content[0].type == "thinking"
    history = [question, {"role": "assistant", "content": first.content}, {"role": "user", "content": "and?"}]
    client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)], messages=history)
    with pytest.raises(SimulatedAPIError):
        client.messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000, "t")],
                               messages=history)


def diagnose(client, previous_id, **request):
    base = dict(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=block(1000)["text"],
                messages=[{"role": "user", "content": "hello"}])
    return client.beta.messages.create(**{**base, **request}, diagnostics={"previous_message_id": previous_id})


def test_diagnostics_reports_the_earliest_divergence_in_prefix_order():
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types
    # Unconfirmed reading (offline.py, _diagnose): the docs give no order for model, tools, and system. The sim
    # checks the model, then follows the prefix: tools, system, messages.
    client = OfflineClient()
    first = diagnose(client, None, tools=[TOOL])
    changed_tool = {**TOOL, "description": "Find an order."}
    both = diagnose(client, first.id, tools=[changed_tool], system=block(1000, "t")["text"])
    reason = both.diagnostics.cache_miss_reason
    assert reason.type == "tools_changed"
    assert reason.cache_missed_input_tokens == both.usage.input_tokens + both.usage.cache_creation_input_tokens
    everything = diagnose(client, both.id, model="another-model", tools=[TOOL])
    assert everything.diagnostics.cache_miss_reason.type == "model_changed"


def test_diagnostics_names_a_changed_or_dropped_message():
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types
    client = OfflineClient()
    turns = [{"role": "user", "content": [block(10, "q")]}, {"role": "assistant", "content": [block(20, "a")]},
             {"role": "user", "content": [block(30, "b")]}]
    first = diagnose(client, None, messages=turns)
    edited = diagnose(client, first.id, messages=[turns[0], {"role": "assistant", "content": [block(20, "e")]}, turns[2]])
    reason = edited.diagnostics.cache_miss_reason
    # Unconfirmed reading (offline.py, _diagnose): missed tokens are counted per block from the change on.
    assert (reason.type, reason.cache_missed_input_tokens) == ("messages_changed", 20 + 30)
    dropped = diagnose(client, edited.id, messages=turns[:1])
    assert dropped.diagnostics.cache_miss_reason.type == "messages_changed"


def test_diagnostics_is_unavailable_when_request_parameters_changed():
    # https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types
    # "a model/system/tools match where tool_choice ... or the set of anthropic-beta headers differs"
    client = OfflineClient()
    first = diagnose(client, None, tools=[TOOL], tool_choice={"type": "auto"})
    changed = diagnose(client, first.id, tools=[TOOL], tool_choice={"type": "none"})
    assert changed.diagnostics.cache_miss_reason.type == "unavailable"
    beta = diagnose(client, changed.id, tools=[TOOL], tool_choice={"type": "none"}, betas=["cache-diagnosis-2026-04-07"])
    assert beta.diagnostics.cache_miss_reason.type == "unavailable"
    # Unconfirmed reading (offline.py, _diagnose): with a parameter and a message both changed, the row
    # above still applies (model, system, and tools match), so the sim checks parameters before messages.
    both = diagnose(client, beta.id, tools=[TOOL], tool_choice={"type": "auto"},
                    messages=[{"role": "user", "content": "goodbye"}])
    assert both.diagnostics.cache_miss_reason.type == "unavailable"


@pytest.mark.parametrize("messages", [
    [],  # no messages
    [{"role": "user", "content": [{"type": "text", "text": ["not", "a", "string"]}]}],
    [{"role": "system", "content": "Current time: 09:00"}, {"role": "user", "content": "hello"}],
    [{"role": "user", "content": "hello"}, {"role": "system", "content": "Current time: 09:00"},
     {"role": "user", "content": "and?"}],
    [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"},
     {"role": "system", "content": "Current time: 09:00"}],
    [{"role": "user", "content": {"type": "text", "text": "hello"}}],
], ids=["no messages", "text that isn't a string", "system message before the user message",
        "system message followed by a user message", "system message after an assistant message",
        "content that's one block, not a list"])
def test_requests_the_api_rejects_are_400s(messages):
    # https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages
    with pytest.raises(SimulatedAPIError):
        OfflineClient().messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)],
                                        messages=messages)


@pytest.mark.parametrize("system", [{"type": "text", "text": "hello"}, 42], ids=["one block, not a list", "a number"])
def test_a_system_prompt_that_isnt_a_string_or_a_list_is_a_400(system):
    with pytest.raises(SimulatedAPIError):
        ask(OfflineClient(), 0, system)


def test_system_messages_can_follow_the_user_message():
    # https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages
    # "Consecutive system messages are accepted and treated as a single system section."
    time = {"role": "system", "content": "Current time: 09:00"}
    for after in ([time], [time, {"role": "system", "content": "The phone line is closed."}]):
        response = OfflineClient().messages.create(model=config.MODEL, max_tokens=config.MAX_TOKENS, system=[block(1000)],
                                                   messages=[{"role": "user", "content": "hello"}, *after])
        assert response.stop_reason == "end_turn"


def test_output_stops_at_max_tokens():
    # https://platform.claude.com/docs/en/build-with-claude/thinking (thinking counts toward max_tokens)
    client = OfflineClient()
    client.set_clock(0)
    response = client.messages.create(model=config.MODEL, max_tokens=50, system=[block(1000)],
                                      messages=[{"role": "user", "content": "hello"}])
    assert (response.usage.output_tokens, response.stop_reason) == (50, "max_tokens")


def test_first_divergence_agrees_with_diagnostics():
    # first_divergence(), which cache_check.py uses on Bedrock (README, "Take it to your app"), names the part
    # diagnostics names: the system prompt on Friday's code, nothing once the time moves.
    history = [{"role": "user", "content": "Do you rent bear canisters?"}, {"role": "assistant", "content": "Yes."}]
    turn_1 = friday_request([], history[0]["content"], "2026-09-26T09:00:00-07:00")
    turn_2 = friday_request(history, "How much for five days?", "2026-09-26T09:02:00-07:00")
    assert first_divergence(turn_1, turn_2) == "system"
    fixed_1 = thursday_request([], history[0]["content"], "")
    fixed_2 = thursday_request(history, "How much for five days?", "")
    assert first_divergence(fixed_1, fixed_2) is None
    assert first_divergence(fingerprint(fixed_2), fingerprint(fixed_1)) == "messages[1]"  # history shrank
    # A moved breakpoint isn't a change; a reordered tool list is.
    marked = make_request(HANDBOOK, [{"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": BP}]}])
    unmarked = make_request(HANDBOOK, [{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
    assert first_divergence(marked, unmarked) is None
    other = {**TOOL, "name": "track_order"}
    assert first_divergence({**fixed_1, "tools": [TOOL, other]}, {**fixed_1, "tools": [other, TOOL]}) == "tools"
    # And diagnostics agrees on Friday's pair.
    client = OfflineClient()
    first = client.beta.messages.create(**turn_1, diagnostics={"previous_message_id": None})
    second = client.beta.messages.create(**turn_2, diagnostics={"previous_message_id": first.id})
    assert second.diagnostics.cache_miss_reason.type == "system_changed"


def test_first_divergence_sees_request_parameters_the_way_diagnostics_does():
    # https://platform.claude.com/docs/en/build-with-claude/prompt-caching#what-invalidates-the-cache
    # An effort or tool_choice change invalidates the messages cache; diagnostics calls it unavailable.
    request = make_request(HANDBOOK, [{"role": "user", "content": "hi"}])
    for before, after in (({"output_config": {"effort": "high"}}, {"output_config": {"effort": "max"}}),
                          ({"tools": [TOOL], "tool_choice": {"type": "auto"}},
                           {"tools": [TOOL], "tool_choice": {"type": "none"}})):
        assert first_divergence({**request, **before}, {**request, **after}) == "params"
        client = OfflineClient()
        first = client.beta.messages.create(**request, **before, diagnostics={"previous_message_id": None})
        second = client.beta.messages.create(**request, **after, diagnostics={"previous_message_id": first.id})
        assert second.diagnostics.cache_miss_reason.type == "unavailable"
    # A string system prompt and the same text as one block are one request, and so are no tools and [].
    assert first_divergence(request, {**request, "system": [{"type": "text", "text": HANDBOOK}], "tools": []}) is None


def test_fridays_deploy_tripled_the_bill():
    # The README's first line, on this simulator: the same weekend on Thursday's code and on Friday's.
    _, thursday = truth(t.usage for t in replay(OfflineClient(), WEEKEND, thursday_request, send_plain))
    _, friday = truth(t.usage for t in replay(OfflineClient(), WEEKEND, friday_request, send_plain))
    assert friday / thursday >= 3.0
