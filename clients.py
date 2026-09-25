"""
make_client() returns the client for config.PROVIDER. All three have
client.messages.create and client.beta.messages.create; the SDK takes cache
diagnostics on the beta method. Diagnostics itself is Claude API only (the
offline client simulates the Claude API), so on Bedrock the lab never asks.
"""
import anthropic

import config
from offline import OfflineClient


def make_client(provider: str = config.PROVIDER):
    if provider == "offline":
        return OfflineClient()
    if provider == "anthropic":
        # api_key defaults to the ANTHROPIC_API_KEY environment variable.
        # https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python
        return anthropic.Anthropic()
    if provider == "bedrock":
        # Opus 5.5 runs on Claude in Amazon Bedrock, which serves the Messages
        # API; its client is AnthropicBedrockMantle. (AnthropicBedrock is the
        # legacy InvokeModel client for Opus 4.6 and earlier.) Credentials come
        # from constructor args, then AWS_* env vars, then the AWS config chain.
        # The region comes from config.AWS_REGION.
        # https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock
        # Unconfirmed: no doc states the usage field names in Bedrock Messages API
        # responses. The lab reads the Claude API names (cache_read_input_tokens and
        # so on) and counts a missing value as 0. Check on the first live run.
        return anthropic.AnthropicBedrockMantle(aws_region=config.AWS_REGION)
    raise ValueError(f"PROVIDER must be offline, anthropic, or bedrock, not {provider!r}")


def has_diagnostics(provider: str = config.PROVIDER) -> bool:
    """Cache diagnostics is Claude API only; it isn't available on Bedrock.

    https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#limitations
    The offline client simulates the Claude API, so it has it too. On Bedrock
    the lab never sends a diagnostics object: whether Bedrock would reject it
    or ignore it is unconfirmed.
    """
    return provider in ("offline", "anthropic")
