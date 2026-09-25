"""
Writes data/weekend.json: the support chat traffic for the weekend of
09/26/26 to 09/27/26 that the lab replays. Seeded, so the file is the same
every run. The committed JSON is what the lab uses; rerun this only if you
change it.

    .venv/bin/python data/make_traffic.py
"""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

PT = timezone(timedelta(hours=-7))  # Pacific daylight time

# Each topic is a customer's messages in order; a conversation uses the first 1 to 4.
TOPICS = {
    "where_is_order": [
        "Hi, where is my order {order}? Tracking still says label created.",
        "It's been three days though. Is that normal?",
        "Can someone call me about it today?",
        "OK, I'll watch for the email then. Thanks.",
    ],
    "return_boots": [
        "Can I return Switchback boots I wore on one hike? They give me blisters.",
        "What if I'm in Trail Club?",
        "How do I get a return label?",
        "How long until the refund shows up?",
    ],
    "exchange_size": [
        "I need to swap my Traverse 55 for a size L. Order {order}.",
        "Is the exchange free?",
        "Will the new one ship right away?",
        "Great, thanks for the help!",
    ],
    "warranty_zipper": [
        "The door zipper on my Ridgeline 2 tent broke after two seasons. Is that covered?",
        "I bought it a couple of years ago and don't have the order number.",
        "Where do I send the photos?",
        "How long do repairs usually take?",
    ],
    "change_order": [
        "I placed order {order} about 20 minutes ago. Can I still change it?",
        "Can I switch the shipping to expedited?",
        "How much extra is that?",
        "Perfect, please do it.",
    ],
    "price_drop": [
        "The Cirrus down jacket I bought last week is $50 cheaper now. Can I get the difference back?",
        "It's order {order}.",
        "When will I see the refund?",
    ],
    "recall": [
        "Is my Summit carabiner part of the recall? The lot number is S23-{lot}.",
        "How do I get the replacement?",
        "Should I stop using the others from the same pack too?",
    ],
    "kayak_freight": [
        "How does shipping work for the Tidewater 12 kayak?",
        "Do I have to be home for the delivery?",
        "Can I call someone to set up the delivery appointment today?",
        "What about picking it up at the Bend store instead?",
    ],
    "rental": [
        "Do you rent bear canisters?",
        "How much would it be for five days?",
        "What happens if I bring it back a day late?",
    ],
    "missing_package": [
        "My package for order {order} says delivered but it isn't here.",
        "I already checked with the neighbors and around the house.",
        "Can someone call me about this?",
        "OK, thank you.",
    ],
    "gift_card": [
        "I bought a digital gift card for my brother but he never got the email.",
        "It was $100, and I think I typed his address wrong.",
        "Can you send it to a different email instead?",
    ],
    "canada": [
        "Do you ship to Canada?",
        "Who pays the duties?",
        "How long does it take to get to Vancouver?",
    ],
}

# Mean minutes between new conversations, by hour of day. Busy midday, quiet edges.
MEAN_GAP = {8: 9, 9: 7, 10: 4, 11: 3, 12: 3, 13: 3, 14: 4, 15: 4, 16: 6, 17: 8, 18: 12, 19: 15}
DAYS = [  # (date, open hour, close hour)
    (datetime(2026, 9, 26, tzinfo=PT), 8, 20),
    (datetime(2026, 9, 27, tzinfo=PT), 9, 18),
]


def main():
    rng = random.Random(926)
    conversations = []
    for day, open_hour, close_hour in DAYS:
        t = day.replace(hour=open_hour)
        close = day.replace(hour=close_hour)
        while True:
            t += timedelta(seconds=rng.expovariate(1 / (MEAN_GAP[t.hour] * 60)))
            if t >= close:
                break
            topic = rng.choice(sorted(TOPICS))
            n_turns = min(len(TOPICS[topic]), rng.choices([1, 2, 3, 4], weights=[15, 30, 30, 25])[0])
            fill = {"order": f"KO-{rng.randint(10000, 99999)}", "lot": rng.randint(100, 300)}
            at, turns = t, []
            for text in TOPICS[topic][:n_turns]:
                turns.append({"at": at.isoformat(timespec="seconds"), "text": text.format(**fill)})
                at += timedelta(seconds=rng.randint(45, 150))
            conversations.append({"id": f"c{len(conversations) + 1:03d}", "topic": topic, "turns": turns})

    out = {"weekend": "2026-09-26 to 2026-09-27", "timezone": "Pacific (UTC-07:00)",
           "conversations": conversations}
    path = Path(__file__).parent / "weekend.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    n_turns = sum(len(c["turns"]) for c in conversations)
    print(f"wrote {path.name}: {len(conversations)} conversations, {n_turns} requests")


if __name__ == "__main__":
    main()
