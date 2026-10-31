"""Dashboard interaction-state tests without a browser or MQTT broker."""
from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import shutil

from entity.ev_charger import EVCharger
from view.dashboard_app import (BREAK_GAP, DEFAULT_METER_INTERVAL, PRICE_LEGEND, SESSION_LEGEND, TREND_LEGEND,
                                DashboardView, _LEGEND_TOGGLE, _add_styles, _charger_price_chart, _charger_timeline,
                                _connector_header, _connector_sessions_chart, _connector_stats,
                                _connector_timeline_chart, _connector_trend_chart, _event_axis, _meter_interval,
                                _occupancy_chart, _pick_session, _replace_chart_options, _session_chart,
                                _session_details, _session_options, _set_chart_options, _status_for, _timestamp,
                                _wall_ms, resolve_display_timezone)
from view.dashboard_data import DashboardSnapshot, DashboardStation
from view.dashboard_model import (ActiveSession, ChargerLiveState, ConnectorView, DashboardAnalytics,
                                    DashboardEventSnapshot, MeterPoint, PricePoint, StationHistory)


class FakeElement:
    def __init__(self):
        self.text = ""
        self.visible = True
        self.value = None
        self.options = {}
        self.options_history = []
        self.update_count = 0
        self.clear_count = 0
        self.methods = []
        self.chart_options = {}

    def set_text(self, value): self.text = value
    def set_visibility(self, value): self.visible = value
    def update(self): self.update_count += 1
    def clear(self): self.clear_count += 1
    def run_method(self, name, *args): self.methods.append((name, args))
    def props(self, *_args): return self

    @property
    def options(self): return self.chart_options
    @options.setter
    def options(self, value): self.chart_options = value


class ReadOnlyChart:
    """Matches NiceGUI 3.18's read-only EChart.options API."""
    def __init__(self):
        self._options, self.visible, self.update_count = {}, True, 0

    @property
    def options(self): return self._options

    def update(self): self.update_count += 1
    def set_visibility(self, value): self.visible = value


class FakeConnectorPanel:
    def __init__(self, connector_no):
        self.connector_no, self.renders = connector_no, []

    def render(self, connector, zone): self.renders.append((connector, zone))

    @property
    def connector(self): return self.renders[-1][0]


class DashboardViewTests(unittest.TestCase):
    def test_timestamp_uses_iana_zone_with_dst_and_explicit_utc_fallback(self):
        self.assertEqual(_timestamp(datetime(2026, 9, 17, 0, 38, tzinfo=timezone.utc), "Australia/Sydney"),
                         "2026-09-17 10:38 AEST")
        self.assertEqual(_timestamp(datetime(2026, 10, 17, 0, 38, tzinfo=timezone.utc), "Australia/Sydney"),
                         "2026-10-17 11:38 AEDT")
        self.assertTrue(_timestamp(datetime(2026, 9, 17, 0, 38), "invalid/zone").endswith("UTC"))
        self.assertEqual(resolve_display_timezone("Australia/Sydney"), "Australia/Sydney")
        self.assertEqual(resolve_display_timezone("invalid/zone"), "UTC")
        self.assertEqual(resolve_display_timezone(None), "UTC")

    def test_four_occupancy_states_use_distinct_active_connectors_and_capacity(self):
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        station = DashboardStation(EVCharger(9, number_of_plugs=4, latitude=-33, longitude=151), ())
        def snapshot(connectors, capacity=4, count=None):
            station.charger.number_of_plugs = capacity
            sessions = tuple(ActiveSession(9, connector, str(connector), now, None, None, None) for connector in connectors)
            return DashboardEventSnapshot(("run",), "run", {9: ChargerLiveState(None, len(sessions) if count is None else count, now)},
                                          sessions, {}, 0, len(sessions), None, now)
        self.assertEqual(_status_for(station, snapshot(())), "available")
        self.assertEqual(_status_for(station, snapshot((1,))), "charging")
        self.assertEqual(_status_for(station, snapshot((1, 2, 3))), "charging")
        self.assertEqual(_status_for(station, snapshot((1, 2, 3, 4))), "full")
        self.assertEqual(_status_for(station, snapshot((1,), capacity=1)), "full")
        self.assertEqual(_status_for(station, snapshot((99,), capacity=1)), "unknown")
        self.assertEqual(_status_for(station, snapshot((99,), capacity=2)), "unknown")
        self.assertEqual(_status_for(station, snapshot((1,), capacity=0)), "unknown")
        self.assertEqual(_status_for(station, snapshot((1, 2, 3, 4, 5))), "unknown")
        self.assertEqual(_status_for(station, snapshot((1, 1), count=2)), "charging")
        self.assertEqual(_status_for(station, snapshot((1,), count=2)), "unknown")
        self.assertEqual(_status_for(station, snapshot((1, 2), count=0)), "unknown")
        self.assertEqual(_status_for(station, snapshot((1, 2), count=1)), "unknown")

    def setUp(self):
        station = DashboardStation(EVCharger(1, station_name="One", station_address="1 Road", latitude=-33.8,
                                             longitude=151.2, charger_type="DC", number_of_plugs=2, rating_kw=50,
                                             operator_name="Network"), ("CCS2",))
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.first = ActiveSession(1, 1, "session-a", now, 0.5, 1.0, 40)
        self.second = ActiveSession(1, 2, "session-b", now, 0.6, 2.0, 55)
        events = DashboardEventSnapshot(("run-a",), "run-a", {1: ChargerLiveState(0.5, 2, now)},
            (self.first, self.second), {self.first.key: (MeterPoint(now, 1.0),), self.second.key: (MeterPoint(now, 2.0),)},
            0, 2, 0.5, now)
        self.snapshot = DashboardSnapshot(1, (station,), events)
        fields = {name: FakeElement() for name in ("Address", "Operator", "Charger Type", "Connector Type", "Number of Plugs", "Max Power", "Latest Price", "Charging Status")}
        self.panels = []
        def new_connector_panel(connector_no):
            self.panels.append(FakeConnectorPanel(connector_no))
            return self.panels[-1]
        self.view = DashboardView(
            snapshot=self.snapshot, active_sessions_label=FakeElement(), average_price_label=FakeElement(),
            completed_sessions_label=FakeElement(), last_event_label=FakeElement(), event_notice=FakeElement(),
            analytics_value=FakeElement(), selection_intro=FakeElement(), selection_body=FakeElement(),
            station_title=FakeElement(), station_subtitle=FakeElement(), station_fields=fields,
            connector_area=FakeElement(), connector_empty=FakeElement(), new_connector_panel=new_connector_panel,
        )
        self.layer = FakeElement()
        self.view.marker_layers["layer-a"] = (station, self.layer)
        self.view.marker_id_by_charger[1] = "layer-a"

    def test_map_legend_is_a_non_interactive_overlay_above_leaflet_panes(self):
        class StyleSink:
            def add_head_html(self, html): self.html = html
        sink = StyleSink()
        _add_styles(sink)
        self.assertIn(".map-legend{position:absolute!important;z-index:750!important;pointer-events:none", sink.html)

    def test_live_snapshot_cannot_overwrite_sticky_failed_indicator(self):
        badge = FakeElement()
        self.view.connection_badge = badge
        self.view.set_live_sync_failed()
        self.view.apply_event_snapshot(self.snapshot.events, live=True)
        self.assertEqual(badge.text, "LIVE synchronization FAILED")

    def test_successful_live_snapshot_keeps_normal_indicator_without_failure(self):
        badge = FakeElement()
        self.view.connection_badge = badge
        self.view.apply_event_snapshot(self.snapshot.events, live=True)
        self.assertEqual(badge.text, "Live updates received")

    def test_snapshot_summary_tracks_the_same_run_as_kpis(self):
        summary = FakeElement()
        self.view.snapshot_summary_label = summary
        updated = DashboardEventSnapshot(("run-a", "run-b"), "run-b", {}, (), {}, 7, 0, 0.5,
                                         self.first.session_start_ts,
                                         DashboardAnalytics(total_events=7, stations_with_event_data=1))
        self.view.apply_event_snapshot(updated, live=True)
        self.assertIn("Run run-b", summary.text)
        self.assertIn("7 total events", summary.text)

    def test_leaflet_static_marker_bindings_are_batched_after_init(self):
        source = Path("view/dashboard_app.py").read_text(encoding="utf-8")
        self.assertIn('charging_map.run_method("configure_layers", bindings)', source)
        self.assertNotIn('[(layer.run_method("bindPopup"', source)
        javascript = Path("view/dashboard_leaflet.js").read_text(encoding="utf-8")
        self.assertIn("configure_layers(bindings)", javascript)

    def test_hidden_leaflet_layers_use_persistent_registry_in_production_javascript(self):
        javascript = Path("view/dashboard_leaflet.js").read_text(encoding="utf-8")
        self.assertIn("const layer = this.layersById?.get(id)", javascript)
        self.assertIn("if (!layer) return null", javascript)
        self.assertNotIn("dashboard_leaflet_methods.mjs", javascript)
        self.assertNotIn("this.map.eachLayer((layer) => {\n        if (layer.id !== id)", javascript)
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the JavaScript-level Leaflet regression test")
        subprocess.run([node, "tests/dashboard_leaflet_component_test.mjs"], check=True)

    def test_status_filter_uses_marker_status_and_batches_visibility(self):
        stations = tuple(DashboardStation(EVCharger(index, station_name=name, station_address=f"{index} Road",
                    latitude=-33.8 - index / 100, longitude=151.2, charger_type="DC", number_of_plugs=2 if index == 1 else 1,
                    rating_kw=50, operator_name="Network"), ("CCS2",))
                    for index, name in ((1, "Full"), (2, "Available"), (3, "Unknown")))
        now = self.first.session_start_ts
        active = ActiveSession(1, 1, "active", now, 0.5, None, None)
        events = DashboardEventSnapshot(("run-a",), "run-a", {
            1: ChargerLiveState(0.5, 1, now), 2: ChargerLiveState(0.5, 0, now)}, (active,), {}, 0, 1, 0.5, now)
        self.view.snapshot = DashboardSnapshot(3, stations, events)
        self.view.marker_layers = {f"layer-{s.charger.charger_id}": (s, FakeElement()) for s in stations}
        self.view.marker_id_by_charger = {s.charger.charger_id: f"layer-{s.charger.charger_id}" for s in stations}
        self.view.charging_map, self.view.filter_count_label = FakeElement(), FakeElement()
        self.view.filter_controls = {name: FakeElement() for name in ("search", "coverage", "type", "operator", "power", "connector", "status")}
        for name in ("coverage", "type", "operator", "power", "connector", "status"):
            self.view.filter_controls[name].value = "all"
        self.view.filter_controls["search"].value = ""
        self.assertEqual([_status_for(s, events) for s in stations], ["charging", "available", "unknown"])

        for status, expected in (("all", {"layer-1", "layer-2", "layer-3"}),
                                 ("charging", {"layer-1"}), ("available", {"layer-2"}),
                                 ("unknown", {"layer-3"})):
            self.view.filter_controls["status"].value = status
            self.view.apply_filters()
            name, args = self.view.charging_map.methods[-1]
            self.assertEqual(name, "set_layers_visible")
            self.assertEqual(set(args[0]), expected)
            self.assertEqual(self.view.filter_count_label.text, f"{len(expected):,} matching stations")

        self.view.filter_controls["status"].value = "charging"
        self.view.filter_controls["type"].value = "AC"
        self.view.apply_filters()
        self.assertEqual(self.view.charging_map.methods[-1][1][0], [])
        self.view.reset_filters()
        self.assertEqual(self.view.filter_controls["status"].value, "all")

    def test_status_filter_reapplies_after_live_state_change_without_selecting_hidden_station(self):
        self.view.charging_map, self.view.filter_count_label = FakeElement(), FakeElement()
        self.view.filter_controls = {name: FakeElement() for name in ("search", "coverage", "type", "operator", "power", "connector", "status")}
        for name in ("coverage", "type", "operator", "power", "connector"):
            self.view.filter_controls[name].value = "all"
        self.view.filter_controls["search"].value, self.view.filter_controls["status"].value = "", "available"
        available = DashboardEventSnapshot(("run-a",), "run-a", {1: ChargerLiveState(0.5, 0, self.first.session_start_ts)}, (), {}, 0, 0, 0.5, self.first.session_start_ts)
        self.view.apply_event_snapshot(available, {1}, live=True)
        self.assertEqual(self.view.charging_map.methods[-1], ("set_layers_visible", (["layer-a"],)))
        charging = DashboardEventSnapshot(("run-a",), "run-a", {1: ChargerLiveState(0.5, 1, self.first.session_start_ts)}, (), {}, 0, 1, 0.5, self.first.session_start_ts)
        self.view.apply_event_snapshot(charging, {1}, live=True)
        self.assertEqual(self.view.charging_map.methods[-1], ("set_layers_visible", ([] ,)))
        self.view.filter_controls["search"].value = "one"
        self.view.search_and_select()
        self.assertIsNone(self.view.selected_charger_id)

    def test_exact_marker_selects_station_with_a_panel_per_connector(self):
        self.view.select_marker("layer-a")
        self.assertEqual(self.view.selected_charger_id, 1)
        self.assertTrue(self.view.selection_body.visible)
        self.assertEqual([panel.connector_no for panel in self.panels], [1, 2])
        self.assertEqual(self.view.connector_area.clear_count, 1)
        self.assertFalse(self.view.connector_empty.visible)
        first, second = (panel.connector for panel in self.panels)
        self.assertEqual((first.status, first.active), ("charging", self.first))
        self.assertEqual((second.status, second.active), ("charging", self.second))
        self.assertEqual(first.meter_points, {"session-a": (MeterPoint(self.first.session_start_ts, 1.0),)})

    def test_live_events_update_connector_panels_in_place_and_keep_completed_history(self):
        self.view.select_marker("layer-a")
        panels = list(self.panels)
        now = self.first.session_start_ts
        ended = replace(self.first, session_end_ts=now + timedelta(minutes=30), last_event_ts=now + timedelta(minutes=30),
                        delivered_energy_kwh=2.5, recorded_cost_aud=1.25, duration_minutes=28)
        events = DashboardEventSnapshot(
            ("run-a",), "run-a", {1: ChargerLiveState(0.5, 1, ended.session_end_ts)}, (self.second,),
            {ended.key: (MeterPoint(now, 1.0), MeterPoint(now, 2.5)), self.second.key: (MeterPoint(now, 2.0),)},
            1, 1, 0.5, ended.session_end_ts, completed_session_records=(ended,))
        self.view.apply_event_snapshot(events, {1}, live=True)
        # The same panels, so an expanded panel stays expanded while events arrive.
        self.assertEqual(self.panels, panels)
        self.assertEqual(self.view.connector_area.clear_count, 1)
        first = panels[0].connector
        self.assertEqual((first.status, first.active, first.completed), ("available", None, (ended,)))
        self.assertEqual([point.energy_kwh for point in first.meter_points["session-a"]], [1.0, 2.5])
        self.assertEqual(panels[1].connector.status, "charging")

    def test_connector_panels_are_rebuilt_for_another_station_and_cleared_with_the_selection(self):
        self.view.select_marker("layer-a")
        other = DashboardStation(EVCharger(2, station_name="Two", latitude=-33.9, longitude=151.3, number_of_plugs=3), ())
        self.view.show_station(other)
        self.assertEqual([panel.connector_no for panel in self.panels], [1, 2, 1, 2, 3])
        self.assertEqual(self.view.connector_area.clear_count, 2)
        self.assertEqual({panel.connector.status for panel in self.panels[2:]}, {"unknown"})
        self.view.clear_selection()
        self.assertEqual((self.view.connector_panels, self.view.connector_area.clear_count), ({}, 3))
        self.view.show_station(other)
        self.assertEqual(len(self.panels), 8)

    def test_station_without_plug_count_or_sessions_shows_no_connector_panels(self):
        station = DashboardStation(EVCharger(3, station_name="Three", latitude=-33.9, longitude=151.3), ())
        self.view.show_station(station)
        self.assertEqual(self.panels, [])
        self.assertTrue(self.view.connector_empty.visible)

    def test_connector_used_beyond_the_listed_plugs_still_gets_a_panel(self):
        extra = ActiveSession(1, 3, "session-c", self.first.session_start_ts, 0.5, None, None)
        events = replace(self.snapshot.events, active_sessions=(self.first, self.second, extra))
        self.assertEqual([connector.connector_no for connector in events.connectors(1, 2)], [1, 2, 3])
        self.assertEqual([connector.connector_no for connector in events.connectors(1, None)], [1, 2, 3])
        self.assertEqual(events.connectors(99, 0), ())

    def test_another_chargers_event_leaves_this_chargers_connectors_unchanged(self):
        # So this charger's charts stay still until one of its own events arrives.
        events, later = self.snapshot.events, self.snapshot.events.last_event_ts + timedelta(hours=1)
        elsewhere = replace(events, last_event_ts=later, live_states={**events.live_states, 2: ChargerLiveState(0.4, 0, later)})
        self.assertEqual(elsewhere.connectors(1, 2), events.connectors(1, 2))

    def test_blank_map_click_clears_without_deleting_marker_and_snapshot_reuses_it(self):
        self.view.select_marker("layer-a")
        self.view.select_marker(None)
        self.assertIsNone(self.view.selected_charger_id)
        self.assertTrue(self.view.selection_intro.visible)
        self.assertFalse(self.view.selection_body.visible)
        marker_count = len(self.view.marker_layers)
        self.view.apply_event_snapshot(self.snapshot.events)
        self.assertEqual(len(self.view.marker_layers), marker_count)
        self.assertTrue(any(name == "bindPopup" for name, _ in self.layer.methods))

    def test_run_options_do_not_reset_selection_during_live_events(self):
        self.view.run_selector = FakeElement()
        self.view.run_selector.value = "run-a"
        self.view.run_selector_run_ids = ("run-a",)
        self.view.update_run_options(("run-new", "run-a"))
        self.assertEqual(self.view.run_selector.value, "run-a")
        self.assertEqual(self.view.run_selector.options, ["run-new", "run-a"])
        self.assertEqual(self.view.run_selector.update_count, 1)
        self.view.update_run_options(("run-new", "run-a"))
        self.assertEqual(self.view.run_selector.update_count, 1)

    def test_automatic_snapshot_syncs_dropdown_without_entering_history(self):
        self.view.run_selector = FakeElement()
        self.view.run_selector.value = "run-a"
        self.view.live_mode = True
        updated = DashboardEventSnapshot(("run-a", "run-b"), "run-b", {}, (), {}, 0, 0, None,
                                         self.first.session_start_ts)
        self.view.apply_event_snapshot(updated, live=True)
        self.assertEqual(self.view.snapshot.events.run_id, "run-b")
        self.assertEqual(self.view.run_selector.value, "run-b")
        # A delayed selector event carrying the programmatic value is a no-op.
        self.view.select_history_run("run-b")
        self.assertTrue(self.view.live_mode)

    def test_live_button_uses_observed_run_not_simulated_timestamp_order(self):
        calls = []
        self.view.run_selector = FakeElement()
        self.view.run_selector_run_ids = ("run-a", "run-b")  # query order: simulated A appears newer
        self.view.live_run_id = "run-b"  # actual successful-commit arrival order
        self.view.live_mode = False
        self.view.on_run_change = lambda run_id: calls.append(run_id) or self.snapshot
        self.view.return_to_live()
        self.assertEqual(calls, ["run-b"])
        self.assertTrue(self.view.live_mode)

    def test_read_only_echarts_update_for_station_and_analytics_charts(self):
        # Covers the chart families with an options property that deliberately
        # has no setter, as in NiceGUI 3.18.
        charts = [ReadOnlyChart() for _ in range(5)]
        for index, chart in enumerate(charts):
            _replace_chart_options(chart, {"series": [{"data": [index]}]})
            self.assertEqual(chart.options["series"][0]["data"], [index])
            self.assertEqual(chart.update_count, 1)

        now = self.first.session_start_ts
        analytics = DashboardAnalytics(
            event_type_counts={"meter": 2}, top_station_sessions=((1, 1),),
            station_history={1: StationHistory(price_points=(PricePoint(now - timedelta(minutes=5), 0.5),))},
        )
        updated_events = replace(self.snapshot.events, analytics=analytics)
        self.view.state_charts = {"occupancy": charts[0], "timeline": charts[1], "price": charts[2],
                                  "area": FakeElement(), "empty": FakeElement(), "price_empty": FakeElement()}
        self.view.analytics_charts = {"Events by Type": charts[3], "Top Stations": charts[4]}
        self.view.stations_by_id = {1: self.snapshot.stations[0]}
        self.view.select_marker("layer-a")
        self.view.apply_event_snapshot(updated_events, {1}, live=True)
        self.assertEqual([value for _x, value in charts[2].options["series"][0]["data"]], [0.5, 0.5])
        self.assertEqual([value for _x, value in charts[0].options["series"][0]["data"]], [0, 2])
        self.assertTrue(all(chart.update_count >= 2 for chart in charts))
        self.assertTrue(self.view.state_charts["area"].visible)
        self.assertFalse(self.view.state_charts["empty"].visible)
        self.assertFalse(self.view.state_charts["price_empty"].visible)

    def test_charger_without_events_hides_its_state_history(self):
        state = {name: FakeElement() for name in ("area", "empty", "price_empty")}
        state.update({name: ReadOnlyChart() for name in ("occupancy", "timeline", "price")})
        self.view.state_charts = state
        quiet = DashboardStation(EVCharger(2, station_name="Two", latitude=-33.9, longitude=151.3, number_of_plugs=2), ())
        self.view.show_station(quiet)
        self.assertEqual((state["area"].visible, state["empty"].visible), (False, True))
        self.assertEqual(state["occupancy"].update_count, 0)

    def test_connector_charts_are_sent_only_when_their_options_change(self):
        chart = ReadOnlyChart()
        _set_chart_options(chart, {"series": [{"data": [1]}]})
        _set_chart_options(chart, {"series": [{"data": [1]}]})
        self.assertEqual(chart.update_count, 1)
        _set_chart_options(chart, {"series": [{"data": [1, 2]}]})
        self.assertEqual((chart.update_count, chart.options["series"][0]["data"]), (2, [1, 2]))


class ConnectorFixture:
    """Connector 2 of charger 6: a finished session and, by default, a current one."""

    start = datetime(2026, 9, 14, 19, 20, tzinfo=timezone.utc)  # 05:20 AEST

    def at(self, minutes):
        return self.start + timedelta(minutes=minutes)

    def connector(self, *, active=True, has_event_data=True):
        ended = ActiveSession(6, 2, "ended", self.start, 0.7, 39.0, 70.0, "Kia <EV6>", 72.0, self.at(25),
                              self.at(25), 39.01, 27.3, 22.0, self.at(22))
        sessions = [ended]
        points = {"ended": (MeterPoint(self.at(5), 8.4, 123.6, 35.7), MeterPoint(self.at(10), 18.7, 122.8, 49.1))}
        if active:
            sessions.append(ActiveSession(6, 2, "live", self.at(60), 0.65, 12.5, 48.0, "MG4", 98.1, self.at(70)))
            points["live"] = (MeterPoint(self.at(65), 6.0, 99.0, 40.0), MeterPoint(self.at(70), 12.5, 98.1, 48.0))
        return ConnectorView(6, 2, tuple(sessions), points, has_event_data)


class ConnectorPanelContentTests(ConnectorFixture, unittest.TestCase):
    """What a connector panel shows: its header while collapsed and its trends when expanded."""

    def test_header_shows_the_active_session_live_reading(self):
        header = _connector_header(self.connector(), "Australia/Sydney")
        self.assertEqual((header.status, header.label, header.headline), ("charging", "Charging", "98.1 kW"))
        self.assertEqual(header.summary, "MG4 · plugged in 15 Sep 06:20")
        self.assertEqual(header.detail, "12.50 kWh · SoC 48% · $0.65/kWh")
        self.assertEqual(header.soc, 0.48)

    def test_header_before_the_first_meter_reading(self):
        waiting = replace(self.connector(), sessions=(ActiveSession(6, 2, "new", self.start, 0.65, None, None),))
        header = _connector_header(waiting)
        self.assertEqual((header.headline, header.detail, header.soc), ("", "Awaiting first meter reading · $0.65/kWh", None))

    def test_header_of_a_free_connector_summarises_its_completed_sessions(self):
        header = _connector_header(self.connector(active=False), "Australia/Sydney")
        self.assertEqual((header.status, header.label, header.soc), ("available", "Available", None))
        self.assertEqual(header.summary, "Free since 15 Sep 05:45")
        self.assertEqual(header.detail, "1 session · 39.01 kWh delivered")
        unused = _connector_header(ConnectorView(6, 3, has_event_data=True))
        self.assertEqual((unused.status, unused.summary, unused.detail), ("available", "Not used in this run yet", ""))
        unknown = _connector_header(ConnectorView(6, 3))
        self.assertEqual((unknown.status, unknown.label), ("unknown", "No data"))

    def test_stats_count_active_occupancy_up_to_its_latest_event(self):
        # The current session has been plugged in from 60 to its latest meter reading at 70.
        self.assertEqual(_connector_stats(self.connector()),
                         "1 completed session + 1 active · 39.01 kWh delivered · $27.30 recorded · occupied 35 min")

    def test_trend_chart_breaks_lines_between_sessions_and_shades_occupancy_in_display_time(self):
        options = _connector_trend_chart(self.connector(), "Australia/Sydney")
        power, soc = (series["data"] for series in options["series"])
        local = lambda minutes: _wall_ms(self.at(minutes), "Australia/Sydney")
        self.assertTrue(options["useUTC"])
        self.assertEqual(local(0), round(datetime(2026, 9, 15, 5, 20, tzinfo=timezone.utc).timestamp() * 1000))
        self.assertEqual(power, [[local(5), 123.6], [local(10), 122.8], [local(60), "-"], [local(65), 99.0], [local(70), 98.1]])
        self.assertEqual([value for _x, value in soc], [35.7, 49.1, "-", 40.0, 48.0])
        self.assertEqual(options["series"][0]["markArea"]["data"],
                         [[{"xAxis": local(0)}, {"xAxis": local(25)}], [{"xAxis": local(60)}, {"xAxis": local(70)}]])
        # The axis runs from the first plug-in to the connector's latest event, and the
        # 35 idle minutes between unplugging at 25 and the next plug-in at 60 are cut out,
        # all but a 5-minute reading interval at either end.
        self.assertEqual((options["xAxis"]["min"], options["xAxis"]["max"]), (local(0), local(70)))
        self.assertEqual(options["xAxis"]["breaks"], [{"start": local(30), "end": local(55), "gap": BREAK_GAP}])
        self.assertNotIn("min", _connector_trend_chart(ConnectorView(6, 1, has_event_data=True))["xAxis"])

    def test_trend_chart_moves_on_with_the_connectors_next_event(self):
        connector = self.connector()
        later = replace(connector, meter_points={**connector.meter_points,
                                                 "live": connector.meter_points["live"] + (MeterPoint(self.at(75), 20.0, 97.0, 55.0),)},
                        sessions=(connector.sessions[0], replace(connector.sessions[1], last_event_ts=self.at(75))))
        self.assertEqual(_connector_trend_chart(connector)["xAxis"]["max"], _wall_ms(self.at(70)))
        self.assertEqual(_connector_trend_chart(later)["xAxis"]["max"], _wall_ms(self.at(75)))
        self.assertEqual(_connector_trend_chart(later)["series"][0]["markArea"]["data"][-1][1], {"xAxis": _wall_ms(self.at(75))})


class EventAxisTests(ConnectorFixture, unittest.TestCase):
    """A chart's time axis follows its own events and cuts out the idle stretches between them."""

    def test_idle_means_three_meter_intervals_without_an_event(self):
        local = lambda minutes: _wall_ms(self.at(minutes))
        times = [self.at(minutes) for minutes in (0, 5, 10, 25, 26, 60)]
        axis = _event_axis(times, timedelta(minutes=5))
        # 15 minutes is three readings' worth and stays; the 34 minutes from 26 to 60 are cut,
        # keeping one reading interval beside each event.
        self.assertEqual(axis["breaks"], [{"start": local(31), "end": local(55), "gap": BREAK_GAP}])
        self.assertEqual((axis["min"], axis["max"]), (local(0), local(60)))
        self.assertFalse(axis["breakArea"]["expandOnClick"])
        self.assertIn(":formatter", axis["axisLabel"])  # Wall-clock minutes, not the cut edges' seconds.
        # Readings every 20 minutes make an hour the idle threshold.
        self.assertEqual(_event_axis(times, timedelta(minutes=20))["breaks"], [])
        # A short meter interval still keeps gaps up to MIN_IDLE.
        self.assertEqual(len(_event_axis([self.at(0), self.at(9), self.at(20)], timedelta(minutes=1))["breaks"]), 1)

    def test_axis_of_one_event_or_none(self):
        self.assertEqual(_event_axis([self.at(0)] * 2, timedelta(minutes=5))["max"], _wall_ms(self.at(1)))
        self.assertNotIn("min", _event_axis([], timedelta(minutes=5)))

    def test_meter_interval_is_the_usual_gap_within_sessions(self):
        readings = lambda *minutes: tuple(MeterPoint(self.at(value), 1.0) for value in minutes)
        self.assertEqual(_meter_interval([readings(0, 5, 10, 40), readings(100, 105)]), timedelta(minutes=5))
        self.assertEqual(_meter_interval([readings(0), ()]), DEFAULT_METER_INTERVAL)

    def test_connector_event_times_are_session_starts_readings_and_ends(self):
        connector = self.connector()
        self.assertEqual(connector.event_times(), tuple(self.at(minutes) for minutes in (0, 5, 10, 25, 60, 65, 70)))
        self.assertEqual(connector.event_times("live"), tuple(self.at(minutes) for minutes in (60, 65, 70)))
        self.assertEqual((connector.sessions[0].span_end_ts, connector.sessions[1].span_end_ts), (self.at(25), self.at(70)))

    def test_sessions_chart_marks_the_active_session_and_escapes_vehicle_names(self):
        options = _connector_sessions_chart(self.connector(), "Australia/Sydney")
        self.assertEqual(options["xAxis"]["data"], ["15 Sep 05:20", "15 Sep 06:20"])
        ended, live = options["series"][0]["data"]
        self.assertEqual((ended["value"], live["value"]), (39.01, 12.5))
        self.assertNotEqual(ended["itemStyle"]["color"], live["itemStyle"]["color"])
        self.assertIn("Kia &lt;EV6&gt;", ended["tip"])
        self.assertIn("15 Sep 05:20 – 05:45", ended["tip"])
        self.assertIn("$27.30 · 22 min charging", ended["tip"])
        self.assertIn("12.50 kWh so far", live["tip"])
        self.assertIn("06:20 – now", live["tip"])
        # A bar names its session, so clicking it can open that session.
        self.assertEqual((ended["session"], live["session"]), ("ended", "live"))


class SessionSelectionTests(ConnectorFixture, unittest.TestCase):
    """The session dropdown in an expanded connector panel and the chart of the session it picks."""

    def test_dropdown_lists_the_current_session_first_then_past_sessions(self):
        self.assertEqual(_session_options(self.connector(), "Australia/Sydney"),
                         {"live": "Current · MG4 · since 15 Sep 06:20",
                          "ended": "15 Sep 05:20 – 05:45 · Kia <EV6> · 39.01 kWh"})
        self.assertEqual(list(_session_options(self.connector(active=False))), ["ended"])
        self.assertEqual(_session_options(ConnectorView(6, 1, has_event_data=True)), {})

    def test_panel_follows_the_newest_session_until_an_older_one_is_picked(self):
        both = {"live": "", "ended": ""}
        self.assertEqual(_pick_session({"ended": ""}, None, True), ("ended", True))
        self.assertEqual(_pick_session(both, "ended", True), ("live", True))   # A new session takes over.
        self.assertEqual(_pick_session(both, "ended", False), ("ended", False))  # A picked one stays.
        self.assertEqual(_pick_session(both, "live", False), ("live", True))    # Picking the newest follows again.
        self.assertEqual(_pick_session(both, "other-run", False), ("live", True))
        self.assertEqual(_pick_session({}, "ended", False), (None, True))

    def test_session_details_for_current_and_past_sessions(self):
        connector = self.connector()
        live, ended = connector.active, connector.completed[0]
        self.assertEqual(_session_details(live, "Australia/Sydney"),
                         "MG4 · plugged in 15 Sep 06:20 · $0.65/kWh · 12.50 kWh so far · SoC 48%")
        self.assertEqual(_session_details(ended, "Australia/Sydney"),
                         "Kia <EV6> · 15 Sep 05:20 – 05:45 · 39.01 kWh · $27.30 · $0.70/kWh · charged 22 min · idle 3 min")

    def test_session_chart_runs_from_plug_in_to_unplug_and_shades_the_idle_time(self):
        local = lambda minutes: _wall_ms(self.at(minutes), "Australia/Sydney")
        options = _session_chart(self.connector(), "ended", "Australia/Sydney")
        power, energy, soc = (series["data"] for series in options["series"])
        self.assertEqual((options["xAxis"]["min"], options["xAxis"]["max"]), (local(0), local(25)))
        self.assertEqual(energy, [[local(0), 0], [local(5), 8.4], [local(10), 18.7], [local(22), 39.01]])
        self.assertEqual(power, [[local(0), "-"], [local(5), 123.6], [local(10), 122.8], [local(22), "-"]])
        self.assertEqual([value for _x, value in soc], ["-", 35.7, 49.1, "-"])
        self.assertEqual(options["series"][0]["markArea"]["data"],
                         [[{"xAxis": local(22), "name": "Idle"}, {"xAxis": local(25)}]])
        self.assertEqual(options["xAxis"]["breaks"], [])  # Readings every 5 minutes: nothing idle to cut.
        live = _session_chart(self.connector(), "live", "Australia/Sydney")
        # Plug-in to the session's latest reading, however late other chargers' events are.
        self.assertEqual((live["xAxis"]["min"], live["xAxis"]["max"]), (local(60), local(70)))
        self.assertEqual(live["series"][0]["markArea"]["data"], [])
        self.assertEqual([series["data"] for series in _session_chart(self.connector(), None)["series"]], [[], [], []])


class ChargerStateHistoryTests(ConnectorFixture, unittest.TestCase):
    """The selected charger's state over the run: occupancy, connector timeline and price."""

    def connectors(self):
        other = ConnectorView(6, 1, (ActiveSession(6, 1, "other", self.at(25), 0.7, None, None, "BYD", None, self.at(40),
                                                   self.at(40), 10.0, 7.0, 12.0, self.at(37)),),
                              {}, True)
        return other, self.connector()

    def timeline(self, prices=(PricePoint(-10, 0.7),)):
        """The charger's timeline with prices given at minutes from the fixture's start."""
        prices = tuple(replace(point, event_ts=self.at(point.event_ts)) for point in prices)
        return _charger_timeline(self.connectors(), prices, "Australia/Sydney")

    def test_timeline_runs_over_the_chargers_own_events_and_cuts_idle_stretches(self):
        local = lambda minutes: _wall_ms(self.at(minutes), "Australia/Sydney")
        timeline = self.timeline()
        self.assertEqual(timeline.times, tuple(self.at(minutes) for minutes in (-10, 0, 5, 10, 25, 40, 60, 65, 70)))
        self.assertEqual((timeline.start, timeline.end), (self.at(-10), self.at(70)))
        # Nothing happens between unplugging at 40 and the next plug-in at 60.
        self.assertEqual(timeline.axis["breaks"], [{"start": local(45), "end": local(55), "gap": BREAK_GAP}])
        self.assertEqual((timeline.axis["min"], timeline.axis["max"]), (local(-10), local(70)))
        self.assertIsNone(_charger_timeline((ConnectorView(6, 1),), ()))
        # A charger's first event alone still gets a visible axis.
        single = _charger_timeline((), (PricePoint(self.at(-10), 0.7),))
        self.assertEqual((single.end, single.axis["max"]), (self.at(-10), _wall_ms(self.at(-9))))

    def test_all_three_charts_share_the_timeline_axis(self):
        timeline = self.timeline()
        prices = (PricePoint(self.at(-10), 0.7),)
        for options in (_occupancy_chart(self.connectors(), 2, timeline), _connector_timeline_chart(self.connectors(), timeline),
                        _charger_price_chart(prices, timeline)):
            self.assertIs(options["xAxis"], timeline.axis)

    def test_occupancy_steps_unplug_before_plug_in_at_the_same_time(self):
        local = lambda minutes: _wall_ms(self.at(minutes), "Australia/Sydney")
        options = _occupancy_chart(self.connectors(), 2, self.timeline(), "Australia/Sydney")
        series = options["series"][0]
        # Connector 2 unplugs at 25 just as connector 1 plugs in, so occupancy stays at one,
        # and it still holds at the charger's latest event.
        self.assertEqual(series["data"], [[local(-10), 0], [local(0), 1], [local(25), 1], [local(40), 0],
                                          [local(60), 1], [local(70), 1]])
        self.assertEqual(series["step"], "end")
        self.assertEqual(series["markLine"]["data"], [{"yAxis": 2}])
        self.assertEqual(options["yAxis"]["max"], 2)
        priced_only = _charger_timeline((), (PricePoint(self.at(0), 0.7),))
        self.assertEqual(_occupancy_chart((), None, priced_only)["series"][0]["markLine"]["data"], [])

    def test_timeline_splits_sessions_into_charging_idle_and_in_use(self):
        local = lambda minutes: _wall_ms(self.at(minutes), "Australia/Sydney")
        options = _connector_timeline_chart(self.connectors(), self.timeline(), "Australia/Sydney")
        self.assertEqual(options["yAxis"]["data"], ["1", "2"])
        blocks = options["series"][0]["data"]
        self.assertEqual([block["value"] for block in blocks],
                         [[0, local(25), local(37)], [0, local(37), local(40)],
                          [1, local(0), local(22)], [1, local(22), local(25)], [1, local(60), local(70)]])
        self.assertIn("Connector 2 · Kia &lt;EV6&gt;", blocks[2]["tip"])
        self.assertIn("Idle, still plugged in 15 Sep 05:42 – 05:45", blocks[3]["tip"])
        self.assertIn("In use 15 Sep 06:20 – now", blocks[4]["tip"])
        self.assertIn(":renderItem", options["series"][0])

    def test_price_chart_holds_each_price_until_the_next_update(self):
        local = lambda minutes: _wall_ms(self.at(minutes), "Australia/Sydney")
        prices = (PricePoint(0, 0.7, 0.07), PricePoint(60, 0.65, -0.01))
        timeline = self.timeline(prices)
        prices = tuple(replace(point, event_ts=self.at(point.event_ts)) for point in prices)
        options = _charger_price_chart(prices, timeline, "Australia/Sydney")
        retail, wholesale = options["series"]
        # Each price holds up to the charger's latest event, a meter reading at 70.
        self.assertEqual(retail["data"], [[local(0), 0.7], [local(60), 0.65], [local(70), 0.65]])
        self.assertEqual(wholesale["data"], [[local(0), 0.07], [local(60), -0.01], [local(70), -0.01]])
        self.assertEqual({retail["step"], wholesale["step"]}, {"end"})
        # Without a wholesale price the series is still there, empty, so it matches the legend.
        retail_only = _charger_price_chart((PricePoint(self.at(0), 0.7),), timeline)
        self.assertEqual([series["data"] for series in retail_only["series"]][1], [])


class ChartLegendTests(ConnectorFixture, unittest.TestCase):
    """Legends are HTML above the charts so they can wrap; each lists exactly its chart's series."""

    def test_html_legends_name_each_series_and_echarts_draws_none(self):
        prices = (PricePoint(self.at(0), 0.7, 0.07),)
        timeline = _charger_timeline((self.connector(),), prices)
        for options, legend in ((_connector_trend_chart(self.connector()), TREND_LEGEND),
                                (_session_chart(self.connector(), "ended"), SESSION_LEGEND),
                                (_charger_price_chart(prices, timeline), PRICE_LEGEND)):
            self.assertEqual(options["legend"], {"show": False})
            self.assertEqual([series["name"] for series in options["series"]], [name for name, _color, _dashed in legend])
            self.assertEqual([series["lineStyle"]["color"] for series in options["series"]],
                             [color for _name, color, _dashed in legend])
            self.assertEqual([series["lineStyle"].get("type") == "dashed" for series in options["series"]],
                             [dashed for _name, _color, dashed in legend])

    def test_idle_label_stays_inside_its_shaded_area(self):
        options = _session_chart(self.connector(), "ended")
        self.assertEqual(options["series"][0]["markArea"]["label"]["position"], "insideTop")

    def test_legend_click_toggles_the_named_series_of_the_chart_beside_it(self):
        handler = _LEGEND_TOGGLE.format(name=json.dumps("SoC (%)"))
        self.assertIn("closest('.legend-chart')", handler)
        self.assertIn("{type: 'legendToggleSelect', name: \"SoC (%)\"}", handler)


if __name__ == "__main__":
    unittest.main()
