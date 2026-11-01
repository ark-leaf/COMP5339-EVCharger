"""The dashboard daemon's event hand-off and standalone entry point, and port selection for both entry points."""
from __future__ import annotations

from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from view import dashboard_daemon


class FakeSubscriber:
    """Stands in for YMqttEventSubscriber[...]; it subscribes at once."""
    instances: list = []

    @classmethod
    def __class_getitem__(cls, unused):
        return cls

    def __init__(self, name, handle_event, host, port, event_type):
        self.name, self.handle_event, self.host, self.port = name, handle_event, host, port
        self.ready, self.stopping = threading.Event(), threading.Event()
        self.error, self.started, self.joined = None, False, False
        FakeSubscriber.instances.append(self)

    def start(self):
        self.started = True
        self.ready.set()

    def join(self, timeout=None):
        self.joined = True


class DashboardDaemonTests(unittest.TestCase):
    def setUp(self):
        FakeSubscriber.instances = []
        patcher = patch.object(dashboard_daemon, "YMqttEventSubscriber", FakeSubscriber)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_receive_hands_every_event_to_the_live_pages(self):
        received, event = [], object()
        daemon = dashboard_daemon.DashboardDaemon()
        daemon.live_service = type("Pages", (), {"receive": lambda self, item: received.append(item)})()
        daemon.receive(event)
        self.assertEqual(received, [event])

    def test_stop_asks_nicegui_to_shut_down(self):
        from nicegui import app
        with patch.object(app, "shutdown") as shutdown:
            dashboard_daemon.DashboardDaemon().stop()
        shutdown.assert_called_once_with()

    def test_the_standalone_dashboard_registers_its_own_subscriber_around_serving(self):
        served = []

        def serve(daemon, **unused):
            subscriber, = FakeSubscriber.instances
            served.append((daemon, subscriber.started, subscriber.stopping.is_set()))

        with patch.object(dashboard_daemon, "dashboard_port_problem", return_value=None), \
                patch.object(dashboard_daemon.DashboardDaemon, "serve", serve):
            self.assertEqual(dashboard_daemon.main(["--mqtt-host", "broker", "--mqtt-port", "18830"]), 0)
        (daemon, started, stopping), = served
        subscriber, = FakeSubscriber.instances
        self.assertEqual((subscriber.name, subscriber.host, subscriber.port), ("dashboard-update", "broker", 18830))
        self.assertEqual(subscriber.handle_event, daemon.receive)
        self.assertEqual((started, stopping), (True, False))  # subscribed for as long as it served
        self.assertTrue(subscriber.stopping.is_set())
        self.assertTrue(subscriber.joined)


class DashboardPortTests(unittest.TestCase):
    def test_probe_reports_a_port_that_another_socket_listens_on(self):
        with socket.create_server(("127.0.0.1", 0)) as busy:
            port = busy.getsockname()[1]
            self.assertIsNotNone(dashboard_daemon.port_unavailable_reason("127.0.0.1", port))
        self.assertIsNone(dashboard_daemon.port_unavailable_reason("127.0.0.1", port))

    def test_standalone_dashboard_rejects_a_taken_port_before_starting(self):
        with socket.create_server(("127.0.0.1", 0)) as busy, redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                dashboard_daemon.parse_args(["--port", str(busy.getsockname()[1])])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("DASHBOARD_PORT", stderr.getvalue())

    def test_dashboard_port_follows_the_environment(self):
        result = subprocess.run([sys.executable, "-c", "import config; print(config.DASHBOARD_PORT)"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                                env={**os.environ, "DASHBOARD_PORT": "8123"}, check=True)
        self.assertEqual(result.stdout.strip(), "8123")


if __name__ == "__main__":
    unittest.main()
