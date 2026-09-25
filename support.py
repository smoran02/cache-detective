"""
The support agent, as it shipped on Friday. You don't edit this file;
starter.py is where you work.

Kestrel Outdoor Co. runs Wren, a support chat agent, on Opus 5.5. Each
customer message is one Messages API request: the handbook as the system
prompt, the conversation so far, and the new message.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import config

DATA = Path(__file__).parent / "data"
HANDBOOK = (DATA / "handbook.md").read_text()
WEEKEND = json.loads((DATA / "weekend.json").read_text())["conversations"]


def make_request(system, messages: list) -> dict:
    """Everything a request needs besides the system prompt and the messages."""
    return {
        "model": config.MODEL,
        "max_tokens": config.MAX_TOKENS,
        # Top-level cache_control turns on automatic caching: the API puts the
        # breakpoint on the last cacheable block of the request.
        "cache_control": {"type": "ephemeral"},
        "system": system,
        "messages": messages,
    }


def friday_request(history: list, question: str, now: str) -> dict:
    """One turn's request as Friday's deploy left it. The deploy is data/friday.diff."""
    system = f"Current time: {now}\n\n{HANDBOOK}"
    return make_request(system, history + [{"role": "user", "content": question}])


def send_plain(client, request: dict, previous_id=None):
    """Send without cache diagnostics. Returns (response, None)."""
    return client.messages.create(**request), None


def reply_text(response) -> str:
    """The reply's text. Opus 5.5 responses can start with thinking blocks, so pick blocks by type."""
    text = "".join(b.text for b in response.content if b.type == "text")
    return text or "(no reply)"


@dataclass
class Turn:
    conversation: str
    number: int  # 1 for the customer's first message
    at: str
    usage: object  # response.usage
    reason: object  # what send() returned: a cache_miss_reason, "pending", or None


def replay(client, conversations: list, build, send) -> list[Turn]:
    """Replay conversations in time order, one request per customer message.

    build(history, question, now) returns the request dict for one turn.
    send(client, request, previous_id) returns (response, reason).
    """
    events = sorted(
        (datetime.fromisoformat(t["at"]), c, n)
        for c, convo in enumerate(conversations)
        for n, t in enumerate(convo["turns"])
    )
    history = [[] for _ in conversations]
    previous_id = [None] * len(conversations)
    turns = []
    for when, c, n in events:
        convo, message = conversations[c], conversations[c]["turns"][n]
        if hasattr(client, "set_clock"):
            client.set_clock(when)  # offline: run on the traffic's clock, not the wall clock
            now = message["at"]
        else:
            # Live: the wall clock, as Friday's deploy used. Replaying the traffic's
            # times would repeat Friday's prompts from run to run, so a second run
            # would read what the first one wrote. (The fix's handbook entry is the
            # same bytes on every run, so a run within 5 minutes of another reads it.)
            now = datetime.now().astimezone().isoformat(timespec="seconds")
        request = build(history[c], message["text"], now)
        response, reason = send(client, request, previous_id[c])
        # History keeps the reply text only, so it's byte-stable from turn to turn
        # and no Opus 5.5 thinking block is sent back. The Thinking page allows it
        # ("outside tool use, omit prior turns' thinking"), and replaying one after
        # the system prompt changed is a 400 on accounts created since 08/31/26:
        # Friday's system prompt changes on every request.
        # https://platform.claude.com/docs/en/build-with-claude/thinking#preserving-thinking-blocks
        # (Unconfirmed: whether live diagnostics would flag a reply sent back
        # without its thinking block.)
        history[c] = request["messages"] + [{"role": "assistant", "content": reply_text(response)}]
        previous_id[c] = response.id
        turns.append(Turn(convo["id"], n + 1, message["at"], response.usage, reason))
    return turns
