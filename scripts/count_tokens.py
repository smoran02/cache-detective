"""
Count the lab's fixed text with the Claude API's token counting endpoint and
write data/token_counts.json, which offline.py reads so offline mode uses real
token counts instead of estimating them.

Token counting is free (it has its own rate limit, separate from messages), but
it needs ANTHROPIC_API_KEY. Run it again only when handbook.md, weekend.json, or
offline.REPLIES changes:

    .venv/bin/python scripts/count_tokens.py

https://platform.claude.com/docs/en/build-with-claude/token-counting
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic

import config
from offline import REPLIES
from support import DATA, HANDBOOK, WEEKEND

MODEL = config.MODELS["anthropic"]
# Each text is counted after this anchor, and the anchor's own count is subtracted.
# That removes the request's fixed overhead and lets a whitespace-only line be counted.
ANCHOR = "Count:\n"


def main():
    client = anthropic.Anthropic()

    def count(text: str) -> int:
        return client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": ANCHOR + text}]
        ).input_tokens

    # Handbook lines keep their newline, as they appear in the system prompt. Customer
    # messages and replies are counted whole: each is one block, or one line of one.
    texts = sorted(
        set(HANDBOOK.splitlines(keepends=True))
        | {t["text"] for c in WEEKEND for t in c["turns"]}
        | set(REPLIES)
    )
    base = count("")
    counts = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (text, n) in enumerate(zip(texts, pool.map(count, texts)), 1):
            counts[text] = max(n - base, 0)
            print(f"\r  Counted {i} of {len(texts)} texts", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    whole = count(HANDBOOK) - base
    by_line = sum(counts[line] for line in HANDBOOK.splitlines(keepends=True))
    out = {
        "model": MODEL,
        "counted": date.today().strftime("%m/%d/%y"),
        "handbook": {"whole": whole, "sum_of_lines": by_line},
        "tokens": counts,
    }
    (DATA / "token_counts.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote data/token_counts.json: {len(counts)} texts on {MODEL}.")
    print(f"Handbook: {whole:,} tokens counted whole, {by_line:,} as the sum of its lines.")


if __name__ == "__main__":
    main()
