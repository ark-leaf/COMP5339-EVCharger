"""MQTT delivery boundaries without a broker. OpenAI Codex assisted these tests."""
import json
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from data_generator import data_generator_daemon as daemon
from repository.event.ev_charger_state_event import EVChargerStateEvent


class EventStream:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        for i in range(3):
            yield EVChargerStateEvent(
                run_id="run-1", event_id=f"price-{i}", type="price_update",
                ts=f"2026-09-15T0{i}:00:00+10:00", station_id="42",
                payload={"price_per_kwh": 0.3 + i / 10})

    def close(self):
        self.closed = True


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.times = []
        self.events = EventStream()
        self.client = Mock()
        self.reason = SimpleNamespace(is_failure=False)
        self.client.loop_start.side_effect = lambda: self.client.on_connect(
            self.client, None, None, self.reason, None)
        self.message = Mock(rc=0)
        self.message.is_published.return_value = True
        self.message.wait_for_publish.side_effect = lambda timeout: self.advance(.02)

        def send(*args, **kwargs):
            self.times.append(self.now)
            return self.message

        self.client.publish.side_effect = send
        paho, package, mqtt = (ModuleType(name) for name in
                               ("paho", "paho.mqtt", "paho.mqtt.client"))
        paho.mqtt, package.client = package, mqtt
        mqtt.Client = Mock(return_value=self.client)
        mqtt.CallbackAPIVersion = SimpleNamespace(VERSION2=2)
        mqtt.MQTT_ERR_SUCCESS, mqtt.error_string = 0, str
        modules = {module.__name__: module for module in (paho, package, mqtt)}
        for patcher in (patch.dict(sys.modules, modules), patch.object(
                daemon, "time", SimpleNamespace(monotonic=lambda: self.now, sleep=self.advance))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def advance(self, seconds):
        self.now += seconds

    def assert_closed(self):
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()
        self.assertTrue(self.events.closed)

    def test_serialized_qos1_delivery_is_spaced_and_acknowledged(self):
        self.assertEqual(daemon.publish_events(self.events), 3)
        for actual, expected in zip(self.times, [0.0, 0.12, 0.24]):
            self.assertAlmostEqual(actual, expected)
        for i, call in enumerate(self.client.publish.call_args_list):
            self.assertEqual(call.args[0], "evc/price_update/42")
            self.assertEqual(json.loads(call.args[1])["event_id"], f"price-{i}")
            self.assertEqual(call.kwargs, {"qos": 1, "retain": False})
        self.assertEqual(self.message.wait_for_publish.call_count, 3)
        self.assert_closed()

    def test_missing_ack_stops_stream_and_cleans_up(self):
        self.message.is_published.return_value = False
        with self.assertRaisesRegex(TimeoutError, "price-0"):
            daemon.publish_events(self.events)
        self.assertEqual(self.client.publish.call_count, 1)
        self.assert_closed()

    def test_connack_refusal_sends_nothing_and_cleans_up(self):
        self.reason.is_failure = True
        with self.assertRaisesRegex(ConnectionError, "connection rejected"):
            daemon.publish_events(self.events)
        self.client.publish.assert_not_called()
        self.assert_closed()


if __name__ == "__main__":
    unittest.main()
