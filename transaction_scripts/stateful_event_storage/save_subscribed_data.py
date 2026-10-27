import copy

from repository.entity.ev_charger_state import EVChargerState
from repository.entity.evc_event_dao import EVChargerEventDAO
from repository.event.ev_charger_state_event import EVChargerStateEvent


class EVChargerEventStore:
    """Deduplicate, validate and save EVChargerStateEvents; use from one writer thread.

    The database opens with the first event, not here: main_ass_2's generator first reads
    the Assignment 1 stations read-only, and DuckDB refuses read-only and read-write
    connections to one file in the same process.
    """

    def __init__(self, dao: EVChargerEventDAO | None = None):
        self.dao = EVChargerEventDAO() if dao is None else dao
        self.stored = self.duplicates = 0
        self.run_ids: set[str] = set()
        self._states: dict[tuple[str, int], EVChargerState] = {}  # by (run_id, charger_id)
        self._tables_ready = False

    def save(self, event: EVChargerStateEvent) -> bool:
        """Store one event. Returns False if it was already stored (a replay or redelivery)."""
        if not self._tables_ready:
            self.dao.ensure_tables()
            self._tables_ready = True
        self.run_ids.add(event.run_id)
        if self.dao.event_exists(event.id):
            self.duplicates += 1
            return False
        key = (event.run_id, event.charger_id)
        # First event for this charger, e.g. after a restart
        if key not in self._states:
            self._states[key] = self._rebuild_state(*key)
        new_state = copy.deepcopy(self._states[key])
        # An invalid transition raises before anything is written
        new_state.apply(event)
        # The event and the latest state commit together.
        with self.dao.transaction():
            # An unknown Assignment 1 charger raises here (FK).
            if not self.dao.insert_event(event):
                self.duplicates += 1
                return False
            self.dao.update_latest_state(event, new_state)
        self._states[key] = new_state
        self.stored += 1
        return True

    def _rebuild_state(self, run_id: str, charger_id: int) -> EVChargerState:
        """Replay this charger's stored events in the order they were published."""
        state = EVChargerState(charger_id, run_id)
        for stored_event in self.dao.list_events(run_id, charger_id):
            state.apply(stored_event)
        return state
