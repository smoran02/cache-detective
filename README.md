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
functions in one file, and each one brings a clue online. About 30 minutes if
you've shipped on the Claude API; about an hour if the API is new to you.

Walkthrough video: `[confirm: video URL]`

**New to prompt caching?** A request is a prefix of blocks: tools, then
system, then messages. A **breakpoint** is a `cache_control` marker on a block
(nothing to do with a debugger). The API writes the prefix that ends there to
the cache, and a later request that starts with the same bytes reads it back
for a fraction of the input price. An entry lives 5 minutes, and each read
restarts the clock. Prices here are per MTok (million tokens). The
[prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
have the full rules.

## Setup

You need Python **3.10+**. No API key for offline mode.

```bash
git clone [confirm: repo URL] cache-detective && cd cache-detective
./scripts/setup.sh              # creates .venv and installs requirements
.venv/bin/python app.py         # the weekend readout, offline
```

On Windows, set up by hand and use `.venv\Scripts\python` wherever this
README says `.venv/bin/python`:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

The readout replays the weekend (252 conversations, 663 requests) through
Friday's code and through yours. Right now all four clues say *offline*:
none of the four functions is written yet. The last line names the one to
write first.

## What you build

Open **`starter.py`**. Four functions, all `raise NotImplementedError`. Fill
them in one at a time and run `app.py` after each.

| # | Function | Clue | API surface | Lines |
|---|---|---|---|---|
| 1 | `meter()` | hit rate and $ per conversation | `response.usage` cache fields | ~14 |
| 2 | `send_with_diagnostics()` | why each request missed | `client.beta.messages.create(..., diagnostics=...)` | 6 |
| 3 | `build_request()` | move the cache buster | the `system` prompt and the new `user` message | 2 |
| 4 | `place_breakpoint()` | place the breakpoint, verify the drop | `cache_control` on a `system` block | 4 |

That's about 25 lines. Everything else (the handbook, Friday's request
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
prices, output included. Run `app.py`: Friday's code has a **0.0%** hit rate
at **$0.0539** per conversation. Every request writes the whole prompt to the
cache at 1.25x the input price, and nothing ever reads it back. (The
`uncached` column stays 0 on every row: automatic caching puts the breakpoint
on the last block, so nothing comes after it. Keep going, Minimum length,
shows it move.)

**Clue 2: the witness.** Cache diagnostics
([GA on the Claude API since 09/23/26](https://platform.claude.com/docs/en/release-notes/overview))
compares a request with an earlier one and names the first thing that
changed. Opt in on every request with a `diagnostics` object whose
`previous_message_id` is the previous response's `id` (or `None` on a
conversation's first turn). In the Python SDK the parameter is on
`client.beta.messages.create`; the API itself needs no beta header.
`response.diagnostics` comes back in one of three states: `None` (nothing
changed, or nothing to compare), a `cache_miss_reason` naming what changed,
or `{"cache_miss_reason": null}` (the comparison was still running: check the
next turn). Run `app.py`: every follow-up turn says **`system_changed`**, with
about 3,200 tokens missed. Friday's deploy is in `data/friday.diff`. What in
the system prompt is different on every request?

**Clue 3: move the cache buster.** The time. Friday's deploy put it at the
top of the system prompt, so Wren would stop offering phone callbacks at
2am. The cache matches prefixes byte for byte, in the order tools, system,
messages, so a system prompt that changes every request can never be read
back. The fix the diagnostics docs give for `system_changed`: make the system
prompt a byte-stable constant and move the per-request value into the user
message. Earlier messages never change, so each turn can read the prefix the
turn before it wrote. (On Opus 5.5 the docs also allow appending a
`{"role": "system"}` message to `messages`; the tests accept either.) Run
`app.py`: the hit rate jumps to **61%**. Follow-up turns read the cache. But
look at the diagnostics table: first turns read it **0** times out of 252.

**Clue 4: place the breakpoint.** The lab threads diagnostics through each
conversation, so a first turn has nothing to compare against: reason from
the rules. `make_request()` uses automatic caching, which puts the breakpoint
on the last block: the new user message, different on every request. Writes
happen only at a breakpoint. On a miss, the API looks back up to 20 blocks
for an entry an earlier request *wrote*, and no request ever wrote one that
ends at the handbook. (The docs'
[worked example](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-automatic-prefix-checking-works)
is this bug.) Now read the diff's other hunk. Put an explicit breakpoint on
the last block every request shares, and keep the automatic one for the
growing conversation (a request can carry up to 4). Run `app.py` and watch
`c003`'s first turn read the handbook. Hit rate **90.8%**, about **$0.0171**
per conversation: a third of Friday's, and where Thursday's code was before
the deploy. Case closed.

## Check your work

```bash
.venv/bin/python -m pytest -q tests                          # tests your starter.py, offline
.venv/bin/python -m pytest -q tests -k clue_1                # one clue at a time: clue_1 to clue_4
LAB_SOLUTION=reference .venv/bin/python -m pytest -q tests   # the finished version passes
```

`tests/test_offline.py` checks each clue, then replays the whole weekend
before and after your fix: Friday's code must stay near 0%, and yours must
reach at least 88% and at most $0.0190 per conversation. The tests use their
own meter, so a bug in `meter()` can't hide a bad fix. `tests/test_simulator.py`
checks the offline client against the documented caching rules; it passes
before you write anything. No key, no network. `tests/test_live.py` skips
unless `LAB_LIVE=1` (see below).

## If something goes wrong

| What you see | Why |
|---|---|
| `ZeroDivisionError` in `meter()` | Dividing by `input_tokens`, which is 0 on every request here. Divide by all input. |
| `TypeError: ... unexpected keyword argument 'diagnostics'` | `client.messages.create`. The SDK takes `diagnostics` on `client.beta.messages.create`. |
| `previous_message_not_found` on second turns | The first turn went out without a `diagnostics` object, so the API kept no fingerprint of it. Send `{"previous_message_id": None}`. |
| `SimulatedAPIError: ... 4 explicit breakpoints ...` | `cache_control` on the user message. It stays in the history, so markers pile up turn by turn. |
| Clue 3 test: "don't change history" | `history.append(...)` changes the caller's list. Build a new one: `history + [message]`. |

## Run it live

Offline token counts are simulated (about 4 characters per token). To see
real ones, pick a provider in `config.py` (`PROVIDER`) or with `LAB_PROVIDER`.
Live runs replay the first 6 conversations (17 requests) through each
version, back to back, stamping each request with the wall clock as Friday's
deploy did, so one run never reads what the last one wrote. At simulated
token counts that's about $0.50 at Claude API list prices; real counts differ.

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
(Diagnostics can't say so here: the lab sends `None` on first turns. On a
follow-up turn, no reason plus a zero `cache_read_input_tokens` means the
same thing.) Try
`{"type": "ephemeral", "ttl": "1h"}` on the system breakpoint. A 1-hour write
costs 2x base input ($8 / MTok) instead of 1.25x, and 1-hour entries must
come before 5-minute ones. Update `meter()` to price
`usage.cache_creation.ephemeral_1h_input_tokens` at `config.PRICES["cache_write_1h"]`.
On this traffic: 97.8% hit rate, $0.0143 per conversation.

**Tool ordering.** Tools come first in the prefix, so any change to the
tool definitions invalidates the tools, system, and messages caches. In your
`build_request()`, add a `tools` list of two tool definitions, then shuffle
their order on each request with `random.sample(tools, 2)`. Offline,
diagnostics reports `tools_changed` on about 200 requests (the order is
random, so the count varies from run to run) and the hit rate falls to about
77%. The fix is a fixed order and deterministic serialization. (Offline
only: the simulated client never calls tools, and the replay loop doesn't run
a tool loop.)

**Minimum length.** Opus 5.5 caches a prefix only if it's at least 512
tokens (`config.MIN_CACHEABLE_TOKENS`); some other models need 1,024 to
4,096. Shorter prefixes run uncached with no error, and both cache fields
come back 0. Try `HANDBOOK[:1500]` (375 simulated tokens) as the system
prompt: first turns never cache, and caching starts once the conversation
grows the prefix past 512 (turn 3 in `c001`, turn 2 in 10 conversations).

## Take it to your app

Your `send_with_diagnostics()` and `meter()` work on any Claude API request,
not just Wren's:

```python
from starter import meter, send_with_diagnostics

previous_id = None                  # per conversation: None on its first turn
for request in turns:               # the kwargs you already pass to messages.create
    response, reason = send_with_diagnostics(client, request, previous_id)
    previous_id = response.id
    log(response.usage, reason)     # None, "pending", or reason.type names what changed

hit_rate, dollars = meter(usages)   # usage objects from your logs
```

For usage logged as JSON, `anthropic.types.Usage(**row)` rebuilds the
object. `config.PRICES` is Opus 5.5 on the Claude API; change it for your
model. Diagnostics is Claude API only, and no doc states Bedrock's usage
field names yet.

## Teaching this

**Timing.** Three simulated learners (Claude as a novice, a median, and a
strong learner) estimated 26 to 29 minutes for engineers who have shipped on
the Claude API, and 55 for a Python developer new to it, mostly spent on
vocabulary. The 29-minute run: README and setup 6, reading the code 5, clue 1
5, clue 2 6, clue 3 3, clue 4 3, tests 1. `[confirm after a timed run with a person]`

**Where people get stuck.**

1. **Clue 4: why don't first turns read?** All three runs lost time looking
   for proof the fix worked, and the novice spent 10 minutes on the lookback
   rule. People expect the cache to find the handbook because it's stable.
   Draw two first turns side by side: the lookback finds entries earlier
   requests wrote at their breakpoints, not stable content. Then point at
   `c003`'s first turn: 0 read before the fix, the whole handbook after.
2. **The words, before clue 1.** The novice spent 12 minutes in the docs
   before writing code: "breakpoint" read as a debugger term, and the
   `uncached` column sits at 0. Start with "New to prompt caching?", and say
   why `input_tokens` is 0 here.

**On Bedrock.** Clue 2 is skipped: cache diagnostics is Claude API only. Use
`AnthropicBedrockMantle` and `anthropic.claude-opus-5-5`, and check Opus 5.5
model access in the Bedrock console before the session. The readout's
dollars are Claude API prices; AWS bills at its own rates.

**Rate limits.** Teach the room offline: no key, no limits. Run live as a
presenter demo (34 requests per `app.py` run, 34 more for the live test).
The SDK retries a 429 twice with backoff; if you're still rate-limited,
switch to offline and show your own earlier live numbers. Cache hits don't
count against the rate limit, which is worth saying.

## Talking to customers

- **"Our bill went up and we didn't change the model."** Ask for the `usage`
  of one follow-up request. High `cache_creation_input_tokens` with 0
  `cache_read_input_tokens` usually means something before the breakpoint
  changes on every request (or the turns are more than 5 minutes apart). On
  the Claude API, turn on `diagnostics` for one conversation and read
  `cache_miss_reason.type`: it names what changed.
- **On Bedrock,** caching works the same way (automatic and explicit
  breakpoints, a 512-token minimum on Opus 5.5, 5-minute and 1-hour TTLs),
  but there's no cache diagnostics, the cache is isolated per organization
  rather than per workspace, and AWS bills at its own rates. To name a
  culprit, send the same request shape to the Claude API with diagnostics on.
- **Price the fix at their volume.** On Opus 5.5, cache reads cost 0.05x base
  input, 5-minute writes 1.25x, and 1-hour writes 2x. In this lab, 10,000
  conversations cost $539 on Friday's code and $171 fixed. Cache hits also
  don't count against the rate limit.

## How offline mode works

`offline.py` stands in for the client. It applies the rules from the
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
and [cache diagnostics](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics)
docs: exact prefix matching in tools, system, messages order; writes only at
breakpoints; the 20-block lookback; 5-minute and 1-hour TTLs on the traffic's
own clock; the 512-token minimum; and the documented `diagnostics` shape. It
returns the SDK's own `Message` and `BetaMessage` types, and
`tests/test_simulator.py` checks each rule. It does not count tokens like the
real tokenizer (every offline count is simulated), write real replies, or
call tools.

Where the docs are silent, it picks a reading and marks it `Unconfirmed:` in
the code:

- A breakpoint inside the prefix a request reads counts as a use and
  refreshes its entry. The headline numbers rest on this: without it, the fix
  gets 84.4% and $0.0197 per conversation.
- Diagnostics reports the model first, then tools, system, and messages, and
  compares with the previous request, not its response. (The first live run
  will show whether reply text sent back without its thinking block counts.)
- `cache_missed_input_tokens` is estimated per block, not from byte lengths.

## What this teaches

- **Usage fields**: `cache_read_input_tokens`, `cache_creation_input_tokens`,
  and `input_tokens` split the input three ways, and the bill follows the split.
- **Cache diagnostics**: opt in per request, thread `previous_message_id`
  through the conversation, and read `cache_miss_reason.type`. `None` means
  no change or nothing to compare; `{"cache_miss_reason": null}` means the
  comparison hadn't finished, so check the next turn.
- **Prefix order and what invalidates it**: tools, then system, then
  messages. A change anywhere invalidates everything after it.
- **Breakpoints**: writes happen only at a breakpoint; reads look back for
  what earlier requests wrote. Automatic caching lands on the last block, so
  a varying last block needs an explicit breakpoint before it.
- **Providers**: the same fix on the Claude API and on Bedrock, with a
  different client, model ID, and feature set.

## Repo layout

```
starter.py        ← the only file you edit
reference.py      ← finished versions
app.py            ← the weekend readout
support.py        ← Wren: handbook loader, Friday's request, the replay loop
offline.py        ← simulated Claude API client for offline mode
clients.py        ← picks the client for config.PROVIDER
config.py         ← provider, model IDs, region, prices

data/             ← handbook.md (the system prompt), weekend.json (the traffic), friday.diff (the deploy), make_traffic.py
tests/            ← test_offline.py (your code), test_simulator.py (the offline client), test_live.py (LAB_LIVE=1), truth.py (the tests' meter)
scripts/setup.sh  ← one-command setup
```

## License

`[confirm: license]`
