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
functions in one file, and each one brings a clue online. About 35 minutes if
you've shipped on the Claude API; about an hour if the API is new to you.
Learners need Setup through Take it to your app; the sections after that are
for instructors and field teams.

<!-- [confirm: video URL] Add "Walkthrough video: <URL>" here once it's recorded; until then, no line. -->

**New to prompt caching?** A request is a list of **blocks** in a fixed
order: the tools, then the system prompt, then the messages. A
**breakpoint** is a `cache_control` marker on one block (nothing to do with a
debugger). The API writes everything from the first block through the marked
one, the **prefix**, to the cache, and a later request that starts with the
same bytes reads it back for a fraction of the input price. A request writes
only prefixes that end at its breakpoints, and a read only finds a prefix an
earlier request wrote. (To carry a marker, a plain-string system prompt
becomes a list of one text block.) **Automatic caching** is a `cache_control`
at the top level of the request instead: the API puts the breakpoint on the
last block for you. An entry lives 5 minutes (its TTL, or time to live), and
each read restarts the clock. Prices here are per MTok (million tokens). The
[prompt caching docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
have the full rules.

## Setup

You need Python **3.10+** and no API key. (macOS's built-in `python3` is
3.9.6: install a newer one from python.org or Homebrew, then run
`PYTHON=python3.12 ./scripts/setup.sh`.)

```bash
git clone [confirm: repo URL] cache-detective && cd cache-detective
./scripts/setup.sh              # creates .venv and installs requirements
.venv/bin/python app.py         # the weekend readout, offline
```

On Windows, run `python -m venv .venv` and
`.venv\Scripts\python -m pip install -r requirements.txt`, then use
`.venv\Scripts\python` for `.venv/bin/python`. In PowerShell, set
variables on their own line first (`$env:NAME="value"`).

The readout replays the weekend (252 conversations, 663 requests) through
Friday's code and through yours. Right now all four clues say *offline*:
none of the four functions is written yet. The last line names the one to
write first.

## What you build

Open **`starter.py`**. Four functions, all `raise NotImplementedError`. Fill
them in one at a time and run `app.py` after each.

| # | Function | Clue | API surface | Lines |
|---|---|---|---|---|
| 1 | `meter()` | hit rate and $ per conversation | `response.usage` cache fields | 19 |
| 2 | `send_with_diagnostics()` | why each request missed | `client.beta.messages.create(..., diagnostics=...)` | 6 |
| 3 | `build_request()` | move the cache buster | the `system` prompt and the new `user` message | 2 |
| 4 | `place_breakpoint()` | place the breakpoint, verify the drop | `cache_control` on a `system` block | 5 |

That's about 30 lines in `reference.py`. Everything else (the handbook,
Friday's request builder, the replay loop, the readout, the offline client)
is provided.

Stuck? `reference.py` has the finished versions. `LAB_SOLUTION=reference .venv/bin/python app.py` shows the solved case. To skip a clue, copy that one function over; to start over, `git checkout starter.py`.

## The case

**Clue 1: the meter.** Every response carries `usage`. Three fields describe
input, and they don't overlap:

| Field | What it counts | Opus 5.5 price |
|---|---|---|
| `cache_read_input_tokens` | read from the cache | $0.20 / MTok |
| `cache_creation_input_tokens` | written to the cache | $5 / MTok (5-minute TTL) |
| `input_tokens` | after the last breakpoint, neither read nor written | $4 / MTok |

All input is the sum of the three: `input_tokens` alone is not the total.
Hit rate is the read share of that sum. Dollars use the `prices` argument,
which defaults to `config.PRICES` (per token, output included). Run
`app.py`: Friday's code has a **0.0%** hit rate at **$0.0539** per
conversation, and the line under the table shows Thursday's code, before the
deploy, at **$0.0172**. The bill tripled. Every request writes the whole
prompt to the cache at 1.25x the input price, and nothing ever reads it back.

**Clue 2: the witness.** Cache diagnostics
([GA on the Claude API since 09/23/26](https://platform.claude.com/docs/en/release-notes/overview))
compares a request with an earlier one and names the first thing that
changed. Opt in on every request with a `diagnostics` object whose
`previous_message_id` is the previous response's `id` (or `None` on a
conversation's first turn). The API needs no beta header, but the Python SDK
(1.8) takes `diagnostics` only on its beta methods, like
`client.beta.messages.create`. `response.diagnostics` comes back in one of
three states: `None` (nothing changed, or nothing to compare), a
`cache_miss_reason` naming what changed, or `{"cache_miss_reason": null}` (the
comparison was still running: check the next turn). Run `app.py`: every
follow-up turn says **`system_changed`**, with about 3,200 tokens missed.
Friday's deploy is in `data/friday.diff`, from Wren's repo; the lab's copy of
the deployed code is `friday_request()` in `support.py`. What in the system
prompt is different on every request?

**Clue 3: move the cache buster.** Write `build_request()` so the system
prompt is the same bytes on every request, and Wren still gets what Friday's
deploy gave it. Run `app.py`: the hit rate jumps to about **61%**, and
follow-up turns read the cache. But look at the diagnostics table: first
turns read it **0** times out of 252.

<details><summary>Explain clue 3</summary>

The time. Friday's deploy put it at the top of the system prompt so Wren
would stop offering phone callbacks at 2am. The cache matches prefixes byte
for byte, in the order tools, system, messages, so a system prompt that
changes on every request is never read back. The
[diagnostics docs' fix](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#cache-miss-reason-types)
for `system_changed` has two halves: "Make the system prompt a byte-stable
constant and move dynamic data into the first `user` message after your cache
breakpoint." Clue 3 is the first half: the time, date included, goes into the
new user message. Earlier messages never change, so each turn can read the
prefix the turn before it wrote. The breakpoint is clue 4. (On Opus 5.5 you
can instead put the time in a
[`{"role": "system"}` message](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages)
right after the new user message; one placed before it is a 400. The tests
accept either.) Rolling back Friday's deploy isn't a fix: Wren would offer
callbacks at 2am again.

</details>

**Clue 4: place the breakpoint.** The handbook is the same on every request,
so why can't a new conversation's first turn read it? Diagnostics can't
say: a first turn has nothing to compare against. Reason from the rules in
[How automatic prefix checking works](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#how-automatic-prefix-checking-works)
and its second example, "Common mistake: Breakpoint on content that changes
every request." Then read the diff's other hunk. Run `app.py` and watch
`c003`'s first turn read the handbook. When your code clears the tests' bar,
the readout says **Case closed**: about **91%** and **$0.017** per
conversation, a third of Friday's and where Thursday's code was, with the
time still in.

<details><summary>Explain clue 4</summary>

`make_request()` uses automatic caching, which puts the breakpoint on the last
block: the new user message, different on every request. Writes happen only
at a breakpoint. On a miss, the API looks back up to 20 blocks for an entry
an earlier request *wrote*, and no request ever wrote one that ends at the
handbook. Put an explicit breakpoint on the system prompt, the last block
every request shares, and keep the automatic one for the growing
conversation (a request can carry up to 4). `c002`'s first turn still misses
after the fix: the last request before it was 21 minutes earlier, so its
entry had expired (Keep going, TTL).

</details>

## Check your work

```bash
.venv/bin/python -m pytest -q tests                          # tests your starter.py, offline
.venv/bin/python -m pytest -q tests -k clue_1                # one clue at a time: clue_1 to clue_4
LAB_SOLUTION=reference .venv/bin/python -m pytest -q tests   # the finished version passes
```

Before you write anything: 7 failed (the clue tests), 44 passed, 1 skipped.
`tests/test_offline.py` checks each clue, then replays the weekend: Friday's
code must stay near 0%, and yours must clear `config.BAR` (at least 88% and
at most $0.0190 per conversation), priced by the tests' own meter so a bug in
`meter()` can't hide a bad fix. The readout runs the same clue 3 check and
bar before it says "Case closed." The bar is calibrated to the simulator,
including one reading the docs leave open (How offline mode works).
`tests/test_simulator.py` checks the simulator; `tests/test_live.py` skips
unless `LAB_LIVE=1`.

## If something goes wrong

| What you see | Why |
|---|---|
| `ZeroDivisionError` in `meter()` | Dividing by `input_tokens`, which is 0 on every request here. Divide by all input. |
| `TypeError: ... unexpected keyword argument 'diagnostics'` | `client.messages.create`. The SDK takes `diagnostics` on `client.beta.messages.create`. |
| "return the cache_miss_reason itself" (tests or readout) | `send_with_diagnostics()` returned `cache_miss_reason.type`, a string. Return the reason; the readout reads its `.type`. |
| `previous_message_not_found` on second turns | The first turn went out without a `diagnostics` object, so the API kept no fingerprint of it. Send `{"previous_message_id": None}`. |
| `SimulatedAPIError: ... breakpoints ...` (live: a 400) | `cache_control` on the user message. It stays in the history, so markers pile up turn by turn until a request passes the limit of 4. |
| `SimulatedAPIError: ... a system message must directly follow a user message ...` | The time went into a `{"role": "system"}` message before the new user message. Put it after that message, or in it. |
| The readout says "Not yet" | All four functions run, but your code misses the tests' bar. The lines under it name the first cause. |

## Run it live

Offline token counts are simulated (about 4 characters per token). For real
ones, set `PROVIDER` in `config.py` or `LAB_PROVIDER`. Live runs replay the
first 6 conversations (17 requests) through each version, back to back,
stamped with the wall clock as Friday's deploy was, so Friday's prompts never
repeat from one run to the next: about $0.50 at list prices, at simulated
token counts. Live, "Case closed" needs a 70% hit rate and a lower bill than
Friday's.

**Claude API**

```bash
export ANTHROPIC_API_KEY=...
LAB_PROVIDER=anthropic .venv/bin/python app.py
LAB_LIVE=1 LAB_PROVIDER=anthropic .venv/bin/python -m pytest -q -s tests/test_live.py
```

**Amazon Bedrock**

```bash
export AWS_REGION=us-east-1     # or AWS_DEFAULT_REGION, or edit AWS_REGION in config.py
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

**TTL.** After the fix, 50 first turns still miss, each after more than 5
quiet minutes (the readout shows them). Nothing changed: the 5-minute entry
expired. (On a follow-up turn, no diagnostics reason plus a zero
`cache_read_input_tokens` means the same.) Try
`{"type": "ephemeral", "ttl": "1h"}` on the system breakpoint. A 1-hour
write costs 2x base input ($8 / MTok) instead of 1.25x, and 1-hour entries
must come before 5-minute ones. Update `meter()` to price
`usage.cache_creation.ephemeral_1h_input_tokens` at `prices["cache_write_1h"]`
(`usage.cache_creation` can be `None` too). On this traffic: 97.8% hit rate,
$0.0143 per conversation. Only 6,196 tokens are 1-hour writes, so the meter
update shows only in the Weekend bill row: $3.60 before, $3.62 after.

**Tool ordering.** Tools come first in the prefix, so any change to the
tool definitions invalidates the tools, system, and messages caches. In your
`build_request()`, add two tool definitions and shuffle them on each request
with `random.sample(tools, 2)`. Offline, diagnostics reports `tools_changed`
on about 200 requests and the hit rate falls to about 77%. The fix is a
fixed order and deterministic serialization. (The simulated client never
calls tools.)

**Minimum length.** Opus 5.5 caches a prefix only if it's at least 512
tokens (`config.MIN_CACHEABLE_TOKENS`); some other models need 1,024 to
4,096. Shorter prefixes run uncached with no error, and both cache fields
come back 0. Try `HANDBOOK[:1500]` (375 simulated tokens) as the system
prompt: first turns never cache, and caching starts once the conversation
grows the prefix past 512 (turn 3 in `c001`, turn 2 in 10 conversations).
Watch the `uncached` column: it's 0 everywhere else, because automatic
caching puts a breakpoint on the last block and `input_tokens` counts only
what comes after the last breakpoint. Here it fills.

## Take it to your app

Copy your `meter()` and `send_with_diagnostics()` into your app, dropping
the `config.PRICES` default (pass your own prices). Call
`send_with_diagnostics()` where you call `client.beta.messages.create`, carry
each conversation's latest `response.id` forward, and log `reason.type` when
the reason is neither `None` nor `"pending"`. (In your app, `None` can also
mean a request went out without `diagnostics`.) Streaming? Pass the same
`diagnostics` to `client.beta.messages.stream(...)` and read
`stream.get_final_message().diagnostics`. Diagnostics never blocks or fails
a request, and it keeps only hashes and token-count estimates, not your prompts
([data retention](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#data-retention)).
Log `usage` too; this reads it back:

```python
# usage_report.py: hit rate and dollars from your app's logged usage.
# Log each response as it comes back:  log.write(json.dumps(response.usage.to_dict()) + "\n")
import json

from anthropic.types import Usage

PRICES = {  # $ per token for your model and provider. These are Opus 5.5 on the Claude API.
    "input": 4.00e-6, "cache_write_5m": 5.00e-6, "cache_write_1h": 8.00e-6,
    "cache_read": 0.20e-6, "output": 20.00e-6,
}

# Paste your meter() from starter.py here.

with open("usage.jsonl") as log:
    usages = [Usage(**json.loads(line)) for line in log]
hit_rate, dollars = meter(usages, PRICES)
print(f"{len(usages)} requests: {hit_rate:.1%} of input read from the cache, ${dollars:.2f}")
```

Diagnostics is Claude API only. On Bedrock, copy `divergence.py` too:
`first_divergence(earlier, later)` hashes the model, tools, system prompt,
and each message of two consecutive requests and names the first part that
differs (`"system"`, `"messages[3]"`). For Bedrock's usage field names, the
Claude docs send you to
[AWS's prompt caching page](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html),
which documents only the Converse API's.

## Teaching this

**Timing.** Three simulated learners (Claude playing a novice, a median, and
a strong learner) estimated 36 and 40 minutes for engineers who have shipped
on the Claude API (the 40 includes 12 optional minutes checking the docs; 26
without) and 55 for a Python developer new to it. The 36-minute run: README
6, setup 2, first readout and code 5, clue 1 4, clue 2 6, clue 3 4, clue 4 5,
tests 1, rereads 3. They played the previous version, whose starter said
where the time and the breakpoint go; this one asks instead. Not yet timed
with a person.

**Ready to teach it** when you can solve it from a fresh `starter.py`
without opening `reference.py`, draw two first turns side by side from
memory and say why only one reads the handbook, and answer "why can't
diagnostics see clue 4?" and "what if live numbers differ?" (How offline
mode works lists what the simulator assumes).

**Before the session,** have everyone run `./scripts/setup.sh`: pip needs the
network, and macOS's built-in `python3` is too old.

| After | Every screen shows |
|---|---|
| Clue 1 | 0.0% and $0.0539 in both columns; Thursday's $0.0172 under them (3.1x) |
| Clue 2 | `system_changed` on all 411 follow-up turns, about 3,200 tokens missed |
| Clue 3 | about 61% and $0.029; first turns read the cache 0 times out of 252 |
| Clue 4 | about 91% and $0.017; `c003`'s first turn reads 3,098; "Case closed" |

The last digits shift a little with how each learner words the time, since
simulated reply lengths follow the message text. To spot who's stuck, have
the room read out their four Clue lines.

**Where people get stuck.**

1. **Clue 4: why can't a first turn read the handbook?** The novice spent 10
   minutes here, docs included. The median solved it from the diff and
   could have finished without understanding the rule it turns on, then
   paused at `c002`'s first turn still reading 0. The primer now states the rule, and the
   readout shows the quiet minutes before a first turn. Draw two first
   turns side by side and ask what any earlier request wrote. Point at
   `c003`'s first turn (0 read before the fix, 3,098 after), and say that
   `c002` still misses because 21 quiet minutes outlast the 5-minute TTL.
2. **Clue 2: the three states of `response.diagnostics`.** The novice spent
   10 minutes, including the diagnostics docs, and it was the median's
   longest clue (6 minutes), slowed by the three-way return. Write
   the three states on the board: `None` (nothing changed, or nothing to
   compare), `{"cache_miss_reason": null}` (still comparing; the lab returns
   `"pending"`), and a reason whose `.type` names the change.

**The 45-minute version,** paced on the median run: hook and setup check 5
minutes, clues 1 and 2 10, clue 3 5, clue 4 10, Keep going 10 (TTL, then
Tool ordering), debrief 5. **Debrief:** keep the prefix byte-stable, put a
breakpoint at the end of what requests share, and prove it with the usage
split (and diagnostics, on the Claude API). Then walk through Talking to
customers.

**On Bedrock,** clue 2 is skipped: cache diagnostics is Claude API only. Use
`AnthropicBedrockMantle` and `anthropic.claude-opus-5-5`, check Opus 5.5
model access in the Bedrock console before the session, and remember the
readout's dollars are Claude API prices.

**Rate limits.** Teach the room offline: no key, no limits. Run live as a
presenter demo (34 requests per `app.py` run, 34 more for the live test).
The SDK retries a 429 twice with backoff; if you're still rate-limited,
switch to offline and show your own earlier live numbers.

## Talking to customers

- **"Our bill went up and we didn't change the model."** Ask for the `usage`
  of one follow-up request. High `cache_creation_input_tokens` with 0
  `cache_read_input_tokens` usually means something before the breakpoint
  changes on every request (or the turns are more than 5 minutes apart). On
  the Claude API, turn on `diagnostics` for one conversation and read
  `cache_miss_reason.type`: it names what changed. Then ask for a first
  turn. If first turns always write the whole system prompt and never read,
  nothing marks the end of what requests share, because automatic caching
  alone lands on the new message. Diagnostics can't name that one; the usage
  split can.
- **On Bedrock,** caching works the same way (automatic and explicit
  breakpoints, a 512-token minimum on Opus 5.5, 5-minute and 1-hour TTLs),
  but there's no cache diagnostics, the cache is isolated per organization
  rather than per workspace, and AWS bills at its own rates. To find the
  culprit, run `divergence.py` on two consecutive requests of one
  conversation: it hashes the tools, the system prompt, and each message,
  and the first hash that differs is the change (diagnostics compares hashes
  too). They can send you the hashes (`fingerprint()`) instead of the
  prompts.
- **Price the fix at their volume.** On Opus 5.5, cache reads cost 0.05x base
  input, 5-minute writes 1.25x, and 1-hour writes 2x. In this lab (simulated
  token counts), 10,000 conversations cost $539 on Friday's code and $171
  fixed. Cache reads also don't count toward the
  [input-tokens-per-minute limit](https://platform.claude.com/docs/en/api/rate-limits)
  on most models, Opus 5.5 included; cache writes and uncached input do.

## How offline mode works

`offline.py` stands in for the client, applying the
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
and [cache diagnostics](https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics)
rules its docstring lists; `tests/test_simulator.py` has a test for each. It
returns the SDK's own `Message` and `BetaMessage` types. It doesn't count
tokens like the real tokenizer, write real replies (their simulated lengths
vary with the request), or call tools. Where the docs are silent, it picks a
reading, marks it `Unconfirmed:` in the code, and pins it with a test:

- A breakpoint inside the prefix a request reads counts as a use and
  refreshes its entry (the docs' multi-turn example calls an earlier-marked
  block read again "a cache hit (and also a cache refresh!)", and their
  mixed-TTL billing counts from "the highest cache hit"). The lab's numbers
  rest on this. With `REFRESH_BREAKPOINTS_INSIDE_THE_READ = False` in
  `offline.py`, the fix gets 84.4% and $0.0197, Friday's bill is 2.7x
  Thursday's instead of 3.1x, and the reference fails 3 offline tests.
- Diagnostics reports the model first, then tools, system, and messages, and
  compares with the previous request, not its response. (The first live run
  will show whether reply text sent back without its thinking block counts.)
- With 4 explicit breakpoints, the last on the last block, the docs call
  automatic caching a no-op there and also say 4 explicit breakpoints are a
  400. The sim returns the 400.
- `cache_missed_input_tokens` is estimated per block, not from byte lengths.

## What this teaches

- **Usage fields**: `cache_read_input_tokens`, `cache_creation_input_tokens`,
  and `input_tokens` split the input three ways, and the bill follows the split.
- **Cache diagnostics**: opt in per request, thread `previous_message_id`
  through the conversation, and read `cache_miss_reason.type`.
- **Prefix order and breakpoints**: tools, then system, then messages, and a
  change anywhere invalidates everything after it. Writes happen only at a
  breakpoint, so a varying last block needs an explicit breakpoint before it.
- **Providers**: the same fix on the Claude API and on Bedrock, with a
  different client, model ID, and feature set (built, not yet run on
  Bedrock).

## Repo layout

```
starter.py        ← the only file you edit
reference.py      ← finished versions
app.py            ← the weekend readout
support.py        ← Wren: handbook loader, Friday's request, the replay loop
divergence.py     ← first_divergence(): what changed between two requests, on any provider
offline.py        ← simulated Claude API client for offline mode
clients.py        ← picks the client for config.PROVIDER
config.py         ← provider, model IDs, region, prices, the tests' bar

data/             ← handbook.md (the system prompt), weekend.json (the traffic), friday.diff (the deploy), make_traffic.py
tests/            ← test_offline.py (your code), test_simulator.py (the offline client), test_live.py (LAB_LIVE=1), truth.py (the tests' meter)
scripts/setup.sh  ← one-command setup
```

## License

`[confirm: license]`
