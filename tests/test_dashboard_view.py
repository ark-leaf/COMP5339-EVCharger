"""Dashboard interaction-state tests without a browser or MQTT broker."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import shutil

from repository.entity.ev_charger import EVCharger
from view.dashboard_app import (DashboardView, _add_styles, _dashboard_run_url, _replace_chart_options, _status_for, _timestamp, resolve_display_timezone,
                                _run_selection_handler)
from view.dashboard_data import DashboardSnapshot, DashboardStation
from view.dashboard_queries import (ActiveSession, ChargerLiveState, DashboardAnalytics,
                                    DashboardEventSnapshot, MeterPoint, PricePoint, StationHistory)


class FakeElement:
    def __init__(self):
        self.text = ""
        self.visible = True
        self.value = None
        self.options = {}
        self.options_history = []
        self.update_count = 0
        self.methods = []
        self.chart_options = {}

    def set_text(self, value): self.text = value
    def set_visibility(self, value): self.visible = value
    def update(self): self.update_count += 1
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
        self.view = DashboardView(
            snapshot=self.snapshot, active_sessions_label=FakeElement(), average_price_label=FakeElement(),
            completed_sessions_label=FakeElement(), last_event_label=FakeElement(), event_notice=FakeElement(),
            analytics_value=FakeElement(), selection_intro=FakeElement(), selection_body=FakeElement(),
            station_title=FakeElement(), station_subtitle=FakeElement(), station_fields=fields,
            session_area=FakeElement(), session_select=FakeElement(), curve_chart=FakeElement(), curve_empty=FakeElement(),
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

    def test_exact_marker_selects_station_and_multiple_sessions_switch_curve(self):
        self.view.select_marker("layer-a")
        self.assertEqual(self.view.selected_charger_id, 1)
        self.assertTrue(self.view.selection_body.visible)
        self.assertTrue(self.view.session_select.visible)
        self.assertEqual(set(self.view.session_select.options), {"1:1:session-a", "1:2:session-b"})
        self.view._show_curve("1:2:session-b")
        self.assertEqual(self.view.selected_session_key, "1:2:session-b")
        self.assertTrue(self.view.curve_chart.visible)
        self.assertGreater(self.view.curve_chart.update_count, 0)

    def test_completed_session_curve_remains_selectable(self):
        ended = ActiveSession(1, 1, "ended", self.first.session_start_ts, 0.5, 2.5, 60,
                              session_end_ts=self.first.session_start_ts, delivered_energy_kwh=2.5,
                              recorded_cost_aud=1.25, duration_minutes=15)
        events = DashboardEventSnapshot(
            ("run-a",), "run-a", self.snapshot.events.live_states, (),
            {ended.key: (MeterPoint(self.first.session_start_ts, 1.0), MeterPoint(self.first.session_start_ts, 2.5))},
            1, 0, 0.5, self.first.session_start_ts, completed_session_records=(ended,))
        self.view.apply_event_snapshot(events)
        self.view.show_station(self.snapshot.stations[0])
        self.assertIn("1:1:ended", self.view.session_select.options)
        self.assertTrue(self.view.curve_chart.visible)

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

    def test_run_selection_routes_new_run_and_uses_exact_url(self):
        navigated = []
        select_run = _run_selection_handler("run-a", navigated.append)
        event = type("Event", (), {"value": "run-new"})()
        select_run(event)
        select_run(type("Event", (), {"value": "run-a"})())
        self.assertEqual(navigated, ["run-new"])
        self.assertEqual(_dashboard_run_url(navigated[0]), "/?run_id=run-new")

    def test_run_selection_can_retry_after_failed_navigation(self):
        attempts = []

        def navigate(run_id):
            attempts.append(run_id)
            if len(attempts) == 1:
                raise RuntimeError("injected navigation interruption")

        select_run = _run_selection_handler("run-a", navigate)
        event = type("Event", (), {"value": "run-new"})()
        with self.assertRaisesRegex(RuntimeError, "navigation interruption"):
            select_run(event)
        select_run(event)
        self.assertEqual(attempts, ["run-new", "run-new"])

    def test_read_only_echarts_update_for_curves_and_analytics(self):
        # Directly covers all four chart families with an options property that
        # deliberately has no setter, as in NiceGUI 3.18.
        charts = [ReadOnlyChart() for _ in range(4)]
        for index, chart in enumerate(charts):
            _replace_chart_options(chart, {"series": [{"data": [index]}]})
            self.assertEqual(chart.options["series"][0]["data"], [index])
            self.assertEqual(chart.update_count, 1)

        now = self.first.session_start_ts
        analytics = DashboardAnalytics(
            event_type_counts={"meter": 2}, top_station_sessions=((1, 1),),
            station_history={1: StationHistory(price_points=(PricePoint(now, 0.5),))},
        )
        updated_events = DashboardEventSnapshot(
            self.snapshot.events.run_ids, "run-a", self.snapshot.events.live_states,
            self.snapshot.events.active_sessions,
            {self.first.key: (MeterPoint(now, 1.0), MeterPoint(now, 2.0)),
             self.second.key: self.snapshot.events.meter_points[self.second.key]},
            0, 2, 0.5, now, analytics,
        )
        self.view.curve_chart = charts[0]
        self.view.analytics_charts = {
            "Price History": charts[1], "Price Empty": FakeElement(),
            "Events by Type": charts[2], "Top Stations": charts[3],
        }
        self.view.stations_by_id = {1: self.snapshot.stations[0]}
        self.view.select_marker("layer-a")
        self.assertTrue(self.view.session_area.visible)
        self.assertTrue(self.view.curve_chart.visible)
        self.view.apply_event_snapshot(updated_events, {1}, live=True)
        self.assertEqual(charts[0].options["series"][0]["data"], [1.0, 2.0])
        self.assertTrue(all(chart.update_count >= 2 for chart in charts))


if __name__ == "__main__":
    unittest.main()
