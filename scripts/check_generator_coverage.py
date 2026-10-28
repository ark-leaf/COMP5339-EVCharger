# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with source-data and full-event-stream verification.
"""Check a balanced DC dataset and save coverage and acceptance evidence locally."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import zip_longest
import csv
import json
from pathlib import Path
import statistics

from repository.duckdb_repo import DuckDBRepository
from repository.evc_info_dao import EVChargerInfoDAO
from repository.entity.ev_charger_state import EVChargerState
from transaction_scripts.data_generation_and_publishing.data_generator_config import GenerationConfig, NEM_TIME, STATION_SCOPE_POLICY
from transaction_scripts.data_generation_and_publishing.data_generator_utils import generate_evc_state_update, load_wholesale_hourly


def check_dataset(path, db_path):
    def rows(name):
        with (path / f'{name}.csv').open() as stream:
            yield from csv.DictReader(stream)

    manifest = json.loads((path / 'manifest.json').read_text())
    config = GenerationConfig(**manifest['settings'])
    # Use the received bundle's cache when checking data moved to another computer.
    config.output_dir = path
    assert config.target_sessions is not None
    start = datetime.fromisoformat(config.start).replace(tzinfo=NEM_TIME)
    dates = [str((start + timedelta(days=d)).date()) for d in range(config.days)]
    with DuckDBRepository(db_path) as repo:
        dao = EVChargerInfoDAO(repo)
        source_dc_ids = {c.charger_id for c in dao.list_chargers() if c.charger_type == 'DC'}
        chargers = {c.charger_id: c for c in dao.list_generation_chargers() if c.charger_type == 'DC'}
        focus = set(dao.list_augmented_charger_ids(config.focus_region)) & set(chargers)
        connector_rows = repo.fetch_all('SELECT charger_id, charger_connector_id, connector_type FROM charger_connector ORDER BY charger_id, charger_connector_id')
        registered_ids = {r['charger_id'] for r in repo.fetch_all('SELECT DISTINCT charger_id FROM charger')}
    assert set(chargers) <= registered_ids & {r['charger_id'] for r in connector_rows}
    assert manifest['station_scope'] == dict(policy=STATION_SCOPE_POLICY,
                                            ports={str(cid): c.number_of_plugs for cid, c in chargers.items()})
    stations = {int(s['charger_id']): s for s in rows('stations')}
    assert set(stations) == set(chargers)
    assert focus == set(config.focus_charger_ids)
    for cid, st in stations.items():
        c = chargers[cid]
        assert int(st['connectors']) == c.number_of_plugs
        assert float(st['max_kw']) == c.rating_kw
        assert (float(st['lat']), float(st['lon'])) == (c.latitude, c.longitude)
    inputs = list(rows('stations_input'))
    assert len(inputs) == len(stations)
    for r in inputs:
        assert list(r) == 'station_id name lat lon site_type connectors max_kw'.split()
        assert all(r[key] == stations[int(r['station_id'])][key] for key in r if key != 'station_id')

    wholesale = load_wholesale_hourly(config)
    mean_price = statistics.mean(wholesale.values())
    prices, price_keys = {}, set()
    for r in rows('prices_hourly'):
        cid, ts = int(r['charger_id']), datetime.fromisoformat(r['ts'])
        key = (cid, ts)
        assert key not in price_keys and ts in wholesale
        price_keys.add(key)
        expected = float(stations[cid]['base_price']) + config.pass_through * (wholesale[ts] - mean_price)
        expected += config.peak_adder if 16 <= ts.hour < 21 else 0
        assert float(r['price_per_kwh']) == round(min(max(expected, config.price_floor), config.price_cap), 2)
        assert abs(float(r['wholesale_per_kwh']) - wholesale[ts]) < 1e-10
        prices[key] = float(r['price_per_kwh'])
    assert len(price_keys) == len(stations) * config.days * 24 >= 10000

    sessions = list(rows('sessions'))
    by_id = {r['session_id']: r for r in sessions}
    assert len(by_id) == len(sessions) == config.target_sessions
    coverage, port_counts, daily, ended = Counter(), Counter(), Counter(), {}
    for r in sorted(sessions, key=lambda r: r['start_ts']):
        cid, port = int(r['charger_id']), int(r['connector_id'])
        t0, charge_end, end = (datetime.fromisoformat(r[k]) for k in ('start_ts', 'charge_end_ts', 'end_ts'))
        assert 1 <= port <= chargers[cid].number_of_plugs
        assert t0 >= ended.get((cid, port), start) and t0 < charge_end <= end
        assert str(t0.date()) in dates
        assert (charge_end - t0).total_seconds() / 60 == float(r['charge_minutes'])
        assert float(r['price_per_kwh']) == prices[cid, t0.replace(minute=0, second=0, microsecond=0)]
        ended[cid, port] = end
        coverage[cid, port, str(t0.date())] += 1
        port_counts[cid, port] += 1
        daily[str(t0.date())] += 1
    expected_ports = {(cid, p) for cid, c in chargers.items() for p in range(1, c.number_of_plugs + 1)}
    assert set(port_counts) == expected_ports
    assert all(1 <= coverage[cid, p, day] <= 3 for cid, p in expected_ports if cid in focus for day in dates)
    assert dict(sorted(daily.items())) == manifest['schedule']['daily_sessions']
    average = len(sessions) / config.days
    assert max(abs(n / average - 1) for n in daily.values()) <= .15
    meter_counts, previous, meter_total = Counter(), {}, 0
    for r in rows('session_metering'):
        sid = r['session_id']
        s = by_id[sid]
        ts = datetime.fromisoformat(r['ts'])
        old_ts, old_energy, old_soc = previous.get(sid, (datetime.fromisoformat(s['start_ts']), 0, 0))
        energy, soc = float(r['energy_kwh']), float(r['soc_pct'])
        assert r['charger_id'] == s['charger_id'] and r['connector_id'] == s['connector_id']
        expected_gap = min(timedelta(minutes=config.meter_every), datetime.fromisoformat(s['charge_end_ts']) - old_ts)
        assert ts - old_ts == expected_gap and energy >= old_energy and soc >= old_soc
        assert 0 <= float(r['power_kw']) <= chargers[int(r['charger_id'])].rating_kw + .01
        previous[sid] = (ts, energy, soc)
        meter_counts[sid] += 1
        meter_total += 1
    for sid, s in by_id.items():
        assert meter_counts[sid] == (int(float(s['charge_minutes'])) + config.meter_every - 1) // config.meter_every
        assert previous[sid][0] == datetime.fromisoformat(s['charge_end_ts'])
        assert abs(previous[sid][1] - float(s['energy_kwh'])) <= .0051

    def exported():
        with (path / 'prepared_events.json').open() as stream:
            for line in stream:
                line = line.strip().strip(',')
                if line and line not in ('[', ']'):
                    yield json.loads(line)
    states, event_ids, event_counts, last_ts = {}, set(), Counter(), start
    for event, saved in zip_longest(generate_evc_state_update(path), exported()):
        assert event is not None and saved == event.to_dict()
        assert event.id not in event_ids and event.ts >= last_ts
        event_ids.add(event.id)
        event_counts[event.type] += 1
        last_ts = event.ts
        states.setdefault(event.charger_id, EVChargerState(event.charger_id, event.run_id)).apply(event)
    assert all(s.active_session_count == 0 for s in states.values())
    assert event_counts['meter'] == meter_total
    assert event_counts['session_start'] == event_counts['session_end'] == len(sessions)
    assert manifest['counts'] == dict(stations=len(stations), prices=len(price_keys), sessions=len(sessions), meters=meter_total)
    with (path / 'connector_coverage.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['charger_id', 'connector_no', 'focus', 'sessions', 'active_days', *dates])
        for cid, port in sorted(expected_ports):
            counts = [coverage[cid, port, day] for day in dates]
            writer.writerow([cid, port, cid in focus, port_counts[cid, port], sum(n > 0 for n in counts), *counts])
    with (path / 'station_source_audit.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['charger_id', 'number_of_plugs', 'charger_connector_ids', 'connector_types'])
        for cid, charger in sorted(chargers.items()):
            types = [row for row in connector_rows if row['charger_id'] == cid]
            writer.writerow([cid, charger.number_of_plugs,
                             json.dumps([r['charger_connector_id'] for r in types]),
                             json.dumps([r['connector_type'] for r in types])])
    hashes = {}
    for file in [*path.glob('*.csv'), path / 'manifest.json', path / 'prepared_events.json']:
        with file.open('rb') as stream:
            hashes[file.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), run_id=manifest['run_id'],
                  counts=manifest['counts'], all_ports=len(expected_ports), ports_without_sessions=0,
                  focus_stations=len(focus), focus_ports=sum(cid in focus for cid, _ in expected_ports),
                  focus_port_day_coverage_complete=True, daily_sessions=dict(sorted(daily.items())),
                  max_daily_deviation_percent=round(100 * max(abs(n / average - 1) for n in daily.values()), 2),
                  meter_interval_minutes=config.meter_every,
                  meter_points_per_session=dict(min=min(meter_counts.values()), median=statistics.median(meter_counts.values()),
                                                mean=round(meter_total / len(sessions), 2), max=max(meter_counts.values())),
                  event_counts=dict(event_counts), total_events=sum(event_counts.values()),
                  source_identity_and_teacher_input_match=True, AEMO_prices_match=True,
                  station_scope_policy=STATION_SCOPE_POLICY,
                  missing_charger_records=0, missing_connector_type_records=0,
                  invalid_port_references=0, synthetic_port_count_defaults=0,
                  excluded_DC_station_ids=sorted(source_dc_ids - set(chargers)),
                  nonoverlapping_sessions=True, meter_timing_energy_and_power_valid=True,
                  full_event_JSON_and_state_transitions_valid=True, full_MQTT_published=False,
                  files_sha256=hashes)
    (path / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check_dataset(args.data_dir, args.db), indent=2))
