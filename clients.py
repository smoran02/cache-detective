"""
make_client() returns the client for config.PROVIDER. All three have
client.messages.create; the Claude API and offline clients also have
client.beta.messages.create, which is where the SDK takes cache diagnostics.
"""
import anthropic

import config
from offline import OfflineClient


def make_client(provider: str = config.PROVIDER):
    if provider == "offline":
        return OfflineClient()
    if provider == "anthropic":
        return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    if provider == "bedrock":
        # Opus 5.5 runs on Claude in Amazon Bedrock, which serves the Messages
        # API; its client is AnthropicBedrockMantle. (AnthropicBedrock is the
        # legacy InvokeModel client for Opus 4.6 and earlier.) Credentials come
        # from constructor args, then AWS_* env vars, then the AWS config chain.
        # https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock
        return anthropic.AnthropicBedrockMantle(aws_region=config.AWS_REGION)
    raise ValueError(f"PROVIDER must be offline, anthropic, or bedrock, not {provider!r}")


def has_diagnostics(provider: str = config.PROVIDER) -> bool:
    """Cache diagnostics is Claude API only; it isn't available on Bedrock.

    https://platform.claude.com/docs/en/build-with-claude/cache-diagnostics#limitations
    The offline client simulates the Claude API, so it has it too.
    """
    return provider in ("offline", "anthropic")
