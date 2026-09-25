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
MODEL = MODELS[PROVIDER]

# Bedrock region. us-east-1 is one of the regions that serves Opus 5.5.
# https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock#regions
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Room for adaptive thinking plus a short support reply. Thinking tokens bill as output.
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
