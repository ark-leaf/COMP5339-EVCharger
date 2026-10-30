"""The dashboard's single entry point: its live page state and NiceGUI server.

Every live update arrives through ``DashboardDaemon.receive``, the callback of a
dashboard-update subscriber. main_ass_2 registers that subscriber next to the storage
subscriber; ``python -m view.dashboard_daemon`` registers it on its own, reading the
database and following an already-running broker.
"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from urllib.parse import urlencode

from config import DASHBOARD_PORT
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber, subscribed
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.repo_config import mqtt_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT,
                        help="HTTP bind port (default: %(default)s; set DASHBOARD_PORT to change it)")
    parser.add_argument("--mqtt-host", help="MQTT broker host (defaults to project config)")
    parser.add_argument("--mqtt-port", type=int, help="MQTT broker port (defaults to project config)")
    args = parser.parse_args(argv)
    problem = dashboard_port_problem(args.host, args.port)
    if problem is not None:
        parser.error(f"--port {problem}")
    return args


def dashboard_port_problem(host: str, port: int) -> str | None:
    """Say why the dashboard cannot listen on host:port, as text following the option name."""
    if not 1 <= port <= 65535:
        return "must be a valid TCP port"
    reason = port_unavailable_reason(host, port)
    if reason is None:
        return None
    return (f"{port} is unavailable on {host}: {reason}. "
            "Another program may be using it; pass a free port or set DASHBOARD_PORT")


def port_unavailable_reason(host: str, port: int) -> str | None:
    """Return why NiceGUI could not listen on ``host:port`` now, or None if it can.

    The probe binds as uvicorn does (asyncio ``create_server``). uvicorn binds only
    after NiceGUI's startup hooks have run, so entry points call this first.
    """
    async def probe() -> None:
        server = await asyncio.get_running_loop().create_server(asyncio.Protocol, host=host, port=port)
        server.close()
        await server.wait_closed()

    try:
        asyncio.run(probe())
    except OSError as exc:
        return str(exc)
    return None


class DashboardDaemon:
    """Serves the dashboard. Every live update arrives through receive(), the subscriber's callback."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = DASHBOARD_PORT):
        from view.dashboard_live import DashboardLiveService
        self.host, self.port = host, port
        self.live_service = DashboardLiveService()

    def receive(self, event: EVChargerStateEvent) -> None:
        """The dashboard-update subscriber's callback; events that arrive before NiceGUI runs wait for it."""
        self.live_service.receive(event)

    def report_sync_failed(self) -> None:
        """Storage has stopped, so every page now differs from the database."""
        self.live_service.report_sync_failed()

    def stop(self) -> None:
        """Make serve() return; any thread may call it."""
        from nicegui import app
        app.shutdown()

    def serve(self, *, on_startup: Callable[[], None] | None = None,
              title: str = "NSW EV Charging Dashboard") -> None:
        """Serve the dashboard in the calling thread until NiceGUI stops (Ctrl+C)."""
        from nicegui import app, ui
        from view.dashboard_app import (create_dashboard, create_load_error_page, create_marker_debug_page,
                                        resolve_display_timezone)
        live_service = self.live_service
        app.on_startup(live_service.start)
        if on_startup is not None:
            app.on_startup(on_startup)

        # Opening a page reads a whole run's history, which can exceed NiceGUI's 3 s default.
        @ui.page("/", response_timeout=60)
        async def dashboard_page(run_id: str | None = None, debug: str | None = None, tz: str | None = None):
            # Browser IANA zone is authoritative for display; UTC is the explicit
            # fallback when Intl is unavailable or an invalid zone is supplied.
            if not tz:
                try:
                    detected = await ui.run_javascript("try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (_) { return 'UTC'; }", timeout=3)
                except Exception:
                    detected = "UTC"
                tz = resolve_display_timezone(detected)
                query = urlencode({key: value for key, value in
                                   (("run_id", run_id), ("debug", debug), ("tz", tz)) if value is not None})
                ui.navigate.to(f"/?{query}")
                return
            client_id = ui.context.client.id
            try:
                snapshot = await live_service.open_page(client_id, run_id)
            except Exception as exc:
                live_service.close_page(client_id)
                create_load_error_page(ui, exc)
                return
            view = create_dashboard(ui, snapshot, lambda selected: live_service.select_run(client_id, selected),
                                    live_mode=run_id is None, debug=debug == "1", time_zone=tz)
            live_service.attach(client_id, view)

        @ui.page("/_debug/marker")
        def marker_debug_page():
            create_marker_debug_page(ui)

        ui.run(host=self.host, port=self.port, title=title, reload=False)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = mqtt_config()
    dashboard = DashboardDaemon(host=args.host, port=args.port)
    subscriber = YMqttEventSubscriber[EVChargerStateEvent](
        "dashboard-update", dashboard.receive, args.mqtt_host or settings["host"],
        args.mqtt_port or settings["port"], EVChargerStateEvent)
    with subscribed(subscriber):
        dashboard.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
