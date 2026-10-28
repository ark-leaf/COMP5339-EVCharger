# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with coverage, reproducibility and window-state tests.
import csv
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
from scripts import build_dashboard_preview as preview
from repository.evc_event_dao import PAYLOAD_COLUMNS

from repository.entity.ev_charger import EVCharger
from repository.entity.ev_charger_state import EVChargerState
from transaction_scripts.data_generation_and_publishing import data_generator_daemon as daemon
from transaction_scripts.data_generation_and_publishing.data_generator_config import GenerationConfig, NEM_TIME
from transaction_scripts.data_generation_and_publishing.data_generator_replay import replay_events
from transaction_scripts.data_generation_and_publishing.data_generator_utils import generate_dataset, generate_evc_state_update


class DashboardDatasetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.start = datetime(2026, 9, 14, tzinfo=NEM_TIME)
        self.config = GenerationConfig(output_dir=self.path, start='2026-09-14', days=3,
                                       target_sessions=10, focus_charger_ids=(42,), meter_every=1)
        self.chargers = [EVCharger(42, charger_type='DC', number_of_plugs=2, rating_kw=150),
                         EVCharger(77, charger_type='DC', number_of_plugs=1, rating_kw=50)]
        self.wholesale = {self.start + timedelta(hours=h): .04 + (h % 24) * .001 for h in range(72)}

    def rows(self, name):
        with (self.path / f'{name}.csv').open() as stream:
            return list(csv.DictReader(stream))

    def test_exact_budget_daily_focus_coverage_and_no_overlapping_sessions(self):
        summary = generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        rows = self.rows('sessions')
        self.assertEqual(len(rows), 10)
        self.assertEqual(summary['counts']['prices'], 144)
        coverage = Counter((r['charger_id'], r['connector_id'], r['start_ts'][:10]) for r in rows)
        for day in range(3):
            for port in ('1', '2'):
                self.assertGreaterEqual(coverage['42', port, str((self.start + timedelta(days=day)).date())], 1)
        self.assertEqual(sum(r['charger_id'] == '77' for r in rows), 1)
        ended = {}
        for r in sorted(rows, key=lambda row: row['start_ts']):
            key = (r['charger_id'], r['connector_id'])
            start, end = map(datetime.fromisoformat, (r['start_ts'], r['end_ts']))
            self.assertGreaterEqual(start, ended.get(key, self.start))
            ended[key] = end
        meter_counts = Counter(m['session_id'] for m in self.rows('session_metering'))
        self.assertEqual(len(meter_counts), 10)
        for r in rows:
            self.assertEqual(meter_counts[r['session_id']], int(float(r['charge_minutes'])))
        states = {c.charger_id: EVChargerState(c.charger_id, summary['run_id']) for c in self.chargers}
        for event in generate_evc_state_update(self.path):
            states[event.charger_id].apply(event)
        self.assertTrue(all(s.active_session_count == 0 for s in states.values()))

    def test_csv_generation_is_reproducible(self):
        generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        original = {p.name: p.read_bytes() for p in self.path.glob('*.csv')}
        self.config.output_dir = self.path / 'second'
        generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.config.output_dir.glob('*.csv')})

    def test_two_minute_meters_preserve_the_final_reading(self):
        self.config.meter_every = 2
        generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        sessions = {r['session_id']: r for r in self.rows('sessions')}
        last, counts = {}, Counter()
        for r in self.rows('session_metering'):
            sid = r['session_id']
            ts = datetime.fromisoformat(r['ts'])
            end = datetime.fromisoformat(sessions[sid]['charge_end_ts'])
            prior = last.get(sid, datetime.fromisoformat(sessions[sid]['start_ts']))
            self.assertEqual(ts - prior, min(timedelta(minutes=2), end - prior))
            last[sid] = ts
            counts[sid] += 1
        for sid, s in sessions.items():
            self.assertEqual(last[sid], datetime.fromisoformat(s['charge_end_ts']))
            self.assertEqual(counts[sid], (int(float(s['charge_minutes'])) + 1) // 2)

    def test_impossible_budget_or_missing_focus_fails_before_writing(self):
        for total, focus in [(6, (42,)), (20, (42,)), (10, ())]:
            self.config.target_sessions, self.config.focus_charger_ids = total, focus
            with self.subTest(total=total, focus=focus), self.assertRaises(ValueError):
                generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        self.assertFalse((self.path / 'manifest.json').exists())

    def test_third_daily_session_fits_reduced_station_scope_without_overlap(self):
        self.config.target_sessions = 19  # Two focus ports x three days x three sessions + one other.
        generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        counts, ends = Counter(), {}
        for row in sorted(self.rows('sessions'), key=lambda r: r['start_ts']):
            key = row['charger_id'], row['connector_id']
            start, end = map(datetime.fromisoformat, (row['start_ts'], row['end_ts']))
            self.assertGreaterEqual(start, ends.get(key, self.start))
            ends[key] = end
            counts[*key, start.date()] += 1
        self.assertTrue(all(n == 3 for (cid, _, _), n in counts.items() if cid == '42'))

    def test_window_reconstructs_live_state_and_keeps_original_event_ids(self):
        generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        full = list(generate_evc_state_update(self.path))
        # Cut in the middle of an actual session, after at least one meter reading.
        first_meter = next(e for e in full if e.type == 'meter')
        start, end = first_meter.ts + timedelta(seconds=30), first_meter.ts + timedelta(hours=2)
        selected = list(replay_events(self.path, start, end))
        self.assertEqual([e.ts for e in selected], sorted(e.ts for e in selected))
        full_map = {e.id: e.to_dict() for e in full}
        self.assertTrue(all(full_map[e.id] == e.to_dict() for e in selected))
        self.assertTrue(any(e.ts < start and e.type == 'session_start' for e in selected))
        self.assertTrue(any(e.ts < start and e.type == 'meter' for e in selected))
        def states(events):
            result = {}
            for e in events:
                result.setdefault(e.charger_id, EVChargerState(e.charger_id, e.run_id)).apply(e)
            return {cid: (s.price_per_kwh, s.active_sessions) for cid, s in result.items()}
        self.assertEqual(states(selected), states(e for e in full if e.ts < end))
        subset = list(replay_events(self.path, start, end, [42]))
        self.assertEqual({e.charger_id for e in subset}, {42})

    def test_window_validation_and_separate_export_preserve_source(self):
        generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        source = {p.name: p.read_bytes() for p in self.path.iterdir() if p.is_file()}
        with self.assertRaises(ValueError):
            list(replay_events(self.path, self.start - timedelta(hours=1), self.start))
        with self.assertRaises(ValueError):
            list(replay_events(self.path, self.start, None))
        with patch('builtins.print'):
            daemon.main(['--replay', '--out', str(self.path), '--export-events',
                         '--window-start', '2026-09-14T09:00', '--window-end', '2026-09-14T13:00',
                         '--events-out', str(self.path / 'window')])
        self.assertEqual(source, {p.name: p.read_bytes() for p in self.path.iterdir() if p.is_file()})
        self.assertTrue(json.loads((self.path / 'window/prepared_events.json').read_text()))
        self.assertFalse((self.path / 'window/published_events.json').exists())

    def test_offline_preview_preserves_utc_instants_in_sydney_timezone(self):
        payload_types = {'vehicle_model': 'VARCHAR', 'charge_end_ts': 'TIMESTAMPTZ'}
        extra = ','.join(f'{name} {payload_types.get(name, "DOUBLE")}' for name in PAYLOAD_COLUMNS)
        messages = [dict(id='00000000000000000000000000000001', run_id='test', type='session_end',
                         ts='2026-09-13T14:30:00+00:00', object_id='42', connector_id=1,
                         session_id='test-session', payload=dict(vehicle_model='Example EV',
                         charge_end_ts='2026-09-13T14:25:00+00:00', energy_kwh=12.345))]
        path = self.path / 'messages.json'
        path.write_text(json.dumps(messages))
        with duckdb.connect() as db:
            db.execute("SET TimeZone='Australia/Sydney'")
            db.execute('CREATE TABLE charger_event (event_id UUID, run_id VARCHAR, event_type VARCHAR, '
                       'event_ts TIMESTAMPTZ, charger_id INTEGER, connector_no INTEGER, session_id VARCHAR, '
                       + extra + ')')
            with patch.object(preview.db, 'execute', side_effect=db.execute):
                preview.load_event_history(path)
            ts, end, day, name, energy = db.execute("SELECT epoch(event_ts),epoch(charge_end_ts),"
                "CAST(event_ts AT TIME ZONE 'Australia/Sydney' AS DATE)::VARCHAR,vehicle_model,energy_kwh "
                "FROM charger_event").fetchone()
        self.assertEqual(ts, datetime.fromisoformat(messages[0]['ts']).timestamp())
        self.assertEqual(end, datetime.fromisoformat(messages[0]['payload']['charge_end_ts']).timestamp())
        self.assertEqual((day, name, energy), ('2026-09-14', 'Example EV', 12.345))


if __name__ == '__main__':
    unittest.main()
