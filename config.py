"""
Lab settings. Change the provider here (or set LAB_PROVIDER); nothing else in
the repo hardcodes a provider, model ID, region, or price.
"""
import os

# offline:   the simulated client in offline.py. No key, no network, no cost.
# anthropic: the Claude API. Needs ANTHROPIC_API_KEY.
# bedrock:   Claude in Amazon Bedrock. Needs AWS credentials and Bedrock model access.
PROVIDER = os.environ.get("LAB_PROVIDER", "offline")

# Model IDs per provider. Opus 5.5 on Bedrock has its own ID.
# https://platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5#availability
MODELS = {
    "offline": "claude-opus-5-5",
    "anthropic": "claude-opus-5-5",
    "bedrock": "anthropic.claude-opus-5-5",
}
if PROVIDER not in MODELS:
    raise ValueError(f"PROVIDER must be offline, anthropic, or bedrock, not {PROVIDER!r}")
MODEL = MODELS[PROVIDER]

# Bedrock region: AWS_REGION, then AWS_DEFAULT_REGION (the two the SDK reads),
# then us-east-1, one of the regions that serves Opus 5.5.
# https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock#regions
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

# Room for adaptive thinking plus a short support reply. Thinking tokens bill as output
# and count toward max_tokens: https://platform.claude.com/docs/en/build-with-claude/thinking
MAX_TOKENS = 2048

# Shortest prefix Opus 5.5 will cache. Shorter prefixes run uncached with no error.
# The offline client applies it. Other models have other minimums (1,024 to 4,096).
# https://platform.claude.com/docs/en/build-with-claude/prompt-caching#cache-limitations
MIN_CACHEABLE_TOKENS = 512

# Claude API list prices for Opus 5.5, in dollars per token ($/MTok divided by 1M).
# https://platform.claude.com/docs/en/about-claude/pricing
# Bedrock is billed by AWS at its own rates, so on Bedrock these are an estimate.
PRICES = {
    "input": 4.00 / 1_000_000,           # base input: tokens after the last breakpoint
    "cache_write_5m": 5.00 / 1_000_000,  # 1.25x base
    "cache_write_1h": 8.00 / 1_000_000,  # 2x base
    "cache_read": 0.20 / 1_000_000,      # 0.05x base on Opus 5.5 (most models: 0.1x)
    "output": 20.00 / 1_000_000,         # includes thinking tokens
}

# Live runs replay only the first few conversations of the weekend, back to back,
# to keep the bill small. Offline mode replays all of them on the traffic's own clock.
LIVE_CONVERSATIONS = 6

# The bar a fix must clear. tests/test_offline.py asserts it, and app.py prints
# "Case closed" only when your numbers clear it. Offline it's calibrated to the
# simulated weekend, where the reference gets a 90.8% hit rate and $0.0171 per
# conversation (README, "How offline mode works"). The bounds leave room for
# small differences, like how you word the time.
BAR = {
    "hit_rate": 0.88,                    # at least
    "dollars_per_conversation": 0.0190,  # at most
    # Friday's bill over yours, at least. Only the tests check it: on this traffic the
    # dollars bar implies it ($0.0539 / $0.0190 is 2.84).
    "friday_over_fixed": 2.8,
    "first_turns_reading": 0.75,         # share of first turns that read the cache, at least
    "follow_ups_past_handbook": 0.90,    # share of follow-up turns that read more than the handbook, at least
}
# Live runs are 6 conversations with real token counts, so tests/test_live.py
# and the live readout ask only for this hit rate and a lower bill than Friday's.
LIVE_HIT_RATE_AT_LEAST = 0.70
