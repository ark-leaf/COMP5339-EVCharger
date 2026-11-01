"""Task B as a plain transaction script: store each event the database-update subscriber receives.

Call prepare_event_storage() once before events arrive. sub_database_update() is the subscriber's
callback; it stores each event with save_event() on the subscriber's thread, the process's only writer.
"""
import copy
import sys
import threading
from collections.abc import Callable

from entity.ev_charger_state import EVChargerState
from repository.evc_event_dao import EVChargerEventDAO
from event.ev_charger_state_event import EVChargerStateEvent

_dao = EVChargerEventDAO()
# The latest validated state of each charger in each run, by (run_id, charger_id).
_states: dict[tuple[str, int], EVChargerState] = {}


def prepare_event_storage() -> None:
    """Create the event tables if none exist yet (stored events are kept) and start with no cached states."""
    _dao.ensure_tables()
    _states.clear()


def sub_database_update(event: EVChargerStateEvent, on_failure: Callable[[], None] | None = None) -> None:
    """The database-update subscriber's callback: store the event and log the outcome.

    If storing fails, on_failure is called and the error is raised, which ends the subscriber.
    """
    where = event.charger_id if event.connector_id is None else f"{event.charger_id}/{event.connector_id}"
    try:
        stored = save_event(event)
    except Exception as exc:
        print(f"FATAL persistence failure: {event.type} event {event.id} (run {event.run_id}, charger {where}) "
              f"was not stored: {exc!r}. Storage has stopped.", file=sys.stderr)
        if on_failure is not None:
            on_failure()
        raise
    outcome = "stored   " if stored else "duplicate"
    print(f"[{threading.current_thread().name}] {outcome} "
          f"{event.ts:%Y-%m-%d %H:%M} UTC {event.type:<13} charger {where:<6} {event.payload}")


def save_event(event: EVChargerStateEvent) -> bool:
    """Store one event with its charger's new state; False if it was already stored (a replay or redelivery).

    An invalid state transition, or a charger that is not in Assignment 1, raises before anything is stored.
    """
    if _dao.event_exists(event.id):
        return False
    key = (event.run_id, event.charger_id)
    # First event for this charger, e.g. after a restart
    if key not in _states:
        _states[key] = _rebuild_state(*key)
    new_state = copy.deepcopy(_states[key])
    # An invalid transition raises before anything is written
    new_state.apply(event)
    # The event and the latest state commit together.
    with _dao.transaction():
        # An unknown Assignment 1 charger raises here (FK).
        if not _dao.insert_event(event):
            return False
        _dao.update_latest_state(event, new_state)
    _states[key] = new_state
    return True


def _rebuild_state(run_id: str, charger_id: int) -> EVChargerState:
    """Replay this charger's stored events in the order they were published."""
    state = EVChargerState(charger_id, run_id)
    for stored_event in _dao.list_events(run_id, charger_id):
        state.apply(stored_event)
    return state
