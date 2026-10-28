"""NiceGUI runner used standalone or by the unified ``main_ass_2`` entry point."""
from __future__ import annotations

import argparse
from pathlib import Path

from config import DB_DATA


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP bind port (default: 8080)")
    parser.add_argument("--db", type=Path, default=DB_DATA, help="Assignment 1 DuckDB path")
    parser.add_argument("--mqtt-host", help="MQTT broker host (defaults to project config)")
    parser.add_argument("--mqtt-port", type=int, help="MQTT broker port (defaults to project config)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from nicegui import app, ui
    from view.dashboard_live import DashboardLiveService
    live_service = DashboardLiveService(host=args.mqtt_host, port=args.mqtt_port, db_path=args.db)
    run_dashboard(ui, app, live_service, host=args.host, port=args.port, db_path=args.db)
    return 0


def run_dashboard(ui, app, live_service, *, host: str, port: int, db_path: Path,
                  on_startup=None, title: str = "NSW EV Charging Dashboard") -> None:
    """Register dashboard routes then run NiceGUI in the caller's main thread.

    ``main_ass_2`` supplies a service configured for externally committed
    events. The standalone entry point supplies the service's own subscriber.
    """
    from view.dashboard_app import create_dashboard, create_marker_debug_page
    app.on_startup(live_service.start)
    if on_startup is not None:
        app.on_startup(on_startup)
    app.on_shutdown(live_service.stop)

    @ui.page("/")
    def dashboard_page(run_id: str | None = None, debug: str | None = None):
        view = create_dashboard(ui, db_path=db_path, run_id=run_id, debug=debug == "1",
                                snapshot_loader=live_service.load_snapshot)
        if view is not None:
            live_service.register(view)

    @ui.page("/_debug/marker")
    def marker_debug_page():
        create_marker_debug_page(ui)

    ui.run(host=host, port=port, title=title, reload=False)


if __name__ == "__main__":
    raise SystemExit(main())
