"""Map-centric NiceGUI presentation layer for the NSW EV Charging Dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import json
import logging
from typing import Callable
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from view.dashboard_data import DashboardSnapshot, DashboardStation
from view.dashboard_leaflet import DashboardLeaflet
from view.dashboard_model import ActiveSession, ConnectorView, DashboardEventSnapshot, PricePoint

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


def _metric_card(ui, title: str, value: str, icon: str, hint: str):
    with ui.card().classes("metric-card flex-1 min-w-52"):
        with ui.row().classes("w-full items-start justify-between no-wrap"):
            with ui.column().classes("gap-0"):
                ui.label(title).classes("metric-title")
                label = ui.label(value).classes("metric-value")
                ui.label(hint).classes("metric-hint")
            ui.icon(icon, color="primary").classes("text-2xl")
    return label


def _detail_field(ui, title: str, *, accent: bool = False, wide: bool = False):
    with ui.column().classes("detail-field gap-0" + (" detail-wide" if wide else "")):
        ui.label(title).classes("detail-label")
        value = ui.label("—").classes("detail-value" + (" detail-accent" if accent else ""))
    return value


def _event_chart(counts: dict[str, int]):
    labels = ["Price updates", "Session starts", "Meter events", "Session ends"]
    values = [counts.get(key, 0) for key in ("price_update", "session_start", "meter", "session_end")]
    return {"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "textStyle": {"fontSize": 13}}, "grid": {"left": 108, "right": 45, "top": 20, "bottom": 30}, "xAxis": {"type": "value", "name": "Events", "axisLabel": {"fontSize": 13}}, "yAxis": {"type": "category", "data": labels, "axisLabel": {"fontSize": 13}}, "series": [{"type": "bar", "data": [{"value": v, "itemStyle": {"color": c}} for v,c in zip(values, ["#16875D", "#2563EB", "#7C3AED", "#F59E0B"])], "label": {"show": True, "position": "right", "fontSize": 13}}]}


def _top_station_chart(top: tuple[tuple[int, int], ...], stations: dict[int, DashboardStation]):
    ordered = tuple(reversed(top)); labels = [f"{_text(stations.get(cid).charger.station_name if cid in stations else None, f'Station {cid}')} (#{cid})" for cid, _ in ordered]
    return {"tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, "textStyle": {"fontSize": 13}}, "grid": {"left": 170, "right": 45, "top": 20, "bottom": 34}, "xAxis": {"type": "value", "name": "Completed Sessions", "axisLabel": {"fontSize": 13}}, "yAxis": {"type": "category", "data": labels, "axisLabel": {"fontSize": 12, "width": 155, "overflow": "truncate"}}, "series": [{"type": "bar", "data": [v for _,v in ordered], "itemStyle": {"color": "#2563EB"}, "label": {"show": True, "position": "right", "fontSize": 13}}]}


def _replace_chart_options(chart, new_options: dict) -> None:
    """Replace NiceGUI 3.18 EChart options without assigning its read-only property."""
    chart.options.clear()
    chart.options.update(new_options)
    chart.update()


def _set_chart_options(chart, new_options: dict) -> None:
    """Send options only when they changed, so an untouched connector costs nothing per event."""
    if chart.options != new_options:
        _replace_chart_options(chart, new_options)


CONNECTOR_STATUS = {"charging": ("Charging", CHARGING_MARKER), "available": ("Available", AVAILABLE_MARKER),
                    "unknown": ("No data", UNKNOWN_MARKER)}
SOC_COLOR, ONGOING_COLOR, ENERGY_COLOR, IDLE_COLOR, PRICE_COLOR = "#7C3AED", "#86C9AE", "#2563EB", "#CBD5E1", "#F59E0B"
WHOLESALE_COLOR = "#64748b"
AXIS_LABEL, SPLIT_LINE = {"color": "#64748b", "fontSize": 11}, {"lineStyle": {"color": "#e2e8f0"}}
# Legends as (series name, colour, dashed). They are HTML above the chart, which wraps onto more
# lines when the chart is narrow; ECharts cannot make room for a legend that wraps.
TREND_LEGEND = (("Power (kW)", CHARGING_MARKER, False), ("SoC (%)", SOC_COLOR, True))
SESSION_LEGEND = (("Power (kW)", CHARGING_MARKER, False), ("Energy (kWh)", ENERGY_COLOR, False), ("SoC (%)", SOC_COLOR, True))
PRICE_LEGEND = (("Retail price", PRICE_COLOR, False), ("Wholesale (NEM)", WHOLESALE_COLOR, True))
# Clicking an HTML legend item shows or hides its series through the chart's hidden ECharts legend.
_LEGEND_TOGGLE = ("(event) => {{ const item = event.currentTarget; item.classList.toggle('off'); "
                  "const chart = item.closest('.legend-chart').querySelector('.nicegui-echart'); "
                  "getElement(chart.id.slice(1)).chart.dispatchAction({{type: 'legendToggleSelect', name: {name}}}); }}")
# The "-" point that breaks the lines at a session's start has no reading to list.
_TREND_TOOLTIP = ("params => { const rows = params.filter(p => p.value[1] !== '-'); return params[0].axisValueLabel + "
                  "(rows.length ? rows.map(p => '<br/>' + p.marker + p.seriesName + ': ' + p.value[1]).join('') "
                  ": '<br/>Plugged in, no meter reading yet'); }")


def _clock(value, zone: str | None = "UTC") -> str:
    """A compact display-zone time for the narrow connector panels."""
    if value is None: return "N/A"
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return value.astimezone(_timezone(zone)).strftime("%d %b %H:%M")


def _wall_ms(value, zone: str | None = "UTC") -> int:
    """Epoch ms of the display zone's wall-clock time, which an ECharts time axis with useUTC labels as is."""
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return round(value.astimezone(_timezone(zone)).replace(tzinfo=timezone.utc).timestamp() * 1000)


# A chart's time axis follows the chart's own events. It ends at the latest of them, so it stops
# while none arrives and moves on with the next one. A stretch with no event for longer than
# IDLE_INTERVALS meter intervals (and MIN_IDLE) is idle, and is cut out of the axis.
IDLE_INTERVALS, MIN_IDLE, DEFAULT_METER_INTERVAL = 3, timedelta(minutes=10), timedelta(minutes=5)
BREAK_GAP = "1.5%"  # The width an idle stretch keeps, as a share of the axis.
# Wall-clock labels ("07:55", or the date at midnight) for the useUTC time axes, whose cut
# edges would otherwise show seconds.
_TIME_LABEL = ("value => { const time = new Date(value); const pad = n => String(n).padStart(2, '0'); "
               "return time.getUTCHours() || time.getUTCMinutes() ? pad(time.getUTCHours()) + ':' + pad(time.getUTCMinutes()) "
               ": time.getUTCDate() + ' ' + ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][time.getUTCMonth()]; }")


def _meter_interval(meter_points) -> timedelta:
    """The usual time between a session's meter readings, given each session's readings."""
    gaps = sorted(later.event_ts - earlier.event_ts for points in meter_points for earlier, later in zip(points, points[1:]))
    return gaps[len(gaps) // 2] if gaps else DEFAULT_METER_INTERVAL


def _event_axis(times, interval: timedelta, zone: str | None = "UTC") -> dict:
    """A time axis from the first to the latest of a chart's event times, with its idle stretches cut out.

    A cut leaves one meter interval either side of the events around it, so an event between
    two idle stretches, such as an hourly price update overnight, still has room to show.
    """
    times = sorted(set(times))
    axis = {"type": "time", "axisLabel": {**AXIS_LABEL, "hideOverlap": True, ":formatter": _TIME_LABEL}}
    if not times:
        return axis
    idle = max(IDLE_INTERVALS * interval, MIN_IDLE)
    end = max(times[-1], times[0] + timedelta(minutes=1))  # A single event still gets a visible axis.
    return {**axis, "min": _wall_ms(times[0], zone), "max": _wall_ms(end, zone),
            "breaks": [{"start": _wall_ms(earlier + interval, zone), "end": _wall_ms(later - interval, zone), "gap": BREAK_GAP}
                       for earlier, later in zip(times, times[1:]) if later - earlier > idle],
            # A break opened by a click would close again at the next event's update.
            "breakArea": {"expandOnClick": False}}


def _period(start, end, zone: str | None = "UTC") -> str:
    """'15 Sep 07:55 – 08:22', with the end's date only when it differs; no end means still running."""
    if end is None:
        return f"{_clock(start, zone)} – now"
    same_day = start is not None and _clock(start, zone)[:6] == _clock(end, zone)[:6]
    return f"{_clock(start, zone)} – {_clock(end, zone)[7:] if same_day else _clock(end, zone)}"


def _duration(minutes: float) -> str:
    hours, rest = divmod(round(minutes), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def _minutes_between(start, end) -> float | None:
    return None if start is None or end is None else max((end - start).total_seconds() / 60, 0)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@dataclass(frozen=True)
class ConnectorHeader:
    """What a connector panel shows while it is collapsed."""
    status: str
    label: str
    color: str
    headline: str
    summary: str
    detail: str
    soc: float | None  # 0..1 for the state-of-charge bar; None hides it.


def _connector_header(connector: ConnectorView, zone: str | None = "UTC") -> ConnectorHeader:
    label, color = CONNECTOR_STATUS[connector.status]
    active, completed = connector.active, connector.completed
    if active is not None:
        reading = [f"{active.energy_kwh:.2f} kWh" if active.energy_kwh is not None else None,
                   f"SoC {active.soc_pct:.0f}%" if active.soc_pct is not None else None]
        reading = [part for part in reading if part] or ["Awaiting first meter reading"]
        if active.price_per_kwh is not None:
            reading.append(_price(active.price_per_kwh))
        return ConnectorHeader(connector.status, label, color, _power(active.power_kw) if active.power_kw is not None else "",
                               f"{_text(active.vehicle_model, 'Vehicle')} · plugged in {_clock(active.session_start_ts, zone)}",
                               " · ".join(reading), None if active.soc_pct is None else active.soc_pct / 100)
    if connector.status == "available":
        if not completed:
            return ConnectorHeader(connector.status, label, color, "", "Not used in this run yet", "", None)
        energy = sum(session.delivered_energy_kwh or 0 for session in completed)
        return ConnectorHeader(connector.status, label, color, "", f"Free since {_clock(completed[-1].session_end_ts, zone)}",
                               f"{_plural(len(completed), 'session')} · {energy:.2f} kWh delivered", None)
    return ConnectorHeader(connector.status, label, color, "", "No events for this station in the selected run", "", None)


def _connector_stats(connector: ConnectorView) -> str:
    """One line summarising a connector's sessions in the run."""
    completed = connector.completed
    occupied = sum(_minutes_between(session.session_start_ts, session.span_end_ts) or 0 for session in connector.sessions)
    parts = [_plural(len(completed), "completed session") + (" + 1 active" if connector.active else ""),
             f"{sum(session.delivered_energy_kwh or 0 for session in completed):.2f} kWh delivered",
             f"${sum(session.recorded_cost_aud or 0 for session in completed):.2f} recorded",
             f"occupied {_duration(occupied)}"]
    return " · ".join(parts)


def _connector_trend_chart(connector: ConnectorView, zone: str | None = "UTC") -> dict:
    """Power and state of charge of every session on the connector's own event time, with occupied periods shaded."""
    power, soc, spans = [], [], []
    for session in connector.sessions:
        start, end = session.session_start_ts, session.span_end_ts
        if power and start is not None:  # Break the lines between sessions.
            power.append([_wall_ms(start, zone), "-"]); soc.append([_wall_ms(start, zone), "-"])
        for point in connector.meter_points.get(session.session_id, ()):
            x = _wall_ms(point.event_ts, zone)
            power.append([x, "-" if point.power_kw is None else point.power_kw])
            soc.append([x, "-" if point.soc_pct is None else point.soc_pct])
        if start is not None and end is not None:
            spans.append([{"xAxis": _wall_ms(start, zone)}, {"xAxis": _wall_ms(end, zone)}])
    return {"animation": False, "useUTC": True, "grid": {"left": 42, "right": 42, "top": 26, "bottom": 26},
            "legend": {"show": False},  # TREND_LEGEND is drawn above the chart.
            "tooltip": {"trigger": "axis", ":formatter": _TREND_TOOLTIP},
            "xAxis": _event_axis(connector.event_times(), _meter_interval(connector.meter_points.values()), zone),
            "yAxis": [{"type": "value", "name": "kW", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
                      {"type": "value", "name": "SoC %", "min": 0, "max": 100, "axisLabel": AXIS_LABEL, "splitLine": {"show": False}}],
            "series": [{"name": "Power (kW)", "type": "line", "symbolSize": 4, "data": power,
                        "lineStyle": {"color": CHARGING_MARKER, "width": 2}, "itemStyle": {"color": CHARGING_MARKER},
                        "markArea": {"silent": True, "itemStyle": {"color": "rgba(22,135,93,0.08)"}, "data": spans}},
                       {"name": "SoC (%)", "type": "line", "yAxisIndex": 1, "symbolSize": 4, "data": soc,
                        "lineStyle": {"color": SOC_COLOR, "width": 2, "type": "dashed"}, "itemStyle": {"color": SOC_COLOR}}]}


def _connector_sessions_chart(connector: ConnectorView, zone: str | None = "UTC") -> dict:
    """Energy delivered by each session; an active session shows its energy so far."""
    labels, bars = [], []
    for session in connector.sessions:
        ongoing = session.session_end_ts is None
        energy = session.energy_kwh if ongoing else session.delivered_energy_kwh
        figures = [f"{energy:.2f} kWh{' so far' if ongoing else ''}" if energy is not None else "No energy reading yet"]
        if not ongoing:
            figures += [f"${session.recorded_cost_aud:.2f}" if session.recorded_cost_aud is not None else None,
                        f"{session.duration_minutes:.0f} min charging" if session.duration_minutes is not None else None]
        # The tooltip is HTML, and the vehicle model arrives over MQTT.
        tip = "<br/>".join((f"<b>{escape(_text(session.vehicle_model, 'Vehicle'))}</b>",
                            _period(session.session_start_ts, session.session_end_ts, zone),
                            " · ".join(part for part in figures if part)))
        labels.append(_clock(session.session_start_ts, zone))
        bars.append({"value": "-" if energy is None else round(energy, 2), "tip": tip, "session": session.session_id,
                     "itemStyle": {"color": ONGOING_COLOR if ongoing else CHARGING_MARKER}})
    return {"animation": False, "grid": {"left": 42, "right": 12, "top": 26, "bottom": 26},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}, ":formatter": "params => params[0].data.tip"},
            "xAxis": {"type": "category", "data": labels, "axisLabel": {**AXIS_LABEL, "hideOverlap": True}},
            "yAxis": {"type": "value", "name": "kWh", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
            "series": [{"name": "Energy", "type": "bar", "barMaxWidth": 22, "data": bars, "cursor": "pointer"}]}


def _session_options(connector: ConnectorView, zone: str | None = "UTC") -> dict[str, str]:
    """Dropdown labels by session_id: the current session first, then completed sessions, newest first."""
    options = {}
    for session in reversed(connector.sessions):
        vehicle = _text(session.vehicle_model, "Vehicle")
        if session.session_end_ts is None:
            options[session.session_id] = f"Current · {vehicle} · since {_clock(session.session_start_ts, zone)}"
        else:
            energy = "" if session.delivered_energy_kwh is None else f" · {session.delivered_energy_kwh:.2f} kWh"
            options[session.session_id] = f"{_period(session.session_start_ts, session.session_end_ts, zone)} · {vehicle}{energy}"
    return options


def _pick_session(options: dict[str, str], selected: str | None, follow: bool) -> tuple[str | None, bool]:
    """The session to show, and whether the panel keeps following the newest one.

    A panel follows the newest session, so a session that starts takes over, until someone
    picks an older one. That choice stays until it is no longer offered, as after a run change.
    """
    newest = next(iter(options), None)
    if follow or selected not in options:
        return newest, True
    return selected, selected == newest


def _session_details(session: ActiveSession, zone: str | None = "UTC") -> str:
    vehicle = _text(session.vehicle_model, "Vehicle")
    price = None if session.price_per_kwh is None else _price(session.price_per_kwh)
    if session.session_end_ts is None:
        parts = [vehicle, f"plugged in {_clock(session.session_start_ts, zone)}", price,
                 None if session.energy_kwh is None else f"{session.energy_kwh:.2f} kWh so far",
                 None if session.soc_pct is None else f"SoC {session.soc_pct:.0f}%"]
    else:
        idle = _minutes_between(session.charge_end_ts, session.session_end_ts)
        parts = [vehicle, _period(session.session_start_ts, session.session_end_ts, zone),
                 None if session.delivered_energy_kwh is None else f"{session.delivered_energy_kwh:.2f} kWh",
                 None if session.recorded_cost_aud is None else f"${session.recorded_cost_aud:.2f}", price,
                 None if session.duration_minutes is None else f"charged {_duration(session.duration_minutes)}",
                 None if idle is None else f"idle {_duration(idle)}"]
    return " · ".join(part for part in parts if part)


def _session_chart(connector: ConnectorView, session_id: str | None, zone: str | None = "UTC") -> dict:
    """One session's power, cumulative energy and state of charge from plug-in to unplug (or its latest event)."""
    session = next((item for item in connector.sessions if item.session_id == session_id), None)
    power, energy, soc, idle = [], [], [], []
    start = None if session is None else session.session_start_ts
    if start is not None:  # Nothing is delivered at plug-in; there is no power or SoC reading yet.
        x = _wall_ms(start, zone)
        power.append([x, "-"]); energy.append([x, 0]); soc.append([x, "-"])
    for point in connector.meter_points.get(session_id, ()) if session else ():
        x = _wall_ms(point.event_ts, zone)
        power.append([x, "-" if point.power_kw is None else point.power_kw])
        energy.append([x, point.energy_kwh])
        soc.append([x, "-" if point.soc_pct is None else point.soc_pct])
    charge_end = None if session is None else session.charge_end_ts
    if charge_end is not None and session.delivered_energy_kwh is not None:  # The session total, when charging stopped.
        x = _wall_ms(charge_end, zone)
        power.append([x, "-"]); energy.append([x, session.delivered_energy_kwh]); soc.append([x, "-"])
        if session.session_end_ts is not None and session.session_end_ts > charge_end:
            idle.append([{"xAxis": x, "name": "Idle"}, {"xAxis": _wall_ms(session.session_end_ts, zone)}])
    # The session's events, and when charging stopped, which has a point of its own.
    times = (connector.event_times(session_id) if session else ()) + ((charge_end,) if charge_end is not None else ())
    return {"animation": False, "useUTC": True, "grid": {"left": 42, "right": 42, "top": 26, "bottom": 26},
            "legend": {"show": False},  # SESSION_LEGEND is drawn above the chart.
            "tooltip": {"trigger": "axis", ":formatter": _TREND_TOOLTIP},
            "xAxis": _event_axis(times, _meter_interval((connector.meter_points.get(session_id, ()),)), zone),
            "yAxis": [{"type": "value", "name": "kW · kWh", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
                      {"type": "value", "name": "SoC %", "min": 0, "max": 100, "axisLabel": AXIS_LABEL, "splitLine": {"show": False}}],
            "series": [{"name": "Power (kW)", "type": "line", "symbolSize": 4, "data": power,
                        "lineStyle": {"color": CHARGING_MARKER, "width": 2}, "itemStyle": {"color": CHARGING_MARKER},
                        # The label stays inside the shaded area, clear of the axis names above the grid.
                        "markArea": {"silent": True, "itemStyle": {"color": "rgba(148,163,184,0.18)"},
                                     "label": {"position": "insideTop", "color": "#64748b", "fontSize": 11}, "data": idle}},
                       {"name": "Energy (kWh)", "type": "line", "symbolSize": 4, "data": energy,
                        "lineStyle": {"color": ENERGY_COLOR, "width": 2}, "itemStyle": {"color": ENERGY_COLOR},
                        "areaStyle": {"color": "rgba(37,99,235,0.08)"}},
                       {"name": "SoC (%)", "type": "line", "yAxisIndex": 1, "symbolSize": 4, "data": soc,
                        "lineStyle": {"color": SOC_COLOR, "width": 2, "type": "dashed"}, "itemStyle": {"color": SOC_COLOR}}]}


def _legend_chart(ui, options: dict, legend: tuple[tuple[str, str, bool], ...], height: str):
    """An echart below its HTML legend, which wraps onto more lines when the chart is narrow."""
    with ui.element("div").classes("legend-chart w-full"):
        with ui.element("div").classes("chart-legend"):
            for name, color, dashed in legend:
                with ui.element("span").classes("chart-legend-item").on(
                        "click", js_handler=_LEGEND_TOGGLE.format(name=json.dumps(name))):
                    ui.element("span").classes("chart-legend-swatch").style(
                        f"border-top:2px {'dashed' if dashed else 'solid'} {color}")
                    ui.label(name)
        return ui.echart(options).classes(f"w-full {height}")


class ConnectorPanel:
    """One connector's expansion panel: live state in its header, its sessions and trends when expanded.

    The charts are built the first time the panel opens. After that every render() updates the
    header and, while the panel is open, the session dropdown and charts in place.
    """

    def __init__(self, ui, connector_no: int):
        self._ui, self._connector, self._zone, self._status, self._history = ui, None, "UTC", None, None
        self._session_id, self._follow, self._syncing = None, True, False
        with ui.expansion().classes("connector-panel w-full") as self.expansion:
            with self.expansion.add_slot("header"):
                with ui.row().classes("w-full items-center no-wrap gap-3"):
                    self._icon = ui.icon("ev_station").classes("text-2xl")
                    with ui.column().classes("gap-0 grow min-w-0"):
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.label(f"Connector {connector_no}").classes("connector-title")
                            self._chip = ui.label("—").classes("connector-chip")
                        self._summary = ui.label("").classes("connector-line")
                        self._detail = ui.label("").classes("connector-line")
                        self._soc = ui.linear_progress(0, show_value=False, size="4px").classes("connector-soc")
                    self._headline = ui.label("").classes("connector-headline")
            self._body = ui.column().classes("w-full gap-1")
        self.expansion.on_value_change(lambda event: self._render_history() if event.value else None)

    def render(self, connector: ConnectorView, zone: str) -> None:
        self._connector, self._zone = connector, zone
        header = _connector_header(connector, zone)
        if header.status != self._status:
            self._status = header.status
            self._icon.style(replace=f"color:{header.color}")
            self._chip.style(replace=f"background:{header.color}")
        self._chip.set_text(header.label)
        self._headline.set_text(header.headline)
        self._summary.set_text(header.summary)
        self._detail.set_text(header.detail)
        self._detail.set_visibility(bool(header.detail))
        self._soc.set_visibility(header.soc is not None)
        self._soc.set_value(0 if header.soc is None else header.soc)  # The next session's bar fills from empty.
        if self.expansion.value:
            self._render_history()

    def _render_history(self) -> None:
        if self._connector is None:
            return
        ui, connector = self._ui, self._connector
        if self._history is None:
            with self._body:
                stats = ui.label("").classes("connector-stats")
                empty = ui.label("No charging session on this connector in the selected run.").classes(
                    "empty-state text-[13px] text-slate-500 py-4 px-3 text-center w-full")
                with ui.column().classes("w-full gap-0") as charts:
                    ui.label("Session").classes("connector-chart-title")
                    select = ui.select({}, label="Current or past session").props("dense outlined options-dense").classes("w-full mt-1")
                    details = ui.label("").classes("connector-session-info")
                    session_chart = _legend_chart(ui, _session_chart(connector, None, self._zone), SESSION_LEGEND, "h-48")
                    ui.label("All sessions: power and state of charge").classes("connector-chart-title")
                    trend = _legend_chart(ui, _connector_trend_chart(connector, self._zone), TREND_LEGEND, "h-48")
                    ui.label("Energy per session (click a bar to open it)").classes("connector-chart-title")
                    sessions = ui.echart(_connector_sessions_chart(connector, self._zone)).classes("w-full h-40")
            select.on_value_change(lambda event: self._choose(event.value))
            sessions.on_point_click(lambda event: self._choose(event.data.get("session") if isinstance(event.data, dict) else None))
            self._history = stats, empty, charts, select, details, session_chart, trend, sessions
        stats, empty, charts, select, details, session_chart, trend, sessions = self._history
        stats.set_text(_connector_stats(connector))
        empty.set_visibility(not connector.sessions)
        charts.set_visibility(bool(connector.sessions))
        options = _session_options(connector, self._zone)
        self._session_id, self._follow = _pick_session(options, self._session_id, self._follow)
        self._syncing = True  # Showing the server's choice is not someone picking a session.
        try:
            if select.options != options:
                select.set_options(options, value=self._session_id)
            elif select.value != self._session_id:
                select.value = self._session_id
        finally:
            self._syncing = False
        session = next((item for item in connector.sessions if item.session_id == self._session_id), None)
        details.set_text("" if session is None else _session_details(session, self._zone))
        _set_chart_options(session_chart, _session_chart(connector, self._session_id, self._zone))
        _set_chart_options(trend, _connector_trend_chart(connector, self._zone))
        _set_chart_options(sessions, _connector_sessions_chart(connector, self._zone))

    def _choose(self, session_id: str | None) -> None:
        """Someone picked a session, from the dropdown or a bar."""
        if self._syncing or session_id is None or session_id == self._session_id:
            return
        self._session_id, self._follow = session_id, False
        self._render_history()


# A charger's state history: three charts on the same ChargerTimeline, so they line up.
_STATE_GRID = {"left": 46, "right": 16, "top": 26, "bottom": 26}
# A connector-timeline block: value is [row, start, end] with times on x and the connector row on y.
_TIMELINE_BLOCK = ("(params, api) => { const start = api.coord([api.value(1), api.value(0)]); "
                   "const end = api.coord([api.value(2), api.value(0)]); "
                   "const height = Math.min(api.size([0, 1])[1] * 0.6, 14); "
                   "return {type: 'rect', shape: {x: start[0], y: start[1] - height / 2, "
                   "width: Math.max(end[0] - start[0], 2), height: height}, style: api.style()}; }")


@dataclass(frozen=True)
class ChargerTimeline:
    """The time axis a charger's state charts share: the charger's own events, idle stretches cut."""
    times: tuple  # When the charger's events happened, oldest first.
    axis: dict

    @property
    def start(self):
        return self.times[0]

    @property
    def end(self):
        return self.times[-1]


def _charger_timeline(connectors: tuple[ConnectorView, ...], prices: tuple[PricePoint, ...],
                      zone: str | None = "UTC") -> ChargerTimeline | None:
    """The charger's price updates and every session event on its connectors; None without events."""
    times = tuple(sorted({point.event_ts for point in prices} | {ts for connector in connectors for ts in connector.event_times()}))
    if not times:
        return None
    interval = _meter_interval(points for connector in connectors for points in connector.meter_points.values())
    return ChargerTimeline(times, _event_axis(times, interval, zone))


def _occupancy_chart(connectors: tuple[ConnectorView, ...], capacity: int | None, timeline: ChargerTimeline,
                     zone: str | None = "UTC") -> dict:
    """Occupied connectors over the run: charger_state.active_sessions as it changed."""
    # Unplugging before plugging in at the same time, as the publisher orders them.
    changes = sorted([(session.session_end_ts, -1) for connector in connectors for session in connector.sessions
                      if session.session_end_ts is not None] +
                     [(session.session_start_ts, 1) for connector in connectors for session in connector.sessions
                      if session.session_start_ts is not None])
    level, steps = 0, [[_wall_ms(timeline.start, zone), 0]]
    for ts, change in changes:
        level += change
        x = _wall_ms(ts, zone)
        if steps[-1][0] == x:
            steps[-1][1] = level
        else:
            steps.append([x, level])
    if steps[-1][0] != _wall_ms(timeline.end, zone):  # The occupancy still holds at the charger's latest event.
        steps.append([_wall_ms(timeline.end, zone), level])
    plugs = capacity if isinstance(capacity, int) and capacity > 0 else None
    peak = max((value for _x, value in steps), default=0)
    return {"animation": False, "useUTC": True, "grid": _STATE_GRID, "tooltip": {"trigger": "axis"},
            "xAxis": timeline.axis,
            "yAxis": {"type": "value", "name": "Occupied", "min": 0, "max": max(plugs or 0, peak, 1), "minInterval": 1,
                      "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
            "series": [{"name": "Occupied connectors", "type": "line", "step": "end", "showSymbol": False, "data": steps,
                        "lineStyle": {"color": CHARGING_MARKER, "width": 2}, "itemStyle": {"color": CHARGING_MARKER},
                        "areaStyle": {"color": "rgba(22,135,93,0.12)"},
                        "markLine": {"silent": True, "symbol": "none", "lineStyle": {"color": FULL_MARKER, "type": "dashed"},
                                     "label": {"formatter": "{c} plugs", "position": "insideEndTop", "color": FULL_MARKER, "fontSize": 11},
                                     "data": [{"yAxis": plugs}] if plugs else []}}]}


def _connector_timeline_chart(connectors: tuple[ConnectorView, ...], timeline: ChargerTimeline,
                              zone: str | None = "UTC") -> dict:
    """When each connector was charging, idle while still plugged in, or in use now."""
    blocks = []
    for row, connector in enumerate(connectors):
        for session in connector.sessions:
            # A session still plugged in is in use up to the charger's latest event.
            start, end = session.session_start_ts, session.session_end_ts or timeline.end
            if start is None or end is None:
                continue
            # The tooltip is HTML, and the vehicle model arrives over MQTT.
            title = f"<b>Connector {connector.connector_no} · {escape(_text(session.vehicle_model, 'Vehicle'))}</b><br/>"
            if session.session_end_ts is None:
                parts = [(start, end, ONGOING_COLOR, f"In use {_period(start, None, zone)}")]
            else:
                charge_end = session.charge_end_ts if session.charge_end_ts is not None and start <= session.charge_end_ts <= end else end
                parts = [(start, charge_end, CHARGING_MARKER, f"Charging {_period(start, charge_end, zone)}"),
                         (charge_end, end, IDLE_COLOR, f"Idle, still plugged in {_period(charge_end, end, zone)}")]
            blocks += [{"value": [row, _wall_ms(begin, zone), _wall_ms(finish, zone)], "itemStyle": {"color": color},
                        "tip": title + what} for begin, finish, color, what in parts if finish > begin]
    return {"animation": False, "useUTC": True, "grid": {**_STATE_GRID, "top": 12},
            "tooltip": {"trigger": "item", ":formatter": "params => params.data.tip"},
            "xAxis": timeline.axis,
            "yAxis": {"type": "category", "inverse": True, "data": [str(connector.connector_no) for connector in connectors],
                      # Every connector's number while they fit; ECharts thins them out beyond that.
                      "axisLabel": {**AXIS_LABEL, "interval": 0 if len(connectors) <= 20 else "auto"},
                      "splitLine": {"show": True, "lineStyle": {"color": "#f1f5f9"}}},
            "series": [{"name": "Connector use", "type": "custom", ":renderItem": _TIMELINE_BLOCK,
                        "encode": {"x": [1, 2], "y": 0}, "data": blocks}]}


def _charger_price_chart(prices: tuple[PricePoint, ...], timeline: ChargerTimeline, zone: str | None = "UTC") -> dict:
    """The retail price and the NEM wholesale price each held from one price_update to the next."""
    end = _wall_ms(timeline.end, zone)
    retail = [[_wall_ms(point.event_ts, zone), point.price_per_kwh] for point in prices]
    wholesale = [[_wall_ms(point.event_ts, zone), point.wholesale_per_kwh] for point in prices
                 if point.wholesale_per_kwh is not None]
    for steps in (retail, wholesale):
        if steps and steps[-1][0] < end:  # The latest price still holds.
            steps.append([end, steps[-1][1]])
    # Both series are always there, as in PRICE_LEGEND, even before a wholesale price arrives.
    series = [{"name": "Retail price", "type": "line", "step": "end", "showSymbol": False, "data": retail,
               "lineStyle": {"color": PRICE_COLOR, "width": 2}, "itemStyle": {"color": PRICE_COLOR}},
              {"name": "Wholesale (NEM)", "type": "line", "step": "end", "showSymbol": False, "data": wholesale,
               "lineStyle": {"color": WHOLESALE_COLOR, "width": 1.5, "type": "dashed"}, "itemStyle": {"color": WHOLESALE_COLOR}}]
    return {"animation": False, "useUTC": True, "grid": _STATE_GRID, "tooltip": {"trigger": "axis"},
            "legend": {"show": False},  # PRICE_LEGEND is drawn above the chart.
            "xAxis": timeline.axis,
            "yAxis": {"type": "value", "name": "AUD/kWh", "scale": True, "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
            "series": series}


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
    connector_area: object
    connector_empty: object | None = None
    new_connector_panel: Callable[[int], object] | None = None  # Builds a panel inside connector_area.
    connector_panels: dict[int, object] = field(default_factory=dict)
    debug_label: object | None = None
    marker_layers: dict[str, tuple[DashboardStation, object]] = field(default_factory=dict)
    marker_id_by_charger: dict[int, str] = field(default_factory=dict)
    selected_charger_id: int | None = None
    charging_map: object | None = None
    filter_count_label: object | None = None
    filter_controls: dict[str, object] = field(default_factory=dict)
    stations_by_id: dict[int, DashboardStation] = field(default_factory=dict)
    history_fields: dict[str, object] = field(default_factory=dict)
    # The selected charger's state history: "occupancy", "timeline" and "price" charts, with
    # "area" holding them, "empty" shown instead without events, and "price_empty" without prices.
    state_charts: dict[str, object] = field(default_factory=dict)
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
    _connector_layout: tuple[int, tuple[int, ...]] | None = None

    def _set_marker_style(self, charger_id: int, *, selected: bool) -> None:
        entry = self.marker_layers.get(self.marker_id_by_charger.get(charger_id, ""))
        if entry:
            station, layer = entry
            layer.run_method("setStyle", _marker_style(station, self.snapshot.events, selected=selected))

    def _show_connectors(self, charger_id: int, connectors: tuple[ConnectorView, ...]) -> None:
        """Build a panel per connector for a newly selected station; afterwards update them in place.

        Updating in place keeps each panel open or closed across live events and run changes.
        """
        layout = charger_id, tuple(connector.connector_no for connector in connectors)
        if layout != self._connector_layout and self.new_connector_panel is not None:
            self.connector_area.clear()
            self.connector_panels = {number: self.new_connector_panel(number) for number in layout[1]}
            self._connector_layout = layout
        for connector in connectors:
            if panel := self.connector_panels.get(connector.connector_no):
                panel.render(connector, self.time_zone)
        if self.connector_empty is not None:
            self.connector_empty.set_visibility(not connectors)

    def _clear_connectors(self) -> None:
        self.connector_area.clear()
        self.connector_panels, self._connector_layout = {}, None

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
        self.selected_charger_id = None
        self.selection_intro.set_visibility(True)
        self.selection_body.set_visibility(False)
        self._clear_connectors()

    def show_station(self, station: DashboardStation) -> None:
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
        connectors = self.snapshot.events.connectors(charger.charger_id, charger.number_of_plugs)
        self._show_state_history(charger.number_of_plugs, connectors, history.price_points if history else ())
        self._show_connectors(charger.charger_id, connectors)

    def _show_state_history(self, capacity: int | None, connectors: tuple[ConnectorView, ...],
                            prices: tuple[PricePoint, ...]) -> None:
        charts = self.state_charts
        if not charts:
            return
        timeline = _charger_timeline(connectors, prices, self.time_zone)
        charts["area"].set_visibility(timeline is not None)
        charts["empty"].set_visibility(timeline is None)
        if timeline is None:
            return
        _set_chart_options(charts["occupancy"], _occupancy_chart(connectors, capacity, timeline, self.time_zone))
        _set_chart_options(charts["timeline"], _connector_timeline_chart(connectors, timeline, self.time_zone))
        _set_chart_options(charts["price"], _charger_price_chart(prices, timeline, self.time_zone))
        charts["price"].set_visibility(bool(prices))
        charts["price_empty"].set_visibility(not prices)

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
                self.show_station(station)

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
      .main-panels{display:grid;grid-template-columns:minmax(0,7fr) minmax(330px,3fr);grid-template-rows:minmax(clamp(760px,calc(100vh - 225px),900px),auto);align-items:stretch;gap:16px}.main-panels>.q-card{min-height:0;width:auto!important;margin:0;box-sizing:border-box}.map-card{min-width:0;display:flex!important;flex-direction:column!important;overflow:clip;box-sizing:border-box}.map-card>:not(.map-viewport){flex:0 0 auto}.map-viewport{position:relative;width:100%;min-width:0;max-width:100%;box-sizing:border-box;align-self:stretch;flex:1 1 auto;min-height:460px;overflow:hidden;border-radius:11px}.map-frame{width:100%!important;height:100%!important;min-height:0!important;display:block}.detail-card{min-width:0;overflow-y:auto;overflow-x:hidden;box-sizing:border-box;contain:size}.detail-field{padding:10px 0;border-bottom:1px solid #edf1ef}.detail-value{color:#23332c;font-size:15px;line-height:1.45}.detail-accent{color:#08794d;font-weight:700}.ev-popup{min-width:205px;color:#24342d;font-size:14px;line-height:1.5}.ev-popup strong{font-size:15px}.map-legend{position:absolute!important;z-index:750!important;pointer-events:none;background:rgba(255,255,255,.94);border:1px solid #dfe8e3;border-radius:8px;box-shadow:0 2px 8px rgba(15,60,45,.12);padding:8px 10px;font-size:13px;color:#334155}.legend-dot{height:9px;width:9px;border-radius:999px;display:inline-block;margin-right:6px}.empty-state{border:1px dashed #cad7d0;border-radius:10px;background:#f8fbf9}.section-heading{font-size:18px;font-weight:700;color:#1f342b}.chart-card{flex:1 1 0;min-width:420px}.chart-frame{height:310px}.history-summary{min-height:102px;padding:15px 18px}
      .detail-heading{color:#1f342b;font-size:15px;font-weight:700;margin-top:16px}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:16px;width:100%}.detail-wide{grid-column:1/-1}
      .connector-list{border:1px solid #dfe8e3;border-radius:12px;overflow:hidden;background:#fff}.connector-list:empty{display:none}.connector-panel+.connector-panel{border-top:1px solid #edf1ef}.connector-panel .q-item{padding:10px 12px}.connector-panel .nicegui-expansion-content{background:#f8fbf9;border-top:1px solid #edf1ef;padding:8px 12px 12px}
      .connector-title{color:#1f342b;font-size:15px;font-weight:700}.connector-chip{color:#fff;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;border-radius:999px;padding:0 8px;line-height:18px}.connector-line{width:100%;color:#64748b;font-size:12.5px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.connector-soc{margin-top:5px;border-radius:999px}.connector-headline{color:#172b25;font-size:18px;font-weight:750;white-space:nowrap}
      .connector-stats{color:#334155;font-size:13px;font-weight:600}.connector-session-info{color:#334155;font-size:12.5px;line-height:1.45;margin-top:4px}.timeline-legend{display:flex;flex-wrap:wrap;gap:2px 14px;color:#475569;font-size:12px;margin-top:2px}
      .chart-legend{display:flex;flex-wrap:wrap;gap:2px 14px;margin-top:2px}.chart-legend-item{display:inline-flex;align-items:center;gap:6px;color:#475569;font-size:12px;cursor:pointer;user-select:none}.chart-legend-item.off{opacity:.4}.chart-legend-swatch{width:16px;height:0}.connector-chart-title{color:#64748b;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;margin-top:8px}
      @media(max-width:480px){.detail-grid{grid-template-columns:1fr}}
      /* Side by side, the map card sets the row's height and grows when its filters wrap, so nothing in it is
         clipped (overflow:clip also stops focus from scrolling it); the details card scrolls within that height. */
      @media(max-width:1024px){.dashboard-shell{padding:13px}.main-panels{grid-template-columns:1fr;grid-template-rows:none}.main-panels>.q-card{height:auto;min-height:0}.map-viewport{height:600px;min-height:600px;flex:none}.detail-card{max-height:none;contain:none}}@media(max-width:780px){.dashboard-shell{padding:10px}.map-viewport{height:520px;min-height:520px}.chart-card{min-width:100%}}
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
                    with ui.row().classes("w-full items-start justify-between gap-2 no-wrap"):
                        with ui.column().classes("gap-0 min-w-0"):
                            station_title = ui.label("—").classes("text-xl font-bold text-primary")
                            station_subtitle = ui.label("—").classes("text-[13px] text-slate-500 mb-2")
                        clear_button = ui.button("Clear", icon="close").props("flat dense").classes("text-slate-600")
                    ui.label("Live Status").classes("detail-heading mt-1")
                    with ui.element("div").classes("detail-grid"):
                        station_fields = {name: _detail_field(ui, name, accent=True) for name in ("Charging Status", "Latest Price", "Occupied Ports", "Active Session Count", "Last Price Update", "Last Event")}
                    ui.label("Connectors").classes("detail-heading")
                    ui.label("Each connector's current state, updated by every event. Expand one for its trends in the selected run.").classes("text-[13px] text-slate-500 mb-2")
                    connector_area = ui.column().classes("connector-list w-full gap-0")
                    connector_empty = ui.label("No connector information for this station.").classes("empty-state text-[13px] text-slate-500 py-4 px-3 text-center w-full")
                    ui.label("Station Overview").classes("detail-heading")
                    with ui.element("div").classes("detail-grid"):
                        station_fields.update({name: _detail_field(ui, name, wide=name == "Address") for name in ("Address", "Operator", "Station ID", "Postcode", "LGA", "SA4 Region")})
                    ui.label("Charging Information").classes("detail-heading")
                    with ui.element("div").classes("detail-grid"):
                        station_fields.update({name: _detail_field(ui, name) for name in ("Charger Type", "Connector Type", "Number of Plugs", "Max Power")})
                    ui.separator().classes("mt-4"); ui.label("Station History (selected run)").classes("detail-heading")
                    with ui.element("div").classes("detail-grid"):
                        history_fields = {name: _detail_field(ui, name, accent=name in {"Delivered Energy", "Recorded Cost"}) for name in ("Completed Sessions", "Delivered Energy", "Recorded Cost", "Average Duration")}
                    ui.label("Charger State History").classes("detail-heading")
                    ui.label("How this charger's state changed in the selected run, updated by every event.").classes("text-[13px] text-slate-500")
                    with ui.column().classes("w-full gap-0") as state_area:
                        ui.label("Occupied connectors").classes("connector-chart-title")
                        occupancy_chart = ui.echart({"animation": False, "series": []}).classes("w-full h-36")
                        ui.label("Connector timeline").classes("connector-chart-title")
                        ui.html(f"<div class='timeline-legend'><span><span class='legend-dot' style='background:{CHARGING_MARKER}'></span>Charging</span>"
                                f"<span><span class='legend-dot' style='background:{IDLE_COLOR}'></span>Idle, still plugged in</span>"
                                f"<span><span class='legend-dot' style='background:{ONGOING_COLOR}'></span>In use now</span></div>")
                        timeline_chart = ui.echart({"animation": False, "series": []}).classes("w-full h-56")
                        ui.label("Price").classes("connector-chart-title")
                        price_chart = _legend_chart(ui, {"animation": False, "series": []}, PRICE_LEGEND, "h-40")
                        price_empty = ui.label("No price update for this charger in the selected run.").classes("empty-state text-[13px] text-slate-500 p-3 text-center w-full")
                    state_empty = ui.label("No events for this charger in the selected run.").classes("empty-state text-[13px] text-slate-500 p-3 mt-2 text-center w-full")
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
    view = DashboardView(snapshot, active_sessions_label, average_price_label, completed_sessions_label, last_event_label, event_notice, analytics_value, selection_intro, selection_body, station_title, station_subtitle, station_fields, connector_area, connector_empty=connector_empty, debug_label=debug_label, live_mode=live_mode, mode_badge=mode_badge, live_button=live_button, on_run_change=load_run, time_zone=time_zone)

    def new_connector_panel(connector_no: int) -> ConnectorPanel:
        with connector_area:
            return ConnectorPanel(ui, connector_no)

    view.new_connector_panel = new_connector_panel
    view.state_charts = {"occupancy": occupancy_chart, "timeline": timeline_chart, "price": price_chart,
                         "area": state_area, "empty": state_empty, "price_empty": price_empty}
    selection_body.set_visibility(False)
    clear_button.on_click(view.clear_selection)
    run_selector.on_value_change(lambda e: view.select_history_run(str(e.value)))
    live_button.on_click(view.return_to_live); live_button.set_visibility(not live_mode)
    view.charging_map, view.filter_count_label = charging_map, filter_count
    view.stations_by_id, view.history_fields = {station.charger.charger_id: station for station in snapshot.stations}, history_fields
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


def create_dashboard(ui, snapshot: DashboardSnapshot, load_run: Callable[[str], DashboardSnapshot], *,
                     live_mode: bool = True, debug: bool = False, time_zone: str = "UTC") -> DashboardView:
    """Create the full-width dashboard from the snapshot its page loaded when it opened."""
    logger.info("Dashboard opened on run_id=%s", snapshot.events.run_id)
    return _build_loaded_page(ui, snapshot, load_run, debug=debug, live_mode=live_mode,
                              time_zone=resolve_display_timezone(time_zone))


def create_load_error_page(ui, error: Exception) -> None:
    """Create an actionable page for a dashboard that could not read its database."""
    _add_styles(ui)
    with ui.column().classes("w-full max-w-2xl mx-auto mt-24 p-6"):
        if isinstance(error, FileNotFoundError):
            ui.icon("database", color="negative").classes("text-5xl"); ui.label("Charging network database is unavailable").classes("text-2xl font-semibold"); ui.label("Please restore the local charging-network database, then restart the dashboard.").classes("text-slate-600 whitespace-pre-wrap")
        else:
            ui.icon("error_outline", color="negative").classes("text-5xl"); ui.label("Unable to load dashboard data").classes("text-2xl font-semibold"); ui.label(f"{type(error).__name__}: {error}").classes("text-slate-600 break-all")


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
