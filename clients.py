"""
make_client() returns the client for config.PROVIDER. Both have
client.messages.create and client.beta.messages.create; the SDK takes cache
diagnostics on the beta method.
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
    raise ValueError(f"PROVIDER must be offline or anthropic, not {provider!r}")
