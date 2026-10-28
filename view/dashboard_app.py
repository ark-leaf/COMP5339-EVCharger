"""Map-centric NiceGUI presentation layer for the NSW EV Charging Dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import logging
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import DB_DATA
from view.dashboard_data import DashboardSnapshot, DashboardStation, database_guidance, load_dashboard_snapshot
from view.dashboard_leaflet import DashboardLeaflet
from view.dashboard_queries import ActiveSession, DashboardEventSnapshot

NSW_CENTER = (-32.5, 147.0)
NSW_ZOOM = 6
UNKNOWN_MARKER, CHARGING_MARKER, FULL_MARKER, AVAILABLE_MARKER, SELECTED_MARKER = "#718096", "#16875D", "#DC2626", "#2563EB", "#F59E0B"
logger = logging.getLogger(__name__)


def _text(value: object | None, fallback: str = "N/A") -> str:
    return fallback if value is None or value == "" else str(value)


def _power(value: float | None) -> str:
    return f"{value:g} kW" if value is not None else "N/A"


def _price(value: float | None) -> str:
    return "N/A" if value is None else f"${value:.2f}/kWh"


def resolve_display_timezone(name: str | None) -> str:
    """Return a validated IANA identifier; UTC is the explicit display fallback."""
    if not isinstance(name, str) or not name.strip():
        return "UTC"
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def _timezone(name: str | None):
    return timezone.utc if resolve_display_timezone(name) == "UTC" else ZoneInfo(name)


def _timestamp(value, zone: str | None = "UTC") -> str:
    if value is None: return "No event data"
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    local = value.astimezone(_timezone(zone))
    return local.strftime("%Y-%m-%d %H:%M %Z")


def _state_for(station: DashboardStation, events: DashboardEventSnapshot):
    return events.live_states.get(station.charger.charger_id)


def _status_for(station: DashboardStation, events: DashboardEventSnapshot) -> str:
    """Return the same selected-run status used by marker colour and filtering."""
    state = _state_for(station, events)
    capacity = station.charger.number_of_plugs
    if state is None or not isinstance(capacity, int) or capacity < 1:
        return "unknown"
    sessions = [session for session in events.active_sessions
                if session.charger_id == station.charger.charger_id]
    occupied = {session.connector_no for session in sessions
                if isinstance(session.connector_no, int) and 1 <= session.connector_no <= capacity}
    # Every reconstructed physical connector must be valid. A state that claims
    # more active sessions than the selected-run reconstruction can evidence is
    # also insufficient; duplicate rows for the same connector remain one port.
    if (any(not isinstance(session.connector_no, int) or not 1 <= session.connector_no <= capacity
            for session in sessions) or state.active_sessions < 0
            or state.active_sessions > len(sessions)
            or state.active_sessions < len(occupied)
            or (state.active_sessions and not occupied)):
        return "unknown"
    if not occupied:
        return "available"
    return "full" if len(occupied) == capacity else "charging"


def _occupancy_for(station: DashboardStation, events: DashboardEventSnapshot) -> tuple[int, int] | None:
    if _status_for(station, events) == "unknown":
        return None
    capacity = station.charger.number_of_plugs
    occupied = {session.connector_no for session in events.active_sessions
                if session.charger_id == station.charger.charger_id}
    return len(occupied), capacity


def _marker_color(station: DashboardStation, events: DashboardEventSnapshot) -> str:
    return {"unknown": UNKNOWN_MARKER, "charging": CHARGING_MARKER, "full": FULL_MARKER,
            "available": AVAILABLE_MARKER}[_status_for(station, events)]


def _marker_style(station: DashboardStation, events: DashboardEventSnapshot, *, selected: bool = False) -> dict:
    color = SELECTED_MARKER if selected else _marker_color(station, events)
    return {"radius": 8 if selected else 6, "color": color, "weight": 2 if selected else 1,
            "fillColor": color, "fillOpacity": 0.9 if selected else 0.76}


def _popup_html(station: DashboardStation, events: DashboardEventSnapshot) -> str:
    state, charger = _state_for(station, events), station.charger
    status = _status_for(station, events).title()
    occupancy = _occupancy_for(station, events)
    connectors = ", ".join(station.connector_types) or "N/A"
    return ("<div class='ev-popup'>"
            f"<strong>{escape(_text(charger.station_name, f'Station #{charger.charger_id}'))}</strong>"
            f"<div>{escape(_text(charger.station_address))}</div>"
            f"<div>{escape(_text(charger.operator_name))} · {escape(connectors)}</div>"
            f"<div><b>{escape(status)}</b> · {escape(_price(state.price_per_kwh) if state else 'N/A')}</div>"
            f"{f'<div>Occupied ports: {occupancy[0]} / {occupancy[1]}</div>' if occupancy else ''}</div>")


def _marker_id_from_event(event) -> str | None:
    """Return the explicit per-layer id emitted by ``DashboardLeaflet``."""
    args = getattr(event, "args", None)
    if isinstance(args, str):
        return args or None
    if isinstance(args, dict):
        marker_id = args.get("marker_id") or args.get("id")
        return str(marker_id) if marker_id is not None else None
    return None


def _dashboard_run_url(run_id: str) -> str:
    return f"/?run_id={quote(run_id, safe='')}"


def _run_selection_handler(current_run_id: str | None, on_run_change: Callable[[str], None]):
    """Navigate for a user selection without permanently suppressing retries."""
    handling_change = False

    def handle(event) -> None:
        nonlocal handling_change
        selected = getattr(event, "value", None)
        if selected is None:
            return
        selected = str(selected)
        if not selected or selected == current_run_id or handling_change:
            return
        logger.info("Dashboard run selector received selected=%s current=%s", selected, current_run_id)
        handling_change = True
        try:
            on_run_change(selected)
        finally:
            # A failed/navigation-interrupted request must be selectable again.
            handling_change = False

    return handle


def _metric_card(ui, title: str, value: str, icon: str, hint: str):
    with ui.card().classes("metric-card flex-1 min-w-52"):
        with ui.row().classes("w-full items-start justify-between no-wrap"):
            with ui.column().classes("gap-0"):
                ui.label(title).classes("metric-title")
                label = ui.label(value).classes("metric-value")
                ui.label(hint).classes("metric-hint")
            ui.icon(icon, color="primary").classes("text-2xl")
    return label


def _detail_field(ui, title: str, *, accent: bool = False):
    with ui.column().classes("detail-field gap-0"):
        ui.label(title).classes("detail-label")
        value = ui.label("—").classes("detail-value" + (" detail-accent" if accent else ""))
    return value


def _chart_options(points=(), zone="UTC"):
    return {"animation": False, "grid": {"left": 44, "right": 18, "top": 28, "bottom": 42}, "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [_timestamp(p.event_ts, zone) for p in points], "axisLabel": {"color": "#64748b"}},
            "yAxis": {"type": "value", "name": "kWh", "axisLabel": {"color": "#64748b"}, "splitLine": {"lineStyle": {"color": "#e2e8f0"}}},
            "series": [{"type": "line", "smooth": True, "showSymbol": True, "symbolSize": 7, "data": [p.energy_kwh for p in points],
                        "lineStyle": {"color": CHARGING_MARKER, "width": 3}, "areaStyle": {"color": "rgba(22,135,93,0.10)"}}]}


def _event_chart(counts: dict[str, int]):
    labels = ["Price updates", "Session starts", "Meter events", "Session ends"]
    values = [counts.get(key, 0) for key in ("price_update", "session_start", "meter", "session_end")]
    return {"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "textStyle": {"fontSize": 13}}, "grid": {"left": 108, "right": 45, "top": 20, "bottom": 30}, "xAxis": {"type": "value", "name": "Events", "axisLabel": {"fontSize": 13}}, "yAxis": {"type": "category", "data": labels, "axisLabel": {"fontSize": 13}}, "series": [{"type": "bar", "data": [{"value": v, "itemStyle": {"color": c}} for v,c in zip(values, ["#16875D", "#2563EB", "#7C3AED", "#F59E0B"])], "label": {"show": True, "position": "right", "fontSize": 13}}]}


def _top_station_chart(top: tuple[tuple[int, int], ...], stations: dict[int, DashboardStation]):
    ordered = tuple(reversed(top)); labels = [f"{_text(stations.get(cid).charger.station_name if cid in stations else None, f'Station {cid}')} (#{cid})" for cid, _ in ordered]
    return {"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "textStyle": {"fontSize": 13}}, "grid": {"left": 170, "right": 45, "top": 20, "bottom": 34}, "xAxis": {"type": "value", "name": "Completed Sessions", "axisLabel": {"fontSize": 13}}, "yAxis": {"type": "category", "data": labels, "axisLabel": {"fontSize": 12, "width": 155, "overflow": "truncate"}}, "series": [{"type": "bar", "data": [v for _,v in ordered], "itemStyle": {"color": "#2563EB"}, "label": {"show": True, "position": "right", "fontSize": 13}}]}


def _price_chart(points, zone="UTC"):
    return {"animation": False, "grid": {"left": 48, "right": 15, "top": 25, "bottom": 38}, "tooltip": {"trigger": "axis", "formatter": "{b}<br/>AUD/kWh: {c}"}, "xAxis": {"type": "category", "data": [_timestamp(p.event_ts, zone) for p in points]}, "yAxis": {"type": "value", "name": "AUD/kWh"}, "series": [{"type": "line", "showSymbol": True, "symbolSize": 10 if len(points) == 1 else 6, "data": [p.price_per_kwh for p in points], "lineStyle": {"color": "#F59E0B", "width": 2}}]}


def _replace_chart_options(chart, new_options: dict) -> None:
    """Replace NiceGUI 3.18 EChart options without assigning its read-only property."""
    chart.options.clear()
    chart.options.update(new_options)
    chart.update()


@dataclass
class DashboardView:
    """Stable UI boundary for Step 3's post-commit event-push runtime."""
    snapshot: DashboardSnapshot
    active_sessions_label: object
    average_price_label: object
    completed_sessions_label: object
    last_event_label: object
    event_notice: object
    analytics_value: object
    selection_intro: object
    selection_body: object
    station_title: object
    station_subtitle: object
    station_fields: dict[str, object]
    session_area: object
    session_select: object
    curve_chart: object
    curve_empty: object
    session_info: object | None = None
    debug_label: object | None = None
    marker_layers: dict[str, tuple[DashboardStation, object]] = field(default_factory=dict)
    marker_id_by_charger: dict[int, str] = field(default_factory=dict)
    selected_charger_id: int | None = None
    selected_session_key: str | None = None
    charging_map: object | None = None
    filter_count_label: object | None = None
    filter_controls: dict[str, object] = field(default_factory=dict)
    stations_by_id: dict[int, DashboardStation] = field(default_factory=dict)
    history_fields: dict[str, object] = field(default_factory=dict)
    analytics_charts: dict[str, object] = field(default_factory=dict)
    analytics_summary_labels: dict[str, object] = field(default_factory=dict)
    run_selector: object | None = None
    run_selector_run_ids: tuple[str, ...] = ()
    live_run_id: str | None = None
    connection_badge: object | None = None
    snapshot_summary_label: object | None = None
    _programmatic_selector_sync: bool = False
    sync_failed: bool = False
    live_mode: bool = True
    mode_badge: object | None = None
    live_button: object | None = None
    on_run_change: Callable[[str], DashboardSnapshot] | None = None
    time_zone: str = "UTC"

    def _sessions_for(self, charger_id: int) -> tuple[ActiveSession, ...]:
        return (tuple(s for s in self.snapshot.events.active_sessions if s.charger_id == charger_id) +
                tuple(s for s in self.snapshot.events.completed_session_records if s.charger_id == charger_id))

    @staticmethod
    def _session_key(session: ActiveSession) -> str:
        return f"{session.charger_id}:{session.connector_no}:{session.session_id}"

    def _set_marker_style(self, charger_id: int, *, selected: bool) -> None:
        entry = self.marker_layers.get(self.marker_id_by_charger.get(charger_id, ""))
        if entry:
            station, layer = entry
            layer.run_method("setStyle", _marker_style(station, self.snapshot.events, selected=selected))

    def _show_curve(self, session_key: str | None) -> None:
        session = next((s for s in self._sessions_for(self.selected_charger_id or -1) if self._session_key(s) == session_key), None)
        self.selected_session_key = session_key if session else None
        if self.session_info is not None:
            if session is None:
                self.session_info.set_text("")
            elif session.session_end_ts is None:
                self.session_info.set_text(
                    f"Live session · Connector {session.connector_no} · Started {_timestamp(session.session_start_ts, self.time_zone)}")
            else:
                self.session_info.set_text(
                    f"Completed Session · Connector {session.connector_no} · Start {_timestamp(session.session_start_ts, self.time_zone)} · "
                    f"End {_timestamp(session.session_end_ts, self.time_zone)} · Energy {_text(f'{session.delivered_energy_kwh:.2f} kWh' if session.delivered_energy_kwh is not None else None)} · "
                    f"Cost {_text(f'${session.recorded_cost_aud:.2f}' if session.recorded_cost_aud is not None else None)} · "
                    f"Duration {_text(f'{session.duration_minutes:.1f} min' if session.duration_minutes is not None else None)}")
        points = self.snapshot.events.meter_points.get(session.key, ()) if session else ()
        if not points:
            self.curve_empty.set_text("No stored meter events for the selected session")
            self.curve_empty.set_visibility(True)
            self.curve_chart.set_visibility(False)
            return
        _replace_chart_options(self.curve_chart, _chart_options(points, self.time_zone))
        self.curve_chart.set_visibility(True)
        self.curve_empty.set_visibility(False)

    def select_history_run(self, run_id: str) -> None:
        if (self._programmatic_selector_sync or not run_id or
                run_id not in self.run_selector_run_ids or self.on_run_change is None or
                run_id == self.snapshot.events.run_id):
            return
        snapshot = self.on_run_change(run_id)
        self.live_mode = False
        if self.mode_badge: self.mode_badge.set_text("History")
        if self.live_button: self.live_button.set_visibility(True)
        self.apply_event_snapshot(snapshot.events)

    def return_to_live(self) -> None:
        if self.on_run_change is None:
            return
        target_run = self.live_run_id or (self.run_selector_run_ids[0] if self.run_selector_run_ids else None)
        if target_run is None:
            return
        self.live_mode = True
        if self.mode_badge: self.mode_badge.set_text("Live")
        if self.live_button: self.live_button.set_visibility(False)
        snapshot = self.on_run_change(target_run)
        self.apply_event_snapshot(snapshot.events, live=True)

    def set_live_sync_failed(self) -> None:
        """Show a fatal transport/persistence condition without changing mode."""
        self.sync_failed = True
        if self.connection_badge:
            self.connection_badge.set_text("LIVE synchronization FAILED")
            self.connection_badge.props("color=negative")

    def clear_selection(self) -> None:
        if self.selected_charger_id is not None:
            self._set_marker_style(self.selected_charger_id, selected=False)
        self.selected_charger_id, self.selected_session_key = None, None
        self.selection_intro.set_visibility(True)
        self.selection_body.set_visibility(False)
        self.session_area.set_visibility(False)
        self.curve_chart.set_visibility(False)
        if self.session_info is not None: self.session_info.set_text("")
        self.curve_empty.set_text("Select a station with an active session to view stored meter events")
        self.curve_empty.set_visibility(True)

    def show_station(self, station: DashboardStation, *, preferred_session_key: str | None = None) -> None:
        if self.selected_charger_id is not None and self.selected_charger_id != station.charger.charger_id:
            self._set_marker_style(self.selected_charger_id, selected=False)
        self.selected_charger_id = station.charger.charger_id
        self._set_marker_style(station.charger.charger_id, selected=True)
        self.selection_intro.set_visibility(False)
        self.selection_body.set_visibility(True)
        charger, state = station.charger, _state_for(station, self.snapshot.events)
        self.station_title.set_text(_text(charger.station_name, f"Station #{charger.charger_id}"))
        status, occupancy = _status_for(station, self.snapshot.events).title(), _occupancy_for(station, self.snapshot.events)
        self.station_subtitle.set_text(f"Station ID {charger.charger_id} · {status}")
        values = {"Address": _text(charger.station_address), "Operator": _text(charger.operator_name),
                  "Charger Type": _text(charger.charger_type), "Connector Type": ", ".join(station.connector_types) or "N/A",
                  "Number of Plugs": _text(charger.number_of_plugs), "Max Power": _power(charger.rating_kw),
                  "Latest Price": _price(state.price_per_kwh) if state else "N/A", "Charging Status": status}
        values.update({"Station ID": charger.charger_id, "Postcode": _text(station.postcode), "LGA": _text(station.lga_name), "SA4 Region": _text(station.sa4_name), "Active Session Count": state.active_sessions if state else "N/A", "Occupied Ports": f"{occupancy[0]} / {occupancy[1]}" if occupancy else "N/A", "Last Price Update": _timestamp(state.price_updated_ts, self.time_zone) if state and state.price_updated_ts else "N/A", "Last Event": _timestamp(state.last_event_ts, self.time_zone) if state else "N/A"})
        for name, value in values.items():
            if name in self.station_fields: self.station_fields[name].set_text(str(value))
        history = self.snapshot.events.analytics.station_history.get(charger.charger_id)
        history_values = {"Completed Sessions": history.completed_sessions if history else "No event data for this station in the selected run", "Delivered Energy": f"{history.delivered_energy_kwh:.2f} kWh" if history and history.delivered_energy_kwh is not None else "N/A", "Recorded Cost": f"${history.recorded_cost_aud:.2f}" if history and history.recorded_cost_aud is not None else "N/A", "Average Duration": f"{history.average_duration_minutes:.1f} min" if history and history.average_duration_minutes is not None else "N/A"}
        for name, value in history_values.items():
            if name in self.history_fields: self.history_fields[name].set_text(str(value))
        if "Price History" in self.analytics_charts:
            points = history.price_points if history else ()
            chart, empty = self.analytics_charts["Price History"], self.analytics_charts["Price Empty"]
            if points:
                _replace_chart_options(chart, _price_chart(points, self.time_zone)); chart.set_visibility(True)
                empty.set_text("Only one price observation recorded." if len(points) == 1 else "")
                empty.set_visibility(len(points) == 1)
            else:
                chart.set_visibility(False); empty.set_text("This station has no stored price observations for the selected Run."); empty.set_visibility(True)
        sessions = self._sessions_for(charger.charger_id)
        self.session_area.set_visibility(True)
        if not sessions:
            self.session_select.set_visibility(False)
            self.curve_chart.set_visibility(False)
            self.curve_empty.set_text("No active or completed charging session for this station")
            self.curve_empty.set_visibility(True)
            self.selected_session_key = None
            return
        active_keys = {self._session_key(s) for s in self.snapshot.events.active_sessions if s.charger_id == charger.charger_id}
        options = {self._session_key(s): f"{'Live' if self._session_key(s) in active_keys else 'Completed'} · Connector {s.connector_no} · Session {s.session_id}" for s in sessions}
        wanted = preferred_session_key if preferred_session_key in options else next(iter(options))
        self.session_select.options, self.session_select.value = options, wanted
        self.session_select.set_visibility(len(options) > 1)
        self.session_select.update()
        self._show_curve(wanted)

    def select_marker(self, marker_id: str | None) -> None:
        """Select an exact Leaflet layer; a blank map click clears selection."""
        if marker_id is None:
            if self.debug_label:
                self.debug_label.set_text("Debug: blank-map click received; selection cleared.")
            self.clear_selection()
        elif marker_id in self.marker_layers:
            self.show_station(self.marker_layers[marker_id][0])
            if self.debug_label:
                self.debug_label.set_text(
                    f"Debug: marker event received; layer mapped; selected charger {self.selected_charger_id}."
                )
        elif self.debug_label:
            self.debug_label.set_text("Debug: marker event received, but its layer id was not mapped.")

    def update_run_options(self, run_ids: tuple[str, ...], *, latest_live_run_id: str | None = None) -> None:
        """Expose a newly committed run without changing this page's selection."""
        available_runs = tuple(run_ids)
        if latest_live_run_id is not None:
            self.live_run_id = latest_live_run_id
        if self.run_selector is None or available_runs == self.run_selector_run_ids:
            return
        self.run_selector.options = list(available_runs)
        self.run_selector_run_ids = available_runs
        self.run_selector.update()

    def _sync_run_selector(self, run_id: str | None) -> None:
        """Reflect a server-selected snapshot without treating it as a manual choice."""
        if self.run_selector is not None and self.run_selector.value != run_id:
            self._programmatic_selector_sync = True
            try:
                self.run_selector.value = run_id
                self.run_selector.update()
            finally:
                self._programmatic_selector_sync = False

    def _update_snapshot_summary(self, events: DashboardEventSnapshot) -> None:
        if self.snapshot_summary_label is not None:
            coverage = events.analytics
            self.snapshot_summary_label.set_text(
                f"Snapshot Loaded · Run {events.run_id or 'N/A'} · "
                f"{coverage.stations_with_event_data or 0:,}/{self.snapshot.total_chargers:,} stations with event data · "
                f"{coverage.total_events or 0:,} total events · simulated time "
                f"{_timestamp(events.last_event_ts, self.time_zone)} · {self.time_zone}")

    def apply_event_snapshot(self, events: DashboardEventSnapshot,
                             changed_charger_ids: set[int] | None = None,
                             *, live: bool = False) -> None:
        """Refresh existing UI after a committed event, without recreating the map."""
        self.snapshot = DashboardSnapshot(self.snapshot.total_chargers, self.snapshot.stations, events)
        self._sync_run_selector(events.run_id)
        self._update_snapshot_summary(events)
        self.active_sessions_label.set_text("N/A" if events.active_session_count is None else str(events.active_session_count))
        self.average_price_label.set_text(_price(events.average_price_per_kwh))
        self.completed_sessions_label.set_text("N/A" if events.completed_sessions is None else str(events.completed_sessions))
        self.last_event_label.set_text(f"Latest simulated event: {_timestamp(events.last_event_ts, self.time_zone)}")
        if live and self.connection_badge is not None and not self.sync_failed:
            self.connection_badge.set_text("Live updates received")
        self.event_notice.set_text("Charging network loaded. Awaiting simulation events." if not events.has_event_data else ("Live update received." if live else "Simulation data loaded."))
        self.analytics_value.set_text("No Event Data" if not events.has_event_data else f"{events.completed_sessions} completed sessions")
        summary_values = {
            "Completed Sessions": "N/A" if events.completed_sessions is None else str(events.completed_sessions),
            "Total Delivered Energy": "N/A" if events.analytics.delivered_energy_kwh is None else f"{events.analytics.delivered_energy_kwh:.2f} kWh",
            "Total Recorded Cost": "N/A" if events.analytics.recorded_cost_aud is None else f"${events.analytics.recorded_cost_aud:.2f}",
            "Average Session Duration": "N/A" if events.analytics.average_duration_minutes is None else f"{events.analytics.average_duration_minutes:.1f} min",
        }
        for title, value in summary_values.items():
            if label := self.analytics_summary_labels.get(title):
                label.set_text(value)
        if chart := self.analytics_charts.get("Events by Type"):
            _replace_chart_options(chart, _event_chart(events.analytics.event_type_counts))
        if chart := self.analytics_charts.get("Top Stations"):
            _replace_chart_options(chart, _top_station_chart(events.analytics.top_station_sessions, self.stations_by_id))
        marker_rows = self.marker_layers.values() if changed_charger_ids is None else (
            row for row in self.marker_layers.values()
            if row[0].charger.charger_id in changed_charger_ids
        )
        for station, layer in marker_rows:
            selected = station.charger.charger_id == self.selected_charger_id
            layer.run_method("setStyle", _marker_style(station, events, selected=selected))
            layer.run_method("bindPopup", _popup_html(station, events))
        if self._filters_are_active():
            self.apply_filters()
        if self.selected_charger_id is not None:
            station = next((s for s in self.snapshot.stations if s.charger.charger_id == self.selected_charger_id), None)
            if station:
                self.show_station(station, preferred_session_key=self.selected_session_key)

    def _filters_are_active(self) -> bool:
        if not self.filter_controls:
            return False
        return any(str(self.filter_controls[name].value or "") not in ("", "all")
                   for name in ("search", "coverage", "type", "operator", "power", "connector", "status"))

    def _station_matches_filters(self, station: DashboardStation) -> bool:
        query = str(self.filter_controls["search"].value or "").lower().strip()
        coverage, charger_type = self.filter_controls["coverage"].value, self.filter_controls["type"].value
        operator, power = self.filter_controls["operator"].value, self.filter_controls["power"].value
        connector, status = self.filter_controls["connector"].value, self.filter_controls["status"].value
        c = station.charger
        haystack = " ".join(str(x or "") for x in (c.station_name, c.charger_id, c.station_address, c.operator_name, station.postcode, station.lga_name)).lower()
        matches = ((not query or query in haystack) and
                   (coverage != "events" or c.charger_id in self.snapshot.events.analytics.station_history) and
                   (charger_type == "all" or c.charger_type == charger_type) and
                   (operator == "all" or c.operator_name == operator) and
                   (connector == "all" or connector in " ".join(station.connector_types).upper()) and
                   (status == "all" or _status_for(station, self.snapshot.events) == status))
        if power == "unknown": return matches and c.rating_kw is None
        if power == "low": return matches and c.rating_kw is not None and c.rating_kw < 22
        if power == "medium": return matches and c.rating_kw is not None and 22 <= c.rating_kw < 100
        if power == "high": return matches and c.rating_kw is not None and c.rating_kw >= 100
        return matches

    def apply_filters(self) -> None:
        """Hide/show existing Leaflet layers; the map itself is never recreated."""
        if not self.charging_map: return
        visible_ids = [marker_id for marker_id, (station, _layer) in self.marker_layers.items()
                       if self._station_matches_filters(station)]
        self.charging_map.run_method("set_layers_visible", visible_ids)
        visible = len(visible_ids)
        if self.selected_charger_id is not None and self.marker_id_by_charger.get(self.selected_charger_id) not in visible_ids:
            self.clear_selection()
        if self.filter_count_label: self.filter_count_label.set_text(f"{visible:,} matching stations")

    def search_and_select(self) -> None:
        query = str(self.filter_controls["search"].value or "").lower().strip(); self.apply_filters()
        if not query: return
        station = next((s for s in self.snapshot.stations if self._station_matches_filters(s)), None)
        if station and station.has_valid_coordinates and self.charging_map:
            self.show_station(station); self.charging_map.run_method("setView", [station.charger.latitude, station.charger.longitude], 13)
            self.marker_layers[self.marker_id_by_charger[station.charger.charger_id]][1].run_method("openPopup")

    def reset_filters(self) -> None:
        for name, value in (("search", ""), ("coverage", "all"), ("type", "all"), ("operator", "all"), ("power", "all"), ("connector", "all"), ("status", "all")): self.filter_controls[name].value = value
        self.apply_filters()


def _add_styles(ui) -> None:
    ui.add_head_html("""<style>
      html,body,#app{background:#f4f7f6}.nicegui-content{max-width:none!important;padding:0!important}
      .dashboard-shell{width:100%;padding:16px 22px 26px;box-sizing:border-box}.metric-card,.panel-card{border:1px solid #dfe8e3;box-shadow:0 3px 13px rgba(15,60,45,.06);border-radius:14px;background:#fff}
      .metric-card{min-height:116px;padding:18px 20px}.metric-title,.detail-label{color:#64748b;font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}.metric-value{color:#172b25;font-size:30px;font-weight:750;line-height:1.16;margin-top:5px}.metric-hint{color:#718096;font-size:13px;margin-top:6px}
      .main-panels{display:grid;grid-template-columns:minmax(0,7fr) minmax(330px,3fr);align-items:stretch;height:clamp(760px,calc(100vh - 225px),900px);gap:16px}.main-panels>.q-card{height:100%;min-height:0;width:auto!important;margin:0;box-sizing:border-box}.map-card{min-width:0;display:flex!important;flex-direction:column!important;overflow:hidden;box-sizing:border-box}.map-card>.row,.map-card>.q-card{flex:0 0 auto}.map-viewport{position:relative;width:100%;min-width:0;max-width:100%;box-sizing:border-box;align-self:stretch;flex:1 1 auto;min-height:460px;overflow:hidden;border-radius:11px}.map-frame{width:100%!important;height:100%!important;min-height:0!important;display:block}.detail-card{min-width:0;overflow-y:auto;overflow-x:hidden;box-sizing:border-box}.detail-field{padding:10px 0;border-bottom:1px solid #edf1ef}.detail-value{color:#23332c;font-size:15px;line-height:1.45}.detail-accent{color:#08794d;font-weight:700}.ev-popup{min-width:205px;color:#24342d;font-size:14px;line-height:1.5}.ev-popup strong{font-size:15px}.map-legend{position:absolute!important;z-index:750!important;pointer-events:none;background:rgba(255,255,255,.94);border:1px solid #dfe8e3;border-radius:8px;box-shadow:0 2px 8px rgba(15,60,45,.12);padding:8px 10px;font-size:13px;color:#334155}.legend-dot{height:9px;width:9px;border-radius:999px;display:inline-block;margin-right:6px}.empty-state{border:1px dashed #cad7d0;border-radius:10px;background:#f8fbf9}.section-heading{font-size:18px;font-weight:700;color:#1f342b}.chart-card{flex:1 1 0;min-width:420px}.chart-frame{height:310px}.history-summary{min-height:102px;padding:15px 18px}
      @media(max-width:1024px){.dashboard-shell{padding:13px}.main-panels{grid-template-columns:1fr;height:auto}.main-panels>.q-card{height:auto;min-height:0}.map-viewport{height:600px;min-height:600px;flex:none}.detail-card{max-height:none}}@media(max-width:780px){.dashboard-shell{padding:10px}.map-viewport{height:520px;min-height:520px}.chart-card{min-width:100%}}
    </style>""")


def _build_loaded_page(ui, snapshot: DashboardSnapshot, load_run: Callable[[str], DashboardSnapshot], *, debug: bool = False,
                       live_mode: bool = True, time_zone: str = "UTC") -> DashboardView:
    _add_styles(ui); ui.colors(primary="#16875D", secondary="#0F5E43", accent="#22A06B"); events = snapshot.events
    with ui.header().classes("bg-white text-slate-800 border-b border-slate-200 shadow-sm"):
        with ui.row().classes("w-full items-center justify-between px-5 py-2 no-wrap"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.icon("ev_station", color="primary").classes("text-3xl")
                with ui.column().classes("gap-0"):
                    ui.label("NSW EV Charging Dashboard").classes("text-xl font-bold")
                    ui.label("Real-time Charging Monitoring").classes("text-[13px] text-slate-500")
            with ui.row().classes("items-center gap-4 no-wrap"):
                last_event_label = ui.label(f"Latest simulated event: {_timestamp(events.last_event_ts, time_zone)} · {time_zone}").classes("text-[13px] text-slate-500 max-sm:hidden")
                connection_badge = ui.badge("Snapshot Loaded" if events.has_event_data else "No Event Data", color="primary" if events.has_event_data else "grey-6")
                mode_badge = ui.badge("Live" if live_mode else "History", color="primary" if live_mode else "grey-7")
                live_button = ui.button("Live", icon="sensors").props("flat dense").classes("text-primary")
                run_selector = ui.select(options=list(events.run_ids), value=events.run_id, label="Simulation Run").props("dense outlined").classes("w-64 max-sm:w-40")
    with ui.element("main").classes("dashboard-shell"):
        event_notice = ui.label("Charging network loaded. Awaiting simulation events." if not events.has_event_data else "Simulation data loaded.").classes("text-[13px] text-slate-600 mb-3")
        coverage = events.analytics
        snapshot_summary_label = ui.label(f"Snapshot Loaded · Run {events.run_id or 'N/A'} · {coverage.stations_with_event_data or 0:,}/{snapshot.total_chargers:,} stations with event data · {coverage.total_events or 0:,} total events · simulated time {_timestamp(events.last_event_ts, time_zone)} · {time_zone}").classes("text-[13px] text-slate-500 mb-3")
        with ui.row().classes("w-full gap-4 flex-wrap mb-4"):
            _metric_card(ui, "Total Chargers", f"{snapshot.total_chargers:,}", "ev_station", "NSW network locations")
            active_sessions_label = _metric_card(ui, "Active Sessions", "N/A" if events.active_session_count is None else str(events.active_session_count), "bolt", "Current selected run")
            average_price_label = _metric_card(ui, "Average Charging Price", _price(events.average_price_per_kwh), "payments", "Known latest prices")
            completed_sessions_label = _metric_card(ui, "Completed Sessions", "N/A" if events.completed_sessions is None else str(events.completed_sessions), "task_alt", "Historical selected run")
        with ui.element("div").classes("main-panels"):
            with ui.card().classes("panel-card map-card grow basis-0 p-3 relative"):
                with ui.row().classes("w-full items-center justify-between pb-2"):
                    with ui.column().classes("gap-0"):
                        ui.label("NSW Charging Network").classes("section-heading")
                        ui.label(f"{len(snapshot.mappable_stations):,} real station locations · marker status is Unknown until an event is received").classes("text-[13px] text-slate-500")
                    ui.icon("map", color="primary").classes("text-2xl")
                with ui.card().classes("w-full mb-2 p-2 bg-slate-50"):
                    search_input = ui.input(label="Search station, ID, address, operator or suburb").props("dense outlined clearable").classes("w-full")
                    with ui.row().classes("w-full gap-2 flex-wrap mt-1"):
                        coverage_filter = ui.select({"all":"All Stations","events":"Stations with Event Data"}, value="all", label="Coverage").props("dense outlined").classes("min-w-40 grow")
                        type_filter = ui.select({"all":"All types", "AC":"AC", "DC":"DC"}, value="all", label="Charger type").props("dense outlined").classes("min-w-28 grow")
                        operator_filter = ui.select({"all":"All operators", **{o:o for o in sorted({s.charger.operator_name for s in snapshot.stations if s.charger.operator_name})}}, value="all", label="Operator", with_input=True).props("dense outlined").classes("min-w-40 grow")
                        power_filter = ui.select({"all":"All power", "low":"< 22 kW", "medium":"22–99 kW", "high":"≥ 100 kW", "unknown":"Unknown rating"}, value="all", label="Power").props("dense outlined").classes("min-w-32 grow")
                        connector_filter = ui.select({"all":"All connectors", "CCS":"CCS", "CHADEMO":"CHAdeMO", "TYPE 2":"Type 2", "OTHER":"Other / Unknown"}, value="all", label="Connector").props("dense outlined").classes("min-w-32 grow")
                        status_filter = ui.select({"all":"All Statuses", "available":"Available", "charging":"Charging", "full":"Full", "unknown":"Unknown"}, value="all", label="Charging Status").props("dense outlined").classes("min-w-32 grow")
                    with ui.row().classes("w-full items-center justify-between mt-1"):
                        filter_count = ui.label(f"{len(snapshot.mappable_stations):,} matching stations").classes("text-[13px] text-slate-600")
                        with ui.row().classes("gap-1"):
                            search_button = ui.button("Find", icon="search").props("dense")
                            reset_button = ui.button("Reset", icon="restart_alt").props("flat dense")
                with ui.element("div").classes("map-viewport"):
                    charging_map = DashboardLeaflet(center=NSW_CENTER, zoom=NSW_ZOOM).classes("map-frame")
                    with ui.element("div").classes("map-legend absolute left-3 bottom-3 z-10"):
                        ui.html(f"<div><span class='legend-dot' style='background:{AVAILABLE_MARKER}'></span>Available</div><div><span class='legend-dot' style='background:{CHARGING_MARKER}'></span>Charging</div><div><span class='legend-dot' style='background:{FULL_MARKER}'></span>Full</div><div><span class='legend-dot' style='background:{UNKNOWN_MARKER}'></span>Unknown</div>")
            with ui.card().classes("panel-card detail-card w-[31%] min-w-80 p-4 max-md:w-full"):
                ui.label("Station Details").classes("section-heading")
                debug_label = ui.label("Debug: waiting for a map interaction.").classes("text-[12px] text-slate-500 mt-1") if debug else None
                with ui.column().classes("empty-state items-center text-center p-5 mt-3 gap-2") as selection_intro:
                    ui.icon("touch_app", color="primary").classes("text-3xl"); ui.label("No station selected").classes("text-base font-semibold"); ui.label("Click a charger on the map to view details.").classes("text-[13px] text-slate-500")
                with ui.column().classes("w-full gap-0 mt-3") as selection_body:
                    with ui.row().classes("w-full items-start justify-between gap-2"):
                        with ui.column().classes("gap-0"):
                            station_title = ui.label("—").classes("text-xl font-bold text-primary")
                            station_subtitle = ui.label("—").classes("text-[13px] text-slate-500 mb-2")
                        clear_button = ui.button("Clear", icon="close").props("flat dense").classes("text-slate-600")
                    ui.label("Station Overview").classes("text-[15px] font-bold mt-2")
                    station_fields = {name: _detail_field(ui, name, accent=name in {"Latest Price", "Charging Status"}) for name in ("Address", "Operator", "Station ID", "Postcode", "LGA", "SA4 Region")}
                    ui.label("Charging Information").classes("text-[15px] font-bold mt-4")
                    station_fields.update({name: _detail_field(ui, name) for name in ("Charger Type", "Connector Type", "Number of Plugs", "Max Power")})
                    ui.label("Live Status").classes("text-[15px] font-bold mt-4")
                    station_fields.update({name: _detail_field(ui, name, accent=True) for name in ("Latest Price", "Charging Status", "Occupied Ports", "Active Session Count", "Last Price Update", "Last Event")})
                    ui.separator().classes("mt-4"); ui.label("Charging Progress").classes("text-[15px] font-bold mt-4"); ui.label("Live progress or stored cumulative energy for a completed connector session").classes("text-[13px] text-slate-500")
                    with ui.column().classes("w-full gap-2") as session_area:
                        session_select = ui.select(options={}, label="Active session").props("dense outlined").classes("w-full mt-2")
                        session_info = ui.label("").classes("text-[12px] text-slate-500")
                        curve_empty = ui.label("No active charging session").classes("empty-state text-[13px] text-slate-500 py-5 px-3 text-center w-full")
                        curve_chart = ui.echart(_chart_options()).classes("w-full h-52")
                    ui.separator().classes("mt-4"); ui.label("Station History (selected run)").classes("text-[15px] font-bold mt-4")
                    history_fields = {name: _detail_field(ui, name, accent=name in {"Delivered Energy", "Recorded Cost"}) for name in ("Completed Sessions", "Delivered Energy", "Recorded Cost", "Average Duration")}
                    ui.label("Historical Price Trend (simulated)").classes("text-[13px] font-semibold mt-3")
                    station_price_chart = ui.echart(_price_chart(())).classes("w-full h-40")
                    station_price_empty = ui.label("No price history for this station in the selected run.").classes("empty-state text-[14px] text-slate-500 p-3 text-center w-full")
        with ui.card().classes("panel-card w-full p-4 mt-4"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("Historical Analytics").classes("section-heading"); ui.label("Charging activity and trends for the selected simulation.").classes("text-[13px] text-slate-500")
                analytics_value = ui.label("No Event Data" if not events.has_event_data else "Selected-run completed-session summary").classes("text-sm font-semibold text-primary")
            analytics_summary_labels = {}
            with ui.row().classes("w-full gap-3 flex-wrap mt-3"):
                for title, value, hint in (("Completed Sessions", "N/A" if events.completed_sessions is None else str(events.completed_sessions), "session_end events"), ("Total Delivered Energy", "N/A" if events.analytics.delivered_energy_kwh is None else f"{events.analytics.delivered_energy_kwh:.2f} kWh", "completed sessions only"), ("Total Recorded Cost", "N/A" if events.analytics.recorded_cost_aud is None else f"${events.analytics.recorded_cost_aud:.2f}", "AUD, completed sessions"), ("Average Session Duration", "N/A" if events.analytics.average_duration_minutes is None else f"{events.analytics.average_duration_minutes:.1f} min", "completed sessions only")):
                    with ui.card().classes("metric-card history-summary flex-1 min-w-52"):
                        ui.label(title).classes("metric-title"); analytics_summary_labels[title] = ui.label(value).classes("text-[24px] font-bold text-slate-800 mt-1"); ui.label(hint).classes("metric-hint")
            with ui.row().classes("w-full gap-4 flex-nowrap max-lg:flex-wrap mt-4"):
                with ui.card().classes("chart-card border border-slate-200 shadow-none p-3"):
                    ui.label("Events by Type").classes("text-[17px] font-bold"); ui.label("Persisted simulated events in the selected run.").classes("text-[13px] text-slate-500")
                    event_type_chart = ui.echart(_event_chart(events.analytics.event_type_counts)).classes("w-full chart-frame")
                with ui.card().classes("chart-card border border-slate-200 shadow-none p-3"):
                    ui.label("Top 10 Stations by Completed Sessions").classes("text-[17px] font-bold"); ui.label("Ranked by session_end records in the selected run.").classes("text-[13px] text-slate-500")
                    stations_index = {s.charger.charger_id:s for s in snapshot.stations}
                    top_station_chart = ui.echart(_top_station_chart(events.analytics.top_station_sessions, stations_index)).classes("w-full chart-frame")
    view = DashboardView(snapshot, active_sessions_label, average_price_label, completed_sessions_label, last_event_label, event_notice, analytics_value, selection_intro, selection_body, station_title, station_subtitle, station_fields, session_area, session_select, curve_chart, curve_empty, session_info=session_info, debug_label=debug_label, live_mode=live_mode, mode_badge=mode_badge, live_button=live_button, on_run_change=load_run, time_zone=time_zone)
    selection_body.set_visibility(False); session_area.set_visibility(False); curve_chart.set_visibility(False); station_price_chart.set_visibility(False)
    clear_button.on_click(view.clear_selection); session_select.on_value_change(lambda e: view._show_curve(e.value))
    run_selector.on_value_change(lambda e: view.select_history_run(str(e.value)))
    live_button.on_click(view.return_to_live); live_button.set_visibility(not live_mode)
    view.charging_map, view.filter_count_label = charging_map, filter_count
    view.stations_by_id, view.history_fields = {station.charger.charger_id: station for station in snapshot.stations}, history_fields
    view.analytics_charts["Price History"], view.analytics_charts["Price Empty"] = station_price_chart, station_price_empty
    view.analytics_charts["Events by Type"], view.analytics_charts["Top Stations"] = event_type_chart, top_station_chart
    view.analytics_summary_labels = analytics_summary_labels
    view.run_selector = run_selector
    view.run_selector_run_ids = tuple(events.run_ids)
    view.live_run_id = events.run_id if live_mode else (events.run_ids[0] if events.run_ids else None)
    view.connection_badge = connection_badge
    view.snapshot_summary_label = snapshot_summary_label
    view.filter_controls = {"search": search_input, "coverage": coverage_filter, "type": type_filter, "operator": operator_filter, "power": power_filter, "connector": connector_filter, "status": status_filter}
    for control in (coverage_filter, type_filter, operator_filter, power_filter, connector_filter, status_filter): control.on_value_change(lambda _e: view.apply_filters())
    search_input.on("keydown.enter", lambda _e: view.search_and_select())
    search_button.on_click(view.search_and_select); reset_button.on_click(view.reset_filters)
    # ``station-select`` is emitted by the exact GenericLayer, not inferred from
    # the map's propagated click. Markers disable bubbling, leaving map-click for
    # genuine blank-map clicks only.
    charging_map.on("station-select", lambda e: view.select_marker(_marker_id_from_event(e)))
    charging_map.on("map-click", lambda _e: view.select_marker(None))
    if debug:
        charging_map.on("map-ready", lambda e: debug_label.set_text(f"Debug: Leaflet ready at {e.args.get('width')}×{e.args.get('height')} px."))
        charging_map.on("map-size", lambda e: debug_label.set_text(f"Debug: Leaflet resized to {e.args.get('width')}×{e.args.get('height')} px."))
    bindings: list[dict[str, str]] = []
    for station in snapshot.mappable_stations:
        layer = charging_map.generic_layer(name="circleMarker", args=[[station.charger.latitude, station.charger.longitude], {**_marker_style(station, events), "bubblingMouseEvents": False}])
        marker_id = str(layer.id)
        view.marker_layers[marker_id] = (station, layer); view.marker_id_by_charger[station.charger.charger_id] = marker_id
        bindings.append({"id": marker_id, "popup": _popup_html(station, events),
                         "tooltip": _text(station.charger.station_name, f"Station #{station.charger.charger_id}")})
    charging_map.on("init", lambda: charging_map.run_method("configure_layers", bindings))
    return view


def create_dashboard(ui, *, db_path: str | Path = DB_DATA, run_id: str | None = None, debug: bool = False,
                     time_zone: str = "UTC", snapshot_loader: Callable[..., DashboardSnapshot] = load_dashboard_snapshot):
    """Create a full-width dashboard or an actionable Assignment 1 database error page."""
    time_zone = resolve_display_timezone(time_zone)
    try:
        logger.info("Dashboard loader requested run_id=%s", run_id)
        snapshot = snapshot_loader(db_path, run_id=run_id)
        logger.info("Dashboard loader resolved run_id=%s", snapshot.events.run_id)
    except FileNotFoundError:
        _add_styles(ui)
        with ui.column().classes("w-full max-w-2xl mx-auto mt-24 p-6"):
            ui.icon("database", color="negative").classes("text-5xl"); ui.label("Charging network database is unavailable").classes("text-2xl font-semibold"); ui.label("Please restore the local charging-network database, then restart the dashboard.").classes("text-slate-600 whitespace-pre-wrap")
        return None
    except Exception as exc:
        _add_styles(ui)
        with ui.column().classes("w-full max-w-2xl mx-auto mt-24 p-6"):
            ui.icon("error_outline", color="negative").classes("text-5xl"); ui.label("Unable to load dashboard data").classes("text-2xl font-semibold"); ui.label(f"{type(exc).__name__}: {exc}").classes("text-slate-600 break-all")
        return None
    def load_run(selected: str) -> DashboardSnapshot:
        return snapshot_loader(db_path, run_id=selected)

    return _build_loaded_page(ui, snapshot, load_run, debug=debug, live_mode=run_id is None, time_zone=time_zone)


def create_marker_debug_page(ui) -> None:
    """Two-marker diagnostic page for manually validating layer-to-server events.

    It contains no database records or sensitive data. Remove this route once the
    browser-side confirmation for the installed NiceGUI version is complete.
    """
    _add_styles(ui)
    ui.label("Leaflet Marker Event Diagnostic").classes("text-xl font-bold m-5")
    ui.label("Click either marker. The line below must show its exact GenericLayer ID and matching test charger ID. Click empty map to test clearing.").classes("text-[13px] text-slate-600 mx-5 mb-3")
    status = ui.label("Debug: waiting for a marker or blank-map click.").classes("text-[13px] font-mono mx-5 mb-3")
    marker_map = DashboardLeaflet(center=(-33.86, 151.20), zoom=11).classes("w-[min(900px,calc(100vw-40px))] h-[560px] mx-5")
    layers: dict[str, int] = {}
    for charger_id, name, lat, lng in ((900001, "Test Alpha", -33.86, 151.20), (900002, "Test Bravo", -33.89, 151.16)):
        layer = marker_map.generic_layer(name="circleMarker", args=[[lat, lng], {"radius": 10, "color": CHARGING_MARKER, "fillColor": CHARGING_MARKER, "fillOpacity": 0.85, "bubblingMouseEvents": False}])
        layers[str(layer.id)] = charger_id
        layer.run_method("bindPopup", f"{name} · test charger {charger_id}")

    def report_marker(event) -> None:
        marker_id = _marker_id_from_event(event)
        charger_id = layers.get(marker_id or "")
        fields = event.args if isinstance(event.args, dict) else {"raw": event.args}
        status.set_text(f"Debug: Python received marker_id={marker_id}; mapped_charger_id={charger_id}; event={fields}")

    marker_map.on("station-select", report_marker)
    marker_map.on("map-click", lambda _event: status.set_text("Debug: Python received a blank-map click; no marker selected."))
