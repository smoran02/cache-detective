# Cache Detective

> **Monday, 9am. The support agent's Claude bill tripled over the weekend, and nobody changed the model.**
> Wren, Kestrel Outdoor's support chat agent, runs on Opus 5.5 with prompt
> caching on. Friday's deploy was small. Traffic was normal. The bill wasn't.
>
> This lab finds the cache buster with the two tools the Claude API gives you
> for it: the usage fields on every response, and cache diagnostics.

A working support agent and a one-screen readout of its weekend: cache hit
rate and dollars per conversation, Friday's code next to yours. It runs
offline out of the box, on a simulated client that follows the documented
caching rules, so you need no API key to start. Solving the case is four small
functions in one file, and each one brings a clue online. About 20 minutes.

## Setup

You need Python **3.10+**. No API key for offline mode.

```bash
cd cache-detective
./scripts/setup.sh              # creates .venv and installs requirements
.venv/bin/python app.py         # the weekend readout, offline
```

The readout replays the weekend (252 conversations, 663 requests) through
Friday's code and through yours. Right now all four clues say *offline*,
and the last line names the function to write first.

## What you build

Open **`starter.py`**. Four functions, all `raise NotImplementedError`. Fill
them in one at a time and run `app.py` after each.

| # | Function | Clue | API surface | Lines |
|---|---|---|---|---|
| 1 | `meter()` | hit rate and $ per conversation | `response.usage` cache fields | ~12 |
| 2 | `send_with_diagnostics()` | why each request missed | `client.beta.messages.create(..., diagnostics=...)` | 3 |
| 3 | `build_request()` | move the cache buster | the `system` prompt and the new `user` message | 2 |
| 4 | `place_breakpoint()` | place the breakpoint, verify the drop | `cache_control` on a `system` block | 3 |

That's about 20 lines. Everything else (the handbook, Friday's request
builder, the replay loop, the readout, the offline client) is provided.

Stuck? `reference.py` has the finished versions. `LAB_SOLUTION=reference .venv/bin/python app.py` shows the solved case.

## The case

**Clue 1: the meter.** Every response carries `usage`. Three fields describe
input, and they don't overlap:

| Field | What it counts | Opus 5.5 price |
|---|---|---|
| `cache_read_input_tokens` | read from the cache | $0.20 / MTok |
| `cache_creation_input_tokens` | written to the cache | $5 / MTok (5-minute TTL) |
| `input_tokens` | after the last breakpoint, neither read nor written | $4 / MTok |

All input is the sum of the three: `input_tokens` alone is not the total.
Hit rate is the read share of that sum. `config.PRICES` has the per-token
prices. Run `app.py`: Friday's code has a **0.0%** hit rate at **$0.0539** per
conversation. Every request writes the whole prompt to the cache at 1.25x
the input price, and nothing ever reads it back.

**Clue 2: the witness.** Cache diagnostics (GA on the Claude API since
09/23/26) compares a request with an earlier one and names the first thing
that changed. Opt in on every request with a `diagnostics` object whose
`previous_message_id` is the previous response's `id` (or `None` on a
conversation's first turn). In the Python SDK the parameter is on
`client.beta.messages.create`; the API itself needs no beta header. Run
`app.py`: every follow-up turn says **`system_changed`**, with about 3,200
tokens missed. Now read `friday_request()` in `support.py`.

**Clue 3: move the cache buster.** Friday's deploy put the current time at
the top of the system prompt, so Wren would stop offering phone callbacks at
2am. The cache matches prefixes byte for byte, in the order tools, system,
messages, so a system prompt that changes every request can never be read
back. The documented fix: make the system prompt a byte-stable constant and
move the per-request value into the user message, after the cached part.
Run `app.py`: the hit rate jumps to **61%**. Follow-up turns read the cache.
But look at the diagnostics table: first turns read it **0** times out of 252.

**Clue 4: place the breakpoint.** Diagnostics can't help with first turns
(there's nothing to compare against), so reason from the rules. `make_request()`
uses automatic caching, which puts the breakpoint on the last block: the new
user message, different on every request. Writes happen only at a
breakpoint. On a miss, the API looks back up to 20 blocks for an entry an
earlier request *wrote*, and no request ever wrote one that ends at the
handbook. Put an explicit breakpoint on the last block every request shares,
the system prompt, and keep the automatic one for the growing conversation
(a request can carry up to 4). Run `app.py`: **90.8%** hit rate, **$0.0171** per
conversation, about a third of Friday's. Case closed.

## Check your work

```bash
.venv/bin/python -m pytest -q tests                          # tests your starter.py, offline
LAB_SOLUTION=reference .venv/bin/python -m pytest -q tests   # the finished version passes
```

`tests/test_offline.py` checks each clue, then replays the whole weekend
before and after your fix: Friday's code must stay near 0%, and yours must
reach at least 88% and $0.0190 per conversation. No key, no network.
`tests/test_live.py` skips unless `LAB_LIVE=1` (see below).

## Run it live

Offline token counts are simulated (about 4 characters per token). To see
real ones, pick a provider in `config.py` (`PROVIDER`) or with `LAB_PROVIDER`.
Live runs replay the first 6 conversations (17 requests) through each
version, back to back. At simulated token counts that's about $0.50 at
Claude API list prices; real counts differ.

**Claude API**

```bash
export ANTHROPIC_API_KEY=...
LAB_PROVIDER=anthropic .venv/bin/python app.py
LAB_LIVE=1 LAB_PROVIDER=anthropic .venv/bin/python -m pytest -q -s tests/test_live.py
```

**Amazon Bedrock**

```bash
export AWS_REGION=us-east-1     # or edit AWS_REGION in config.py
LAB_PROVIDER=bedrock .venv/bin/python app.py
LAB_LIVE=1 LAB_PROVIDER=bedrock .venv/bin/python -m pytest -q -s tests/test_live.py
```

| | Claude API | Claude in Amazon Bedrock |
|---|---|---|
| Client | `anthropic.Anthropic()` | `anthropic.AnthropicBedrockMantle(aws_region=...)` |
| Auth | `ANTHROPIC_API_KEY` | AWS credentials (env vars, profile, SSO, or role), plus model access in the Bedrock console |
| Model ID | `claude-opus-5-5` | `anthropic.claude-opus-5-5` |
| Prompt caching | yes, automatic and explicit | yes, automatic and explicit |
| Cache diagnostics | yes | not available: clue 2 is skipped |
| Billing | Claude API prices (`config.PRICES`) | AWS rates, so the readout's dollars are an estimate |

The live path is built but has not yet been run against either provider.

## Keep going

**TTL.** After the fix, 50 first turns still miss. Each comes after a
quiet stretch longer than 5 minutes (conversation `c002` starts at 08:35;
the last request before it was at 08:14). Their prefix is the same one
other first turns read, so nothing changed: the 5-minute entry expired.
(Diagnostics can't say so here, because a first turn has nothing to compare
against. On a follow-up turn, no reason plus a zero `cache_read_input_tokens`
means the same thing.) Try
`{"type": "ephemeral", "ttl": "1h"}` on the system breakpoint. A 1-hour write
costs 2x base input ($8 / MTok) instead of 1.25x, and 1-hour entries must
come before 5-minute ones. Update `meter()` to price
`usage.cache_creation.ephemeral_1h_input_tokens` at `config.PRICES["cache_write_1h"]`.
On this traffic: 97.8% hit rate, $0.0143 per conversation.

**Tool ordering.** Tools come first in the prefix, so any change to the
tool definitions invalidates the tools, system, and messages caches. In your
`build_request()`, add a `tools` list of two tool definitions, then shuffle
their order on each request with `random.sample(tools, 2)`. Offline,
diagnostics reports `tools_changed` on 192 requests and the hit rate falls
to 77%. The fix is a fixed order and deterministic serialization. (Offline
only: the simulated client never calls tools, and the replay loop doesn't run
a tool loop.)

**Minimum length.** Opus 5.5 caches a prefix only if it's at least 512
tokens (`config.MIN_CACHEABLE_TOKENS`); some other models need 1,024 to
4,096. Shorter prefixes run uncached with no error, and both cache fields
come back 0. Try `HANDBOOK[:1500]` (375 simulated tokens) as the system
prompt: a conversation's first two turns don't cache at all, and caching
starts once the conversation grows the prefix past 512 (turn 3 in `c001`).

## Teaching this

TODO

## Talking to customers

TODO

## What this teaches

- **Usage fields**: `cache_read_input_tokens`, `cache_creation_input_tokens`,
  and `input_tokens` split the input three ways, and the bill follows the split.
- **Cache diagnostics**: opt in per request, thread `previous_message_id`
  through the conversation, and read `cache_miss_reason.type`. `None` means no
  change, or nothing to compare.
- **Prefix order and what invalidates it**: tools, then system, then
  messages. A change anywhere invalidates everything after it.
- **Breakpoints**: writes happen only at a breakpoint; reads look back for
  what earlier requests wrote. Automatic caching lands on the last block, so
  a varying last block needs an explicit breakpoint before it.
- **Providers**: the same fix on the Claude API and on Bedrock, with a
  different client, model ID, and feature set.

## How offline mode works

`offline.py` stands in for the client. It applies the rules from the
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
and [cache diagnostics](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics)
docs: exact prefix matching in tools, system, messages order; writes only at
breakpoints; the 20-block lookback; 5-minute and 1-hour TTLs on the traffic's
own clock; the 512-token minimum; and the documented `diagnostics` shape. It
returns the SDK's own `Message` and `BetaMessage` types. It does not count
tokens like the real tokenizer (every offline count is simulated), write real
replies, or call tools.

## Repo layout

```
starter.py        ← the only file you edit
reference.py      ← finished versions
app.py            ← the weekend readout
support.py        ← Wren: handbook loader, Friday's request, the replay loop
offline.py        ← simulated Claude API client for offline mode
clients.py        ← picks the client for config.PROVIDER
config.py         ← provider, model IDs, region, prices

data/             ← handbook.md (the system prompt), weekend.json (the traffic), make_traffic.py
tests/            ← test_offline.py (offline E2E), test_live.py (runs with LAB_LIVE=1)
scripts/setup.sh  ← one-command setup
```
