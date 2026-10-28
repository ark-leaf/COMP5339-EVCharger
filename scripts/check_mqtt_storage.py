# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this MQTT-to-DuckDB integration check.
"""Publish a window with context to Yeh's subscriber and verify its database."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

from repository import repo_config
from repository.entity.ev_charger_state import EVChargerState
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.utils import duckdb_utils as db
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber
from transaction_scripts.data_generation_and_publishing.data_generator_config import NEM_TIME
from transaction_scripts.data_generation_and_publishing.data_generator_daemon import publish_events
from transaction_scripts.data_generation_and_publishing.data_generator_utils import write_events_json
from transaction_scripts.data_generation_and_publishing.data_generator_replay import replay_events
from transaction_scripts.stateful_event_storage.save_subscribed_data import EVChargerEventStore


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True, help='Existing Ass1 database; copied, never written')
    parser.add_argument('--out', type=Path, required=True, help='New directory for JSON, database and report')
    parser.add_argument('--hours', type=int, default=4)
    parser.add_argument('--window-start', help='ISO start time; naive times use AEST')
    parser.add_argument('--charger-ids', type=int, nargs='+', help='Optional station subset for a smoke test')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=1883)
    args = parser.parse_args()
    source_manifest = json.loads((args.data_dir / 'manifest.json').read_text())
    if not 1 <= args.hours <= source_manifest['settings']['days'] * 24:
        parser.error('--hours must be within the generated period')
    start = datetime.fromisoformat(source_manifest['settings']['start']).replace(tzinfo=NEM_TIME)
    if args.window_start:
        start = datetime.fromisoformat(args.window_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=NEM_TIME)
    end = start + timedelta(hours=args.hours)
    events = list(replay_events(args.data_dir, start, end, args.charger_ids))
    if not events:
        raise ValueError('No events in the selected period')
    expected = {event.id: event.to_dict() for event in events}
    assert len(expected) == len(events)
    source_hash = sha256(args.db)
    args.out.mkdir(parents=True, exist_ok=False)
    database = (args.out / 'subscriber.duckdb').resolve()
    shutil.copy2(args.db, database)
    repo_config.DB_DATA = database
    prepared_path = args.out / 'prepared_events.json'
    published_path = args.out / 'published_events.json'
    write_events_json(events, prepared_path)
    run_id = source_manifest['run_id']
    replay = dict(run_id=run_id, source_dataset=str(args.data_dir.resolve()),
                  source_counts=source_manifest['counts'], start=start.isoformat(), end_exclusive=end.isoformat(),
                  events=len(events), counts=dict(Counter(e.type for e in events)))
    replay.update(context_events=sum(e.ts < start for e in events), charger_ids=args.charger_ids)
    (args.out / 'manifest.json').write_text(json.dumps(replay, indent=2) + '\n')
    states = {}
    for event in events:
        states.setdefault(event.charger_id, EVChargerState(event.charger_id, run_id)).apply(event)

    store = EVChargerEventStore()
    subscriber = None
    unique_received, totals = set(), dict(received=0, duplicates=0)

    def receive(event):
        assert event.to_dict() == expected[event.id], f'Unexpected payload: {event.id}'
        if store.save(event):
            unique_received.add(event.id)
        else:
            totals['duplicates'] += 1
        totals['received'] += 1
        if len(unique_received) and len(unique_received) % 250 == 0:
            print(f"Stored {len(unique_received)}/{len(events)} unique events", flush=True)

    def start_subscriber():
        nonlocal subscriber
        subscriber = YMqttEventSubscriber[EVChargerStateEvent]('database-integration', receive, args.host, args.port)
        subscriber.start()
        if not subscriber.ready.wait(15) or subscriber.error:
            raise RuntimeError(f'Subscriber did not become ready: {subscriber.error}')

    def wait_for_deliveries(target, *, unique=True):
        deadline = time.monotonic() + 30
        while (len(unique_received) if unique else totals['received']) < target:
            if subscriber.error or not subscriber.is_alive():
                raise RuntimeError(f'Subscriber failed: {subscriber.error}')
            if time.monotonic() > deadline:
                raise TimeoutError(f'Only {len(unique_received)}/{target} unique events stored')
            time.sleep(.05)

    def stop_subscriber():
        if subscriber is not None:
            subscriber.stopping.set()
            subscriber.join(timeout=30)
            if subscriber.is_alive() or subscriber.error:
                raise RuntimeError(f'Subscriber did not stop cleanly: {subscriber.error}')

    restarted_after = len(events) // 2
    restart_active_sessions = None

    def replay_with_subscriber_restart():
        nonlocal store, restart_active_sessions
        for index, event in enumerate(events):
            if index == restarted_after:
                wait_for_deliveries(index)
                stop_subscriber()
                restart_active_sessions = store.dao.run_summary(run_id)['active_sessions']
                db.close_connection()
                store = EVChargerEventStore()
                start_subscriber()
                print(f'Restarted subscriber and DB connection after {index} events; '
                      f'{restart_active_sessions} sessions were active', flush=True)
            yield event

    started = time.monotonic()
    try:
        # Reset event tables only in the new copy; retain the complete Ass1 schema/data.
        store.dao.create_tables()
        start_subscriber()
        print(f'SUBACK received; publishing {len(events)} events at >=0.1 s intervals', flush=True)
        published = publish_events(replay_with_subscriber_restart(), host=args.host, port=args.port,
                                   interval=.1, published_path=published_path)
        wait_for_deliveries(len(events))
        assert published == len(events) == len(unique_received)
        assert json.loads(published_path.read_text()) == json.loads(prepared_path.read_text())
        summary = store.dao.run_summary(run_id)

        # One event of each type, resent through MQTT, must not change stored rows/state.
        by_type = {}
        for event in events:
            by_type.setdefault(event.type, event)
        duplicate_events = list(by_type.values())
        received_before = totals['received']
        duplicates_before = totals['duplicates']
        publish_events(duplicate_events, host=args.host, port=args.port, interval=.1,
                       published_path=args.out / 'duplicate_check_events.json')
        wait_for_deliveries(received_before + len(duplicate_events), unique=False)
        assert totals['duplicates'] >= duplicates_before + len(duplicate_events)
        assert store.dao.run_summary(run_id) == summary
        stop_subscriber()

        stored_events = [event for cid in states for event in store.dao.list_events(run_id, cid)]
        assert {e.id: e.to_dict() for e in stored_events} == expected
        current = db.fetch_all('SELECT charger_id, price_per_kwh, active_sessions FROM charger_state WHERE run_id=?', [run_id])
        assert len(current) == len(states)
        for cid, price, active in current:
            assert float(price) == states[cid].price_per_kwh and active == states[cid].active_session_count
        history = db.fetch_all("SELECT charger_id,count(*),min(price_per_kwh),max(price_per_kwh) "
                               "FROM charger_event WHERE run_id=? AND event_type='price_update' GROUP BY charger_id", [run_id])
        assert len(history) == len(states)
        assert summary['active_sessions'] == sum(s.active_session_count for s in states.values())
        report = dict(tested_at_utc=datetime.now(timezone.utc).isoformat(), run_id=run_id,
                      window=replay, host=args.host, port=args.port, subscription='evc/#', qos=1,
                      publish_interval_seconds=.1, published=published, unique_received=len(unique_received),
                      database_summary=summary, payloads_and_ids_match=True, current_states_match=True,
                      chargers_with_price_history=len(history),
                      restart_after_events=restarted_after, active_sessions_at_restart=restart_active_sessions,
                      deliberate_duplicate_events=len(duplicate_events), duplicates_skipped=totals['duplicates'],
                      subscriber_received_including_duplicates=totals['received'],
                      real_MQTT_to_B_passed=True, full_day_published=False,
                      database_file=database.name, elapsed_seconds=round(time.monotonic()-started,1))
    finally:
        try:
            stop_subscriber()
        finally:
            db.close_connection()
    assert sha256(args.db) == source_hash
    report['source_Ass1_database_unchanged'] = True
    report['database_sha256'] = sha256(database)
    (args.out / 'mqtt_storage_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
