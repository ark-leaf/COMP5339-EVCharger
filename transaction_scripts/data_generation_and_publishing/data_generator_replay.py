# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with replay-window preparation and state continuity checks.
"""Select a daytime window while preserving the original IDs and necessary context."""
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path

from event.ev_charger_state_event import EVENT_TYPE_ORDER
from transaction_scripts.data_generation_and_publishing.data_generator_config import NEM_TIME
from transaction_scripts.data_generation_and_publishing.data_generator_utils import generate_evc_state_update


def replay_events(output_dir, start=None, end=None, charger_ids=None):
    """Include latest prices and open-session starts/latest meters before the window.

    Context consists of original generated events, not invented snapshots. It is
    sufficient for current state and live curves, not full pre-window history.
    """
    selected = None if charger_ids is None else set(charger_ids)
    if (start is None) != (end is None):
        raise ValueError("Both replay window boundaries are required")
    if start is not None:
        start, end = (datetime.fromisoformat(t) if isinstance(t, str) else t for t in (start, end))
        start = start if start.tzinfo else start.replace(tzinfo=NEM_TIME)
        end = end if end.tzinfo else end.replace(tzinfo=NEM_TIME)
        settings = json.loads((Path(output_dir) / 'manifest.json').read_text())["settings"]
        first = datetime.fromisoformat(settings["start"]).replace(tzinfo=NEM_TIME)
        if not first <= start < end <= first + timedelta(days=settings["days"]):
            raise ValueError("Replay window must be within the generated period")
    prices, sessions = {}, {}
    context_sent = start is None

    def context():
        rows = list(prices.values()) + [e for pair in sessions.values() for e in pair if e is not None]
        return sorted(rows, key=lambda e: (e.ts, EVENT_TYPE_ORDER.index(e.type), e.charger_id, e.id))

    with closing(generate_evc_state_update(output_dir)) as events:
        for event in events:
            if selected is not None and event.charger_id not in selected:
                continue
            if start is not None and event.ts < start:
                key = (event.charger_id, event.session_id)
                if event.type == 'price_update':
                    prices[event.charger_id] = event
                elif event.type == 'session_start':
                    sessions[key] = [event, None]
                elif event.type == 'meter':
                    sessions[key][1] = event
                else:
                    sessions.pop(key)
                continue
            if not context_sent:
                yield from context()
                context_sent = True
            if end is not None and event.ts >= end:
                break
            yield event
        if not context_sent:
            yield from context()
