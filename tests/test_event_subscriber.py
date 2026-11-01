"""YMqttEventSubscriber decodes into the YEvent subclass chosen by its generic parameter."""
import json
import socket
import threading
import unittest
from dataclasses import asdict, dataclass
from unittest.mock import patch

from event.ev_charger_state_event import EVChargerStateEvent
from event.y_event import YEvent
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber, subscribed
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository


@dataclass
class NoteEvent(YEvent):
    """A minimal non-charger event, to show the subscriber is not tied to EVChargerStateEvent."""

    def to_json(self) -> str:
        return json.dumps(dict(asdict(self), ts=self.ts.isoformat()))


def charger_events():
    return [EVChargerStateEvent(run_id="run-1", id=f"price-{i}", type="price_update",
                                ts=f"2026-09-15T0{i}:00:00+10:00", object_id="42",
                                payload={"price_per_kwh": 0.3 + i / 10}) for i in range(3)]


def note_events():
    return [NoteEvent(run_id="run-1", id=f"note-{i}", type="note",
                      ts=f"2026-09-15T0{i}:00:00+10:00", object_id="7",
                      payload={"text": f"hello {i}"}) for i in range(2)]


class EventSubscriberTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.received, self.done = [], threading.Event()

    def handle(self, event):
        self.received.append(event)
        if len(self.received) == self.expected:
            self.done.set()

    def deliver(self, subscriber, events):
        """Publish events through an inline broker and return what the subscriber handled."""
        self.expected = len(events)
        with YSimpleMqttRepository(host="127.0.0.1", port=self.port, interval=0.1,
                                   is_inline_broker=True) as publisher:
            subscriber.start()
            self.assertTrue(subscriber.ready.wait(10))
            self.assertIsNone(subscriber.error)
            for event in events:
                publisher.send_event(event)
            self.assertTrue(self.done.wait(5), f"handled {len(self.received)}/{len(events)}")
            subscriber.stopping.set()
            subscriber.join(10)
        self.assertIsNone(subscriber.error)
        self.assertEqual(subscriber.received, len(events))
        return self.received

    def test_generic_parameter_selects_the_event_class(self):
        sent = charger_events()
        subscriber = YMqttEventSubscriber[EVChargerStateEvent](
            "charger", self.handle, "127.0.0.1", self.port)
        received = self.deliver(subscriber, sent)
        self.assertIs(subscriber.event_type, EVChargerStateEvent)
        self.assertTrue(all(type(event) is EVChargerStateEvent for event in received))
        self.assertEqual([e.to_dict() for e in received], [e.to_dict() for e in sent])

    def test_any_yevent_subclass_can_be_given_explicitly(self):
        sent = note_events()
        subscriber = YMqttEventSubscriber("notes", self.handle, "127.0.0.1", self.port,
                                          event_type=NoteEvent)
        received = self.deliver(subscriber, sent)
        self.assertTrue(all(type(event) is NoteEvent for event in received))
        self.assertEqual(received, sent)

    def test_missing_abstract_or_foreign_type_fails_before_the_thread_starts(self):
        for subscriber in (YMqttEventSubscriber("none", print, "127.0.0.1", self.port),
                           YMqttEventSubscriber[YEvent]("abstract", print, "127.0.0.1", self.port),
                           YMqttEventSubscriber("foreign", print, "127.0.0.1", self.port,
                                                event_type=dict)):
            with self.subTest(subscriber.name), self.assertRaisesRegex(TypeError, "concrete YEvent"):
                subscriber.start()
            self.assertFalse(subscriber.is_alive())

    def test_from_json_is_inherited_by_every_subclass(self):
        note = note_events()[0]
        self.assertEqual(NoteEvent.from_json(note.to_json()), note)
        with self.assertRaises(TypeError):
            YEvent.from_json(note.to_json())  # YEvent itself is abstract


class Ready(threading.Event):
    """A subscriber's ready flag that also records when it is awaited."""
    def __init__(self, name, timeline):
        super().__init__()
        self.name, self.timeline = name, timeline

    def wait(self, timeout=None):
        self.timeline.append(("wait", self.name))
        return super().wait(timeout)


class FakeSubscriber:
    """Records what subscribed() does to it; it subscribes at once unless given an error."""
    def __init__(self, name, timeline, start_error=None):
        self.name, self.timeline, self.start_error = name, timeline, start_error
        self.ready, self.stopping, self.error = Ready(name, timeline), threading.Event(), None

    def start(self):
        self.timeline.append(("start", self.name))
        self.error = self.start_error
        self.ready.set()

    def join(self, timeout=None):
        self.timeline.append(("join", self.name))


class SubscribedTests(unittest.TestCase):
    def test_subscribers_start_together_and_stop_together(self):
        timeline = []
        storage, dashboard = FakeSubscriber("storage", timeline), FakeSubscriber("dashboard", timeline)
        with subscribed(storage, dashboard):
            timeline.append(("body", None))
        self.assertEqual(timeline, [("start", "storage"), ("start", "dashboard"), ("wait", "storage"),
                                    ("wait", "dashboard"), ("body", None), ("join", "storage"), ("join", "dashboard")])
        self.assertTrue(storage.stopping.is_set() and dashboard.stopping.is_set())

    def test_one_failed_subscription_stops_every_subscriber(self):
        timeline = []
        storage = FakeSubscriber("storage", timeline, start_error=ConnectionError("broker refused"))
        dashboard = FakeSubscriber("dashboard", timeline)
        with self.assertRaisesRegex(RuntimeError, "storage did not subscribe"):
            with subscribed(storage, dashboard):
                self.fail("the body must not run")
        self.assertTrue(storage.stopping.is_set() and dashboard.stopping.is_set())

    def test_a_subscriber_that_fails_while_running_is_reported_on_exit(self):
        storage = FakeSubscriber("storage", [])
        with self.assertRaisesRegex(RuntimeError, "storage failed"):
            with subscribed(storage):
                storage.error = ValueError("undecodable payload")

    def test_an_error_in_the_body_is_not_replaced(self):
        storage = FakeSubscriber("storage", [])
        with self.assertRaisesRegex(KeyError, "body"):
            with subscribed(storage):
                storage.error = ValueError("also failed")
                raise KeyError("body")
        self.assertTrue(storage.stopping.is_set())


if __name__ == "__main__":
    unittest.main()
