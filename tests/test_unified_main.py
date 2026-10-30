"""Unit coverage for main_ass_2: subscriber wiring, the single generator run and the dashboard hand-off."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import main_ass_2


class Broker:
    def __enter__(self): return self
    def __exit__(self, *unused): return False


class UnifiedMainTests(unittest.TestCase):
    def _subscriber_class(self, created, timeline, *, failing=None):
        class Ready(threading.Event):
            def __init__(self, name):
                super().__init__()
                self.name = name
            def wait(self, timeout=None):
                timeline.append(("wait", self.name))
                return super().wait(timeout)

        class Subscriber:
            @classmethod
            def __class_getitem__(cls, unused):
                return cls
            def __init__(self, name, callback, host, port, event_type):
                self.name, self.callback, self.broker = name, callback, (host, port)
                self.ready, self.stopping, self.error = Ready(name), threading.Event(), None
                created.append(self)
            def start(self):
                timeline.append(("start", self.name))
                if self.name == failing:
                    self.error = ConnectionError("refused")
                self.ready.set()
            def join(self, timeout=None): return None
        return Subscriber

    def _dashboard_class(self, daemons, timeline, *, run_startup):
        class Dashboard:
            def __init__(self, **kwargs):
                self.kwargs, self.served_with, self.stopped = kwargs, None, threading.Event()
                daemons.append(self)
            def receive(self, event): pass
            def report_sync_failed(self): pass
            def stop(self): self.stopped.set()
            def serve(self, *, on_startup=None):
                timeline.append(("serve", None))
                self.served_with = on_startup
                if run_startup:
                    on_startup()  # NiceGUI's startup hook: the generator thread's start()
                    on_startup.__self__.join(5)
        return Dashboard

    @contextmanager
    def _fakes(self, *, failing=None, run_startup=False, **generator):
        """Run main() against a fake broker, subscribers, dashboard and generator; data/ is left alone."""
        created, daemons, timeline = [], [], []
        with (patch.object(main_ass_2.data_generator_daemon, "main", **generator) as generate,
              patch.object(main_ass_2, "dashboard_port_problem", return_value=None),
              patch.object(main_ass_2, "_clear_previous_demo_dataset"),
              patch.object(main_ass_2, "prepare_event_storage", side_effect=lambda: timeline.append(("prepare", None))),
              patch.object(main_ass_2, "YSimpleMqttRepository", return_value=Broker()),
              patch.object(main_ass_2, "YMqttEventSubscriber", self._subscriber_class(created, timeline, failing=failing)),
              patch.object(main_ass_2, "DashboardDaemon", self._dashboard_class(daemons, timeline, run_startup=run_startup)),
              redirect_stdout(io.StringIO())):
            yield SimpleNamespace(generate=generate, created=created, daemons=daemons, timeline=timeline)

    def test_unified_run_registers_storage_and_dashboard_subscribers_in_parallel(self):
        with self._fakes() as fakes:
            main_ass_2.main(["--external-broker", "--port", "18830", "--dashboard-port", "8082"])
        dashboard, = fakes.daemons
        storage, live = fakes.created
        self.assertEqual((storage.name, storage.callback.func, storage.callback.keywords),
                         ("database-update", main_ass_2.sub_database_update, {"on_failure": dashboard.report_sync_failed}))
        self.assertEqual((live.name, live.callback), ("dashboard-update", dashboard.receive))
        self.assertEqual({item.broker for item in fakes.created}, {(main_ass_2.mqtt_config()["host"], 18830)})
        # Storage is prepared first. Both subscribers start before either is awaited, and both have
        # subscribed before the dashboard serves.
        self.assertEqual(fakes.timeline, [("prepare", None), ("start", "database-update"), ("start", "dashboard-update"),
                                          ("wait", "database-update"), ("wait", "dashboard-update"), ("serve", None)])
        self.assertTrue(all(item.stopping.is_set() for item in fakes.created))
        self.assertEqual(dashboard.kwargs["port"], 8082)
        self.assertTrue(callable(dashboard.served_with))  # NiceGUI's startup hook starts the generator
        fakes.generate.assert_not_called()  # nothing is generated before the dashboard runs

    def test_a_subscriber_that_cannot_subscribe_stops_both_before_the_dashboard_serves(self):
        with self._fakes(failing="database-update") as fakes:
            with self.assertRaisesRegex(RuntimeError, "database-update did not subscribe"):
                main_ass_2.main(["--external-broker"])
        self.assertNotIn(("serve", None), fakes.timeline)
        self.assertEqual(len(fakes.created), 2)
        self.assertTrue(all(item.stopping.is_set() for item in fakes.created))

    def test_one_generator_run_generates_and_publishes_to_this_broker(self):
        with self._fakes(run_startup=True) as fakes:
            main_ass_2.main(["--port", "18830", "--dashboard-delay", "3", "--limit", "2"])
        fakes.generate.assert_called_once_with(
            ["--limit", "2", "--publish", "--host", main_ass_2.mqtt_config()["host"], "--port", "18830",
             "--startup-wait", "3.0"], shared_connection=True)
        self.assertFalse(fakes.daemons[0].stopped.is_set())

    def test_a_failed_generator_run_stops_the_dashboard_and_is_raised(self):
        with self._fakes(run_startup=True, side_effect=FileExistsError("dataset exists")) as fakes:
            with self.assertRaisesRegex(FileExistsError, "dataset exists"):
                main_ass_2.main(["--external-broker"])
        self.assertTrue(fakes.daemons[0].stopped.is_set())
        self.assertTrue(all(item.stopping.is_set() for item in fakes.created))

    def test_the_generator_cannot_start_a_second_broker(self):
        with (patch.object(main_ass_2, "dashboard_port_problem", return_value=None),
              patch.object(main_ass_2, "YSimpleMqttRepository",
                           side_effect=AssertionError("broker must not start")),
              redirect_stderr(io.StringIO()) as stderr):
            with self.assertRaises(SystemExit) as raised:
                main_ass_2.main(["--limit", "1", "--inline-broker"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--inline-broker cannot be used", stderr.getvalue())

    def test_taken_dashboard_port_stops_before_data_generation(self):
        with (socket.create_server(("127.0.0.1", 0)) as busy,
              patch.object(main_ass_2.data_generator_daemon, "main") as generate,
              patch.object(main_ass_2, "YSimpleMqttRepository",
                           side_effect=AssertionError("broker must not start")),
              redirect_stderr(io.StringIO()) as stderr):
            with self.assertRaises(SystemExit) as raised:
                main_ass_2.main(["--dashboard-port", str(busy.getsockname()[1])])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("DASHBOARD_PORT", stderr.getvalue())
        generate.assert_not_called()

    def test_replacing_the_demo_dataset_is_announced_only_when_one_existed(self):
        with (patch.object(main_ass_2.data_generator_daemon, "remove_dataset", side_effect=[True, False]) as remove,
              redirect_stdout(io.StringIO()) as stdout):
            main_ass_2._clear_previous_demo_dataset(Path("demo"))
            main_ass_2._clear_previous_demo_dataset(Path("demo"))
        self.assertEqual(remove.call_count, 2)
        remove.assert_called_with(Path("demo"))
        self.assertEqual(stdout.getvalue().count("Replacing the previous demo dataset"), 1)

    def test_only_the_default_demo_run_replaces_its_dataset(self):
        for argv in ([], ["--limit", "1", "--out", "elsewhere"]):
            with (self.subTest(argv=argv),
                  patch.object(main_ass_2, "dashboard_port_problem", return_value=None),
                  patch.object(main_ass_2, "_clear_previous_demo_dataset") as clear,
                  patch.object(main_ass_2, "prepare_event_storage", side_effect=RuntimeError("stop"))):
                with self.assertRaisesRegex(RuntimeError, "stop"):
                    main_ass_2.main(argv)
                if argv:
                    clear.assert_not_called()  # an explicit --out keeps the generator's protection
                else:
                    clear.assert_called_once_with(main_ass_2.ASS2_DEMO_DATA_FILE_LOCATION)


if __name__ == "__main__":
    unittest.main()
