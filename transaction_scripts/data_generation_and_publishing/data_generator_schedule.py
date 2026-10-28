# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the coverage-controlled simulation schedule.
"""Allocate a fixed session budget while retaining daily variation and port coverage."""
from collections import Counter
import random


def balanced_session_plan(stations, config):
    """Focus ports run daily; other ports run once; extras go to focus ports."""
    if any(st["model_type"] != "DC" for st in stations):
        raise ValueError("The balanced schedule currently supports DC stations only")
    rng = random.Random(config.seed)
    focus_ids = set(config.focus_charger_ids)
    focus, other = [], []
    for st in stations:
        ports = [(st["charger_id"], c) for c in range(1, st["connectors"] + 1)]
        (focus if st["charger_id"] in focus_ids else other).extend(ports)
    if not focus:
        raise ValueError("No focus DC stations matched the selected augmented region")
    minimum = len(focus) * config.days + len(other)
    daily_extra_capacity = 2 * len(focus)
    maximum = minimum + daily_extra_capacity * config.days
    if not minimum <= config.target_sessions <= maximum:
        raise ValueError(f"target_sessions must be between {minimum} and {maximum} "
                         "for this coverage plan (one to three sessions per focus port/day)")
    plan = Counter({(cid, port, day): 1 for cid, port in focus for day in range(config.days)})
    rng.shuffle(other)
    for index, (cid, port) in enumerate(other):
        plan[cid, port, index % config.days] = 1
    # Spread extras over days with modest variation, never exceeding port capacity.
    extras = config.target_sessions - minimum
    weights = [rng.uniform(.85, 1.15) for _ in range(config.days)]
    allocation = [min(daily_extra_capacity, int(extras * w / sum(weights))) for w in weights]
    remaining = extras - sum(allocation)
    while remaining:
        eligible = [day for day, count in enumerate(allocation) if count < daily_extra_capacity]
        day = rng.choices(eligible, weights=[weights[d] for d in eligible])[0]
        allocation[day] += 1
        remaining -= 1
    for day, count in enumerate(allocation):
        while count:
            batch = min(len(focus), count)
            for cid, port in rng.sample(focus, batch):
                plan[cid, port, day] += 1
            count -= batch
    return plan
