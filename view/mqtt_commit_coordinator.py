"""Bounded retry state machine joining independent MQTT consumers."""
from __future__ import annotations
from collections import OrderedDict
import logging
import threading
import time
logger = logging.getLogger(__name__)


class MqttCommitCoordinator:
    def __init__(self, notify=None, *, max_pending=10_000, ttl_seconds=300,
                 max_notify_attempts=3, retry_delay=.05, on_gap=None, clock=time.monotonic):
        self._notify, self._gap, self._clock = notify, on_gap, clock
        self._max, self._ttl, self._limit, self._delay = max_pending, ttl_seconds, max_notify_attempts, retry_delay
        self._lock, self._closed, self._wake = threading.Lock(), threading.Event(), threading.Event()
        # id -> [event, dashboard_seen, committed, attempts, next_retry, created, status]
        self._states, self._notified, self._inflight = OrderedDict(), OrderedDict(), set()
        self.gaps = self.expired = self.rejected = 0
        self._worker = threading.Thread(target=self._run, name="mqtt-dashboard-retry", daemon=True)
        self._worker.start()

    def set_notifier(self, notify):
        with self._lock: self._notify = notify
    def dashboard_received(self, event): return self._record(event, True, False)
    def committed(self, event): return self._record(event, False, True)
    def rejected_event(self, event):
        with self._lock: self._states.pop(event.id, None); self.rejected += 1

    def _record(self, event, dashboard, committed):
        with self._lock:
            self._prune_locked()
            if event.id in self._notified: return False
            state = self._states.setdefault(event.id, [event, False, False, 0, self._clock(), self._clock(), "pending"])
            if committed: state[0] = event
            state[1] |= dashboard; state[2] |= committed
            if state[1] and state[2] and state[6] == "pending": state[6] = "retry"
        self._wake.set()
        return self.retry_pending()

    def retry_pending(self):
        delivered = False
        while True:
            with self._lock:
                self._prune_locked()
                now = self._clock()
                choice = next(((key, s) for key, s in self._states.items()
                               if s[1] and s[2] and s[6] == "retry" and s[4] <= now and key not in self._inflight), None)
                if choice is None: return delivered
                key, state = choice; self._inflight.add(key); state[6] = "in-flight"
            delivered = self._attempt(key, state[0]) or delivered

    def _attempt(self, key, event):
        try:
            if self._notify: self._notify(event)
        except Exception as exc:
            report = None
            with self._lock:
                self._inflight.discard(key); state = self._states.get(key)
                if state:
                    state[3] += 1
                    if state[3] >= self._limit:
                        state[6] = "permanent-failure"
                        # The terminal failure has one authoritative recovery
                        # report. Remove it so TTL/capacity cannot report it again.
                        self._states.pop(key, None)
                        report = (event, "notification retry limit reached; snapshot resync required")
                    else:
                        state[6] = "retry"; state[4] = self._clock() + self._delay * (2 ** (state[3] - 1))
            if report: self._report(*report)
            else: logger.warning("Dashboard notification failed for %s: %s", key, exc)
            return False
        with self._lock:
            self._inflight.discard(key); self._states.pop(key, None); self._notified[key] = self._clock()
            self._prune_locked()
        return True

    def _run(self):
        while not self._closed.wait(self._delay):
            self.retry_pending()  # includes idle TTL/overflow maintenance
            self._flush_reports()

    def _report(self, event, reason):
        self.gaps += 1
        logger.error("MQTT coordinator gap: %s", reason)
        if self._gap:
            try: self._gap(event, reason)
            except Exception as exc: logger.warning("Gap reporter failed: %s", exc)

    def _prune_locked(self):
        cutoff = self._clock() - self._ttl
        while self._notified and (len(self._notified) > self._max or next(iter(self._notified.values())) < cutoff):
            self._notified.popitem(last=False)
        expired = []
        for key, state in list(self._states.items()):
            if key not in self._inflight and (len(self._states) > self._max or state[5] < cutoff):
                self._states.pop(key); self.expired += 1
                expired.append((state[0] if state[2] else None, "committed event overflow/TTL; snapshot resync required" if state[2] else "dashboard-only event expired before commit"))
        # Reporters are invoked by the worker/caller after lock release.
        self._expired_reports = getattr(self, "_expired_reports", []) + expired

    def _flush_reports(self):
        with self._lock:
            reports, self._expired_reports = getattr(self, "_expired_reports", []), []
        for item in reports: self._report(*item)

    @property
    def pending_count(self):
        with self._lock: self._prune_locked(); count = len(self._states)
        self._flush_reports(); return count

    def close(self):
        self._closed.set(); self._wake.set()
        if self._worker.is_alive(): self._worker.join(timeout=2)
        with self._lock: self._states.clear(); self._notified.clear(); self._inflight.clear()
