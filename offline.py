"""
Offline mode: a simulated Claude API client that applies the documented
prompt caching rules, so the lab runs with no API key, no network, and no bill.

It returns the SDK's own response types: anthropic.types.Message from
client.messages.create and anthropic.types.beta.BetaMessage (with the
diagnostics field) from client.beta.messages.create.

Caching rules it applies, from
https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- The prefix runs tools, then system, then messages. A hit needs every block
  up to the breakpoint to match exactly, so changing one block changes every
  prefix that contains it. The cache is per model.
- Writes happen only at breakpoints: cache_control on a block, plus the
  automatic one (top-level cache_control) on the last cacheable block.
  At most 4 breakpoints per request.
- Reads look back from each breakpoint, up to 20 positions, for an entry an
  earlier request wrote. A run of tool_use (or tool_result) blocks counts as
  one position.
- Entries live 5 minutes, or 1 hour with ttl "1h", from the start of the
  request that wrote or last read them. 1h breakpoints must come before 5m.
- A prefix shorter than config.MIN_CACHEABLE_TOKENS is never cached, and the
  request still succeeds.
- Changing tool_choice, thinking, or output_config invalidates the messages
  cache but not the tools or system cache.

What it doesn't do: count tokens like the real tokenizer (it uses about 4
characters per token, so every count here is simulated), call tools, write
real replies, or model concurrent requests. Replies are canned text.
"""
import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from datetime import datetime

from anthropic.types import Message
from anthropic.types.beta import BetaMessage

import config

TTL_SECONDS = {"5m": 5 * 60, "1h": 60 * 60}
LOOKBACK_POSITIONS = 20
MAX_BREAKPOINTS = 4

REPLIES = [
    "Thanks for reaching out. I've pulled up the details, and here is where things stand: "
    "your request is within our policy, so there's nothing extra you need to do right now. "
    "You'll get an email confirmation shortly with the next steps and any tracking or case "
    "number. If anything looks off when it arrives, reply to that email or message me here.",
    "Good question. Our policy covers this: you have a few options, and the simplest is to "
    "start it from your order page, which takes about two minutes. If you'd rather I set it "
    "up for you, share the order number and I'll take care of it from here.",
    "I can help with that. Based on what you've described, this is covered, and I've noted "
    "it on your account. The timing depends on the carrier and our warehouse, but most "
    "customers see it resolved within a few business days. I'll keep the case open until then.",
    "Here's what I'd suggest. First, check the details on your order page so we're looking at "
    "the same thing. Second, if it still doesn't match, I can open a case with our team, and "
    "they'll follow up by email within one business day.",
    "Happy to help. That works, and there's no charge for it in your situation. Let me know "
    "if you want me to go ahead, and I'll send a confirmation to the email on your account.",
    "Thanks for your patience. I've checked this against our policy and your order. The short "
    "answer is yes, with one condition: we'll need the item back in its original condition. "
    "I'll email you a prepaid label, and the rest happens automatically once it's scanned.",
]


class SimulatedAPIError(Exception):
    """Stands in for the 400 invalid_request_error the real API returns."""

    status_code = 400


def count_tokens(text: str) -> int:
    """Simulated token count: about 4 characters per token. The real tokenizer differs."""
    return math.ceil(len(text) / 4)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _canon(obj) -> str:
    # Keys stay in the order they were sent: a reordered key changes the hash,
    # the way it changes the bytes the real API sees.
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


def _plain(block) -> dict:
    """A block as a plain dict, whether it arrived as a dict or an SDK object."""
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


@dataclass
class _Block:
    section: str  # "tools", "system", or "messages"
    type: str  # "tool", "text", "thinking", "tool_use", "tool_result", ...
    key: str  # what the prefix hash covers: the block without its cache_control
    tokens: int
    cache_control: dict | None
    message: int | None  # index into messages, for message blocks


def _flatten(tools, system, messages) -> list[_Block]:
    blocks = []
    for tool in tools or []:
        tool = _plain(tool)
        cc = tool.pop("cache_control", None)
        key = _canon(tool)
        blocks.append(_Block("tools", "tool", key, count_tokens(key), cc, None))
    if isinstance(system, str):
        system = [{"type": "text", "text": system}] if system else []
    for b in system or []:
        b = _plain(b)
        cc = b.pop("cache_control", None)
        blocks.append(_Block("system", b.get("type", "text"), _canon(b), _tokens(b), cc, None))
    for i, message in enumerate(messages):
        content = message["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for j, b in enumerate(content):
            b = _plain(b)
            cc = b.pop("cache_control", None)
            key = _canon([i, message["role"], j, b])
            blocks.append(_Block("messages", b.get("type", "text"), key, _tokens(b), cc, i))
    return blocks


def _tokens(block: dict) -> int:
    if block.get("type") == "text":
        return count_tokens(block.get("text", ""))
    return count_tokens(_canon(block))


def _prefix_hashes(model: str, blocks: list[_Block], messages_context: str) -> list[str]:
    """Cumulative hash at each block: everything from the start of tools up to it."""
    h = _sha(_canon(["model", model]))
    out = []
    for b in blocks:
        context = messages_context if b.section == "messages" else ""
        h = _sha(h + b.section + context + b.key)
        out.append(h)
    return out


def _positions(blocks: list[_Block]) -> list[int]:
    """Lookback positions. Runs of tool_use or tool_result blocks share one position."""
    out, pos, prev = [], -1, None
    for b in blocks:
        if not (b.type in ("tool_use", "tool_result") and b.type == prev):
            pos += 1
        out.append(pos)
        prev = b.type
    return out


def _ttl(cache_control: dict) -> str:
    if cache_control.get("type") != "ephemeral":
        raise SimulatedAPIError('(offline) cache_control type must be "ephemeral"')
    ttl = cache_control.get("ttl", "5m")
    if ttl not in TTL_SECONDS:
        raise SimulatedAPIError('(offline) cache_control ttl must be "5m" or "1h"')
    return ttl


def _breakpoints(blocks: list[_Block], automatic: dict | None) -> list[tuple[int, str]]:
    bps = {i: _ttl(b.cache_control) for i, b in enumerate(blocks) if b.cache_control}
    if len(bps) > MAX_BREAKPOINTS:
        raise SimulatedAPIError("(offline) at most 4 cache_control breakpoints per request")
    if automatic:
        if len(bps) == MAX_BREAKPOINTS:
            raise SimulatedAPIError("(offline) 4 explicit breakpoints leave no slot for automatic caching")
        # The automatic breakpoint goes on the last cacheable block. Thinking
        # blocks and empty text blocks can't be cached, so walk back past them.
        # (Unconfirmed: the docs don't list which blocks are ineligible for the
        # automatic breakpoint. The lab's requests always end on a user message.)
        last = next((i for i in range(len(blocks) - 1, -1, -1)
                     if blocks[i].type not in ("thinking", "redacted_thinking")
                     and blocks[i].tokens > 0), None)
        if last is not None:
            if last not in bps:
                bps[last] = _ttl(automatic)
            elif bps[last] != _ttl(automatic):
                raise SimulatedAPIError("(offline) automatic and explicit cache_control disagree on ttl")
    ordered = sorted(bps.items())
    seen_5m = False
    for _, ttl in ordered:
        if ttl == "5m":
            seen_5m = True
        elif seen_5m:
            raise SimulatedAPIError("(offline) 1h cache entries must come before 5m entries")
    return ordered


def _to_seconds(when) -> float:
    if isinstance(when, (int, float)):
        return float(when)
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    return when.timestamp()


class _Engine:
    """One simulated workspace: its cache, diagnostics fingerprints, and clock."""

    def __init__(self):
        self.cache: dict[str, dict] = {}  # prefix hash -> {"ttl", "expires"}
        self.fingerprints: dict[str, dict] = {}  # response id -> fingerprint
        self.thinking: dict[str, str] = {}  # thinking signature -> prefix hash it was produced after
        self.clock = 0.0
        self.clock_set = False
        self.count = 0

    def set_clock(self, when):
        self.clock = _to_seconds(when)
        self.clock_set = True

    def create(self, *, beta, model, max_tokens, messages, system, tools, tool_choice,
               cache_control, thinking, output_config, diagnostics, betas):
        if not self.clock_set:
            self.clock += 1.0  # no traffic clock: requests run one second apart
        now = self.clock

        # Opus 5.5 request constraints.
        # https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5
        if thinking and thinking.get("type") in ("enabled", "disabled"):
            raise SimulatedAPIError('(offline) thinking is always on for this model: omit it or use {"type": "adaptive"}')
        if tool_choice and tool_choice.get("type") in ("any", "tool"):
            raise SimulatedAPIError('(offline) forced tool use is not supported: use tool_choice "auto" or "none"')

        blocks = _flatten(tools, system, messages)
        messages_context = _canon([tool_choice, thinking, output_config])
        hashes = _prefix_hashes(model, blocks, messages_context)
        positions = _positions(blocks)
        cum = list(itertools.accumulate(b.tokens for b in blocks))
        total = cum[-1] if cum else 0
        breakpoints = _breakpoints(blocks, cache_control)
        content_hashes = _prefix_hashes(model, blocks, "")  # content only, for thinking binding
        self._check_thinking_binding(model, blocks, content_hashes)

        # Reads: from the last breakpoint back, the first live entry an earlier request wrote.
        hit = None
        for bp, _ in reversed(breakpoints):
            i = bp
            while i >= 0 and positions[bp] - positions[i] < LOOKBACK_POSITIONS:
                entry = self.cache.get(hashes[i])
                if entry and entry["expires"] >= now:
                    hit = i
                    break
                i -= 1
            if hit is not None:
                break
        read = cum[hit] if hit is not None else 0
        if hit is not None:
            self._refresh(hashes[hit], now)

        # Writes: at each breakpoint past the hit that meets the minimum length.
        # Breakpoints inside the read prefix refresh their own entries.
        # (Unconfirmed: the docs say each use refreshes an entry but don't say
        # whether a matching earlier breakpoint counts as a use. The sim counts it.)
        last_1h = last_5m = None
        for bp, ttl in breakpoints:
            if hit is not None and bp <= hit:
                self._refresh(hashes[bp], now)
                continue
            if cum[bp] < config.MIN_CACHEABLE_TOKENS:
                continue
            self.cache[hashes[bp]] = {"ttl": ttl, "expires": now + TTL_SECONDS[ttl]}
            if ttl == "1h":
                last_1h = bp
            else:
                last_5m = bp
        written_1h = cum[last_1h] - read if last_1h is not None else 0
        after_1h = cum[last_1h] if last_1h is not None else read
        written_5m = cum[last_5m] - after_1h if last_5m is not None else 0
        written = written_1h + written_5m

        self.count += 1
        msg_id = f"msg_offline_{self.count:05d}"
        content, output_tokens, stop = self._reply(messages, max_tokens, content_hashes[-1] if blocks else "")
        payload = {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {
                "input_tokens": total - read - written,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": written,
                "cache_read_input_tokens": read,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": written_5m,
                    "ephemeral_1h_input_tokens": written_1h,
                },
            },
        }
        if not beta:
            return Message.model_validate(payload)

        fingerprint = _fingerprint(model, blocks, [tool_choice, thinking, output_config, betas])
        payload["diagnostics"] = self._diagnose(diagnostics, fingerprint) if diagnostics is not None else None
        if diagnostics is not None:
            # The API stores a fingerprint only for requests that include the diagnostics object.
            self.fingerprints[msg_id] = fingerprint
        return BetaMessage.model_validate(payload)

    def _refresh(self, key: str, now: float):
        entry = self.cache.get(key)
        if entry and entry["expires"] >= now:
            entry["expires"] = now + TTL_SECONDS[entry["ttl"]]

    def _reply(self, messages, max_tokens, prefix_hash):
        if max_tokens == 0:
            # Pre-warming: the cache is written, and the response is empty.
            return [], 0, "max_tokens"
        last = messages[-1]["content"] if messages else ""
        seed = int(_sha(_canon(last)), 16)
        text = REPLIES[seed % len(REPLIES)]
        # Adaptive thinking is always on for Opus 5.5. Its tokens bill as output,
        # and the block's text is empty at the default display ("omitted").
        thinking_tokens = 40 + seed % 240
        signature = f"offline-sig-{self.count:05d}"
        self.thinking[signature] = prefix_hash
        content = [
            {"type": "thinking", "thinking": "", "signature": signature},
            {"type": "text", "text": text},
        ]
        return content, thinking_tokens + count_tokens(text), "end_turn"

    def _check_thinking_binding(self, model, blocks, content_hashes):
        """Replaying an Opus 5.5 thinking block after anything before it changed is a 400.

        The API enforces this by default for accounts created on or after
        08/31/26; the sim behaves like one of those accounts.
        https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5
        """
        for b in blocks:
            if b.type != "thinking" or b.section != "messages":
                continue
            signature = json.loads(b.key)[3].get("signature")
            if signature not in self.thinking:
                continue
            first = next(i for i, x in enumerate(blocks) if x.message == b.message)
            before = content_hashes[first - 1] if first else _sha(_canon(["model", model]))
            if before != self.thinking[signature]:
                raise SimulatedAPIError("(offline) a thinking block was replayed after the system prompt, "
                                        "tools, or an earlier message changed")

    def _diagnose(self, diagnostics: dict, fp: dict):
        previous_id = diagnostics.get("previous_message_id")
        if previous_id is None:
            return None  # first turn: nothing to compare against
        prev = self.fingerprints.get(previous_id)
        if prev is None:
            return {"cache_miss_reason": {"type": "previous_message_not_found"}}
        # Unconfirmed: the docs say only the earliest divergence is reported but
        # don't give an order for model, system, and tools. The sim checks the
        # model first, then follows the prefix order: tools, system, messages.
        # cache_missed_input_tokens is estimated per block here, not from byte
        # lengths as the API does; like the real field, treat it as a magnitude.
        # Unconfirmed: whether the API compares against the previous request only
        # (as here) or also against its response content.
        if fp["model"] != prev["model"]:
            return _changed("model_changed", fp["total"])
        if fp["tools"] != prev["tools"]:
            return _changed("tools_changed", fp["total"])
        if fp["system"] != prev["system"]:
            return _changed("system_changed", fp["total"] - fp["tools_tokens"])
        if fp["params"] != prev["params"]:
            return {"cache_miss_reason": {"type": "unavailable"}}
        for i, h in enumerate(prev["messages"]):
            if i >= len(fp["messages"]) or fp["messages"][i] != h:
                return _changed("messages_changed", sum(fp["message_tokens"][i:]))
        return None  # no divergence
        # The sim never returns the pending state {"cache_miss_reason": null}.


def _changed(kind: str, missed: int) -> dict:
    return {"cache_miss_reason": {"type": kind, "cache_missed_input_tokens": missed}}


def _fingerprint(model: str, blocks: list[_Block], params: list) -> dict:
    """What the sim compares between requests: hashes and token estimates only."""
    tools = [b for b in blocks if b.section == "tools"]
    system = [b for b in blocks if b.section == "system"]
    by_message: dict[int, list[_Block]] = {}
    for b in blocks:
        if b.section == "messages":
            by_message.setdefault(b.message, []).append(b)
    return {
        "model": model,
        "tools": _sha("".join(b.key for b in tools)),
        "system": _sha("".join(b.key for b in system)),
        "params": _sha(_canon(params)),
        "messages": [_sha("".join(b.key for b in bs)) for _, bs in sorted(by_message.items())],
        "message_tokens": [sum(b.tokens for b in bs) for _, bs in sorted(by_message.items())],
        "tools_tokens": sum(b.tokens for b in tools),
        "total": sum(b.tokens for b in blocks),
    }


class _Messages:
    """client.messages: create() takes no diagnostics, like the SDK's non-beta method."""

    def __init__(self, engine: _Engine):
        self._engine = engine

    def create(self, *, model, max_tokens, messages, system=None, tools=None, tool_choice=None,
               cache_control=None, thinking=None, output_config=None, metadata=None):
        return self._engine.create(
            beta=False, model=model, max_tokens=max_tokens, messages=messages, system=system,
            tools=tools, tool_choice=tool_choice, cache_control=cache_control, thinking=thinking,
            output_config=output_config, diagnostics=None, betas=None)


class _BetaMessages:
    """client.beta.messages: create() also takes diagnostics and betas."""

    def __init__(self, engine: _Engine):
        self._engine = engine

    def create(self, *, model, max_tokens, messages, system=None, tools=None, tool_choice=None,
               cache_control=None, thinking=None, output_config=None, metadata=None,
               diagnostics=None, betas=None):
        return self._engine.create(
            beta=True, model=model, max_tokens=max_tokens, messages=messages, system=system,
            tools=tools, tool_choice=tool_choice, cache_control=cache_control, thinking=thinking,
            output_config=output_config, diagnostics=diagnostics, betas=betas)


class _Beta:
    def __init__(self, engine: _Engine):
        self.messages = _BetaMessages(engine)


class OfflineClient:
    """Drop-in for anthropic.Anthropic() in this lab. One instance is one workspace cache."""

    def __init__(self):
        self._engine = _Engine()
        self.messages = _Messages(self._engine)
        self.beta = _Beta(self._engine)

    def set_clock(self, when):
        """Run the next requests at this time (datetime, ISO string, or epoch seconds)."""
        self._engine.set_clock(when)
