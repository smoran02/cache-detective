"""
usage_report.py: hit rate and dollars from logged usage, priced by your meter().

    .venv/bin/python app.py --log usage.jsonl     # logs your code's weekend, one usage per line
    .venv/bin/python usage_report.py usage.jsonl

To take it to your app: copy this file, paste your meter() over the import below,
set PRICES to your model's, and log each response as it comes back:

    log.write(json.dumps(response.usage.to_dict()) + "\n")
"""
import json
import sys

from anthropic.types import Usage

from starter import meter  # in your app, paste your meter() here instead

PRICES = {  # $ per token for your model and provider. These are Opus 5.5 on the Claude API.
    "input": 4.00 / 1_000_000, "cache_write_5m": 5.00 / 1_000_000, "cache_write_1h": 8.00 / 1_000_000,
    "cache_read": 0.20 / 1_000_000, "output": 20.00 / 1_000_000,
}


def report(path: str, prices: dict = PRICES) -> str:
    with open(path) as log:
        usages = [Usage(**json.loads(line)) for line in log if line.strip()]
    hit_rate, dollars = meter(usages, prices)
    return f"{len(usages)} requests: {hit_rate:.1%} of input read from the cache, ${dollars:.2f}"


if __name__ == "__main__":
    print(report(sys.argv[1] if len(sys.argv) > 1 else "usage.jsonl"))
