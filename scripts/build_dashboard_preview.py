# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the explicitly offline dashboard preview importer.
"""Build a full-history development database; this is NOT MQTT publication evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from repository import repo_config
from repository.entity.ev_charger_state import EVChargerState
from repository.evc_event_dao import EVChargerEventDAO, PAYLOAD_COLUMNS
from repository.utils import duckdb_utils as db
from transaction_scripts.data_generation_and_publishing.data_generator_utils import generate_evc_state_update


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_event_history(path):
    """Keep ISO timestamps as text until their explicit timezone-aware cast."""
    columns = ', '.join(PAYLOAD_COLUMNS)
    values = ', '.join(f"json_extract_string(payload, '$.{name}')" for name in PAYLOAD_COLUMNS)
    # JSON type inference would turn UTC strings into naive TIMESTAMP values.
    db.execute(f"""
        INSERT INTO charger_event
            (event_id, run_id, event_type, event_ts, charger_id, connector_no, session_id, {columns})
        SELECT id::UUID, run_id, type, ts::TIMESTAMPTZ, object_id::INTEGER,
               connector_id, session_id, {values}
        FROM read_json(?, format='array', columns={{id:'VARCHAR', run_id:'VARCHAR',
             type:'VARCHAR', ts:'VARCHAR', object_id:'VARCHAR', connector_id:'INTEGER',
             session_id:'VARCHAR', payload:'JSON'}})
    """, [str(path)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True, help='Existing Ass1 database, copied only')
    parser.add_argument('--out', type=Path, required=True, help='New preview directory')
    args = parser.parse_args()
    validation = json.loads((args.data_dir / 'validation.json').read_text())
    for name, expected in validation['files_sha256'].items():
        if digest(args.data_dir / name) != expected:
            raise ValueError(f'{name} changed since validation; rerun check_generator_coverage')
    source_hash = digest(args.db)
    args.out.mkdir(parents=True, exist_ok=False)
    destination = args.out / 'dashboard_preview.duckdb'
    shutil.copy2(args.db, destination)
    repo_config.DB_DATA = destination.resolve()
    dao = EVChargerEventDAO()
    try:
        dao.create_tables()
        # Import the verified original messages in bulk, using B's exact event schema.
        load_event_history(args.data_dir / 'prepared_events.json')
        states, prices, ports = {}, {}, {}
        for event in generate_evc_state_update(args.data_dir):
            states.setdefault(event.charger_id, EVChargerState(event.charger_id, event.run_id)).apply(event)
            if event.type == 'price_update':
                prices[event.charger_id] = event
            else:
                ports[event.charger_id, event.connector_id] = event
        assert all(s.active_session_count == 0 for s in states.values())
        # All sessions have ended. Reuse B's DAO to materialize final prices and port states.
        for event in sorted([*prices.values(), *ports.values()], key=lambda e: (e.ts, e.charger_id)):
            dao.update_latest_state(event, states[event.charger_id])
        summary = dao.run_summary(validation['run_id'])
        assert summary['events'] == validation['total_events']
        assert summary['session_starts'] == summary['session_ends'] == validation['counts']['sessions']
        assert len(ports) == validation['all_ports']
        assert db.fetch_one('SELECT count(*) FROM connector_state')[0] == len(ports)
        daily = dict(db.fetch_all("""
            SELECT strftime(event_ts AT TIME ZONE 'Australia/Sydney', '%Y-%m-%d'), count(*)
            FROM charger_event WHERE event_type='session_start' GROUP BY 1 ORDER BY 1
        """))
        assert daily == validation['daily_sessions']
        report = dict(created_at_utc=datetime.now(timezone.utc).isoformat(), run_id=validation['run_id'],
                      method='offline bulk import of verified generated JSON; not MQTT',
                      MQTT_publication_evidence=False, database_summary=summary,
                      daily_sessions=daily,
                      connector_states=len(ports), source_dataset=str(args.data_dir),
                      prepared_events_sha256=validation['files_sha256']['prepared_events.json'])
    finally:
        db.close_connection()
    assert digest(args.db) == source_hash
    report['source_Ass1_database_unchanged'] = True
    report['database_sha256'] = digest(destination)
    (args.out / 'offline_preview_report.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.out / 'README.txt').write_text(
        'OFFLINE DASHBOARD PREVIEW - NOT MQTT EVIDENCE\n'
        'Contains all generated history and final state after every session has ended.\n'
        'Use the separate mqtt_09_13/subscriber.duckdb for real MQTT and live-state evidence.\n'
        'Do not replay earlier events into this preview; they already exist and will be deduplicated.\n'
        'Group September dates in Australia/Sydney (AEST), not by the raw UTC date.\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
