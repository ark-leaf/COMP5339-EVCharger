"""MQTT delivery boundaries, mocked and through the inline broker. OpenAI Codex assisted these tests."""
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import paho.mqtt.client as paho_mqtt

from config import MQTT_QOS
from transaction_scripts.data_generation_and_publishing import data_generator_daemon as daemon
from data_utils import y_mqtt_simple_repo
from event.ev_charger_state_event import EVChargerStateEvent
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository


class EventStream:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        for i in range(3):
            yield EVChargerStateEvent(
                run_id="run-1", id=f"price-{i}", type="price_update",
                ts=f"2026-09-15T0{i}:00:00+10:00", object_id="42",
                payload={"price_per_kwh": 0.3 + i / 10})

    def close(self):
        self.closed = True


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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
        mqtt = SimpleNamespace(Client=Mock(return_value=self.client),
                               CallbackAPIVersion=SimpleNamespace(VERSION2=2),
                               MQTT_ERR_SUCCESS=0, error_string=str)
        for patcher in (patch.object(y_mqtt_simple_repo, "mqtt", mqtt),
                        patch.object(y_mqtt_simple_repo, "time", SimpleNamespace(
                            monotonic=lambda: self.now, sleep=self.advance)),
                        patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def advance(self, seconds):
        self.now += seconds

    def assert_closed(self):
        self.client.disconnect.assert_called_once()
        self.client.loop_stop.assert_called_once()
        self.assertTrue(self.events.closed)

    def test_serialized_delivery_uses_the_configured_qos_and_is_acknowledged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published_events.json"
            self.assertEqual(daemon.publish_events(self.events, published_path=path), 3)
            recorded = json.loads(path.read_text())
        self.assertEqual(recorded, [json.loads(call.args[1]) for call in self.client.publish.call_args_list])
        for actual, expected in zip(self.times, [0.0, 1.02, 2.04]):
            self.assertAlmostEqual(actual, expected)
        for i, call in enumerate(self.client.publish.call_args_list):
            self.assertEqual(call.args[0], "evc/price_update/42")
            self.assertEqual(json.loads(call.args[1])["id"], f"price-{i}")
            self.assertEqual(call.kwargs, {"qos": MQTT_QOS, "retain": False})
        self.assertEqual(self.message.wait_for_publish.call_count, 3)
        self.assert_closed()

    def test_missing_ack_stops_stream_and_cleans_up(self):
        self.message.is_published.return_value = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published_events.json"
            with self.assertRaisesRegex(TimeoutError, "price-0"):
                daemon.publish_events(self.events, published_path=path)
            self.assertEqual(json.loads(path.read_text()), [])
        self.assertEqual(self.client.publish.call_count, 1)
        self.assert_closed()

    def test_published_json_keeps_only_confirmed_events_after_failure(self):
        self.message.is_published.side_effect = [True, False]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published_events.json"
            with self.assertRaisesRegex(TimeoutError, "price-1"):
                daemon.publish_events(self.events, published_path=path)
            self.assertEqual(json.loads(path.read_text()),
                             [json.loads(self.client.publish.call_args_list[0].args[1])])
        self.assertEqual(self.client.publish.call_count, 2)
        self.assert_closed()

    def test_publisher_uses_shared_settings(self):
        settings = dict(daemon.mqtt_config(), host="shared-broker", port=1884,
                        topic_root="shared/evc", keepalive=45,
                        username="test-user", password="test-password",
                        publish_interval_seconds=0.2)
        with patch.object(y_mqtt_simple_repo, "mqtt_config", return_value=settings):
            self.assertEqual(daemon.publish_events(self.events), 3)
        self.client.connect.assert_called_once_with("shared-broker", 1884, keepalive=45)
        self.client.username_pw_set.assert_called_once_with("test-user", "test-password")
        self.assertEqual(self.client.publish.call_args.args[0], "shared/evc/price_update/42")
        self.assertAlmostEqual(self.times[1] - self.times[0], 0.22)
        self.assert_closed()

    def test_explicit_arguments_override_shared_settings(self):
        settings = dict(daemon.mqtt_config(), host="shared-broker", port=1884,
                        topic_root="shared/evc", publish_interval_seconds=0.2)
        with patch.object(y_mqtt_simple_repo, "mqtt_config", return_value=settings):
            daemon.publish_events(self.events, host="cli-broker", port=1885,
                                  topic_prefix="cli/evc", interval=0.1)
        self.client.connect.assert_called_once_with("cli-broker", 1885, keepalive=60)
        self.assertEqual(self.client.publish.call_args.args[0], "cli/evc/price_update/42")
        self.assertAlmostEqual(self.times[1] - self.times[0], 0.12)
        self.assert_closed()

    def test_cli_uses_shared_defaults_when_options_are_omitted(self):
        settings = dict(daemon.mqtt_config(), host="shared-broker", port=1884,
                        topic_root="shared/evc", publish_interval_seconds=0.2)
        with patch.object(daemon, "mqtt_config", return_value=settings), \
                patch.object(daemon, "replay_events", return_value=self.events), \
                patch.object(daemon, "write_events_json", return_value=3) as export, \
                patch.object(daemon, "publish_events", return_value=3) as publish:
            daemon.main(["--replay", "--publish"])
            daemon.main(["--replay", "--publish", "--inline-broker", "--startup-wait", "2"])
        self.assertEqual(publish.call_args_list[0].kwargs, dict(
            host="shared-broker", port=1884, topic_prefix="shared/evc", interval=0.2,
            inline_broker=False, startup_wait=0.0,
            published_path=daemon.GenerationConfig().output_dir / "published_events.json"))
        self.assertEqual(export.call_count, 2)
        self.assertEqual(export.call_args.args[1], daemon.GenerationConfig().output_dir / "prepared_events.json")
        self.assertTrue(publish.call_args_list[1].kwargs["inline_broker"])
        self.assertEqual(publish.call_args_list[1].kwargs["startup_wait"], 2.0)

    def test_cli_reads_stations_through_the_shared_connection_only_when_asked(self):
        for shared_connection in (False, True):
            with self.subTest(shared_connection=shared_connection), \
                    patch.object(daemon, "DuckDBRepository") as private, \
                    patch.object(daemon, "SharedDuckDBRepository") as shared, \
                    patch.object(daemon, "EVChargerInfoDAO") as dao, \
                    patch.object(daemon, "generate_dataset", return_value={}):
                dao.return_value.list_generation_chargers.return_value = []
                daemon.main([], shared_connection=shared_connection)
                used, unused = (shared, private) if shared_connection else (private, shared)
                used.assert_called_once()
                unused.assert_not_called()

    def test_connack_refusal_sends_nothing_and_cleans_up(self):
        self.reason.is_failure = True
        with self.assertRaisesRegex(ConnectionError, "connection rejected"):
            daemon.publish_events(self.events)
        self.client.publish.assert_not_called()
        self.assert_closed()

    def test_invalid_arguments_are_rejected_before_connecting(self):
        for kwargs in (dict(interval=0.05), dict(topic_prefix="evc/#"), dict(port=0)):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                daemon.publish_events(self.events, **kwargs)
        self.client.connect.assert_not_called()


class InlineBrokerTests(unittest.TestCase):
    """Real sockets on 127.0.0.1 only; no external broker is needed."""

    def setUp(self):
        patcher = patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.port = free_port()

    def assert_port_released(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", self.port))

    def test_subscriber_receives_events_through_inline_broker(self):
        subscribed, finished, received = threading.Event(), threading.Event(), []

        def on_message(client, userdata, message):
            received.append((message.topic, EVChargerStateEvent.from_json(message.payload)))
            if len(received) == 3:
                finished.set()

        with YSimpleMqttRepository(host="127.0.0.1", port=self.port, interval=0.1,
                                   is_inline_broker=True) as repo:
            subscriber = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
            subscriber.on_connect = lambda c, u, f, rc, p: c.subscribe("evc/#", qos=MQTT_QOS)
            subscriber.on_subscribe = lambda c, u, mid, rcs, p: subscribed.set()
            subscriber.on_message = on_message
            subscriber.connect("127.0.0.1", self.port)
            subscriber.loop_start()
            try:
                self.assertTrue(subscribed.wait(5), "subscription was not acknowledged")
                expected = list(EventStream())
                for event in expected:
                    repo.send_event(event)
                self.assertTrue(finished.wait(5), f"received {len(received)}/3 events")
            finally:
                subscriber.disconnect()
                subscriber.loop_stop()
        self.assertEqual([topic for topic, _ in received], ["evc/price_update/42"] * 3)
        self.assertEqual([e.to_dict() for _, e in received], [e.to_dict() for e in expected])
        self.assert_port_released()

    def test_repository_subscribe_receives_published_events(self):
        received, finished = [], threading.Event()

        def on_message(topic, payload):
            received.append((topic, EVChargerStateEvent.from_json(payload)))
            if len(received) == 3:
                finished.set()

        with YSimpleMqttRepository(host="127.0.0.1", port=self.port, interval=0.1,
                                   is_inline_broker=True) as publisher, \
                YSimpleMqttRepository(host="127.0.0.1", port=self.port,
                                      is_inline_broker=False) as subscriber:
            subscriber.subscribe(on_message)
            expected = list(EventStream())
            for event in expected:
                publisher.send_event(event)
            self.assertTrue(finished.wait(5), f"received {len(received)}/3 events")
            self.assertEqual(subscriber.msg_count_received, 3)
        self.assertEqual([topic for topic, _ in received], ["evc/price_update/42"] * 3)
        self.assertEqual([e.to_dict() for _, e in received], [e.to_dict() for e in expected])
        self.assert_port_released()

    def test_daemon_publishes_through_inline_broker_and_stops_it(self):
        events = EventStream()
        count = daemon.publish_events(events, host="127.0.0.1", port=self.port,
                                      interval=0.1, inline_broker=True)
        self.assertEqual(count, 3)
        self.assertTrue(events.closed)
        self.assert_port_released()

    def test_port_in_use_fails_without_leaving_threads(self):
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", self.port))
            blocker.listen()
            before = set(threading.enumerate())
            with self.assertRaisesRegex(RuntimeError, "another MQTT broker"):
                YSimpleMqttRepository(host="127.0.0.1", port=self.port, is_inline_broker=True)
            self.assertEqual(set(threading.enumerate()) - before, set())


if __name__ == "__main__":
    unittest.main()
