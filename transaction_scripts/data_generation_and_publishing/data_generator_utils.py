# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the adapters and event conversion.
"""Adapt Ass1 stations and supplied generator output to the shared event entities."""
import csv
import json
import math
import random
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid4, uuid5

import duckdb

from transaction_scripts.data_generation_and_publishing import generate_dataset as supplied
from transaction_scripts.data_generation_and_publishing.data_generator_config import NEM_TIME, STATION_SCOPE_POLICY
from transaction_scripts.data_generation_and_publishing.data_generator_schedule import balanced_session_plan
from event.ev_charger_state_event import EVENT_TYPE_ORDER, EVChargerStateEvent, PAYLOAD_FIELDS

CSV_FIELDS = {
    "stations_input": "station_id name lat lon site_type connectors max_kw",
    "stations": "charger_id name lat lon site_type connectors max_kw charger_type model_type assumptions base_price",
    "prices_hourly": "ts charger_id price_per_kwh wholesale_per_kwh",
    "sessions": "session_id charger_id connector_id site_type vehicle_model start_ts charge_end_ts end_ts charge_minutes energy_kwh avg_kw peak_kw price_per_kwh cost_aud",
    "session_metering": "ts type charger_id connector_id session_id voltage_v current_a power_kw energy_kwh soc_pct",
}


def station_record(charger, config):
    """Keep database identity; record every synthetic default alongside the station."""
    kind = (charger.charger_type or "unknown").upper()
    assumptions = [f"site_type assumed {config.default_site_type}"]
    if kind not in ("AC", "DC"):
        raise ValueError(f"Charger {charger.charger_id}: only existing AC/DC stations may generate events")
    model = kind
    plugs = charger.number_of_plugs
    if type(plugs) is not int or plugs <= 0:
        raise ValueError(f"Charger {charger.charger_id}: a positive Ass1 plug count is required")
    power = charger.rating_kw
    if power is None or not math.isfinite(power) or power <= 0:
        power = 50.0 if model == "DC" else 7.0
        assumptions.append(f"missing rating assumed {power:g} kW")
    name = charger.station_name or (
        f"{charger.operator_name or 'Charger'} - {charger.station_address or charger.charger_id}")
    return dict(charger_id=charger.charger_id, name=name,
                lat=charger.latitude, lon=charger.longitude, site_type=config.default_site_type,
                connectors=int(plugs), max_kw=float(power), charger_type=charger.charger_type,
                model_type=model, assumptions="; ".join(assumptions))


def load_wholesale_hourly(config):
    """Keep the supplied generator's naive AEST times explicit at our boundary."""
    start = datetime.fromisoformat(config.start)
    prices = supplied.load_wholesale_hourly(
        start, start + timedelta(days=config.days), config.region,
        str(config.output_dir / "aemo_cache"))
    return {hour.replace(tzinfo=NEM_TIME): price for hour, price in prices.items()}


def simulate_session(rng, st, connector, session_id, t0, price, config):
    """Run the supplied simulator, which calls the charger "station_id", and rename it charger_id."""
    row, meters, unplug = supplied.simulate_session(
        rng, dict(st, station_id=st["charger_id"]), connector, session_id, t0, price, config)
    for record in (row, *meters):
        record["charger_id"] = record.pop("station_id")
    return row, meters, unplug


def scheduled_sessions(rng, st, plan, start, prices, config):
    """Use the supplied charging physics with non-overlapping, allocated DC sessions."""
    busy_until = [start] * st["connectors"]
    for day in range(config.days):
        midnight = start + timedelta(days=day)
        for c in range(st["connectors"]):
            count = plan[st["charger_id"], c + 1, day]
            for index in range(count):
                hours = list(range(24 * index // count, 24 * (index + 1) // count))
                weights = [supplied.BASE_START_PROFILE[h]
                           * (supplied.URBAN_WEEKDAY_EVENING.get(h, 1) if midnight.weekday() < 5 else 1)
                           * (prices[midnight + timedelta(hours=h)] / st["base_price"]) ** config.elasticity
                           for h in hours]
                hour = rng.choices(hours, weights=weights)[0]
                t0 = max(midnight + timedelta(hours=hour, minutes=rng.randrange(60)), busy_until[c])
                if t0 >= midnight + timedelta(days=1):
                    raise ValueError(f"Insufficient daily capacity for charger {st['charger_id']} port {c + 1}")
                price = prices[t0.replace(minute=0, second=0, microsecond=0)]
                sid = f"{st['charger_id']}-{c + 1}-{t0:%Y%m%d%H%M}"
                row, meters, unplug = simulate_session(rng, st, c + 1, sid, t0, price, config)
                busy_until[c] = unplug + timedelta(minutes=1)
                yield row, meters


def generate_dataset(chargers, config, *, wholesale=None):
    """Write DAO-selected stations and time series; injected prices support offline tests."""
    manifest_path = config.output_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Dataset already exists: {config.output_dir}; use --replay or a new --out")
    stations = [station_record(charger, config) for charger in chargers]
    if not stations or len({s["charger_id"] for s in stations}) != len(stations):
        raise ValueError("Need at least one station, with unique Ass1 charger IDs")
    plan = balanced_session_plan(stations, config) if config.target_sessions is not None else None
    start = datetime.fromisoformat(config.start).replace(tzinfo=NEM_TIME)
    hours = [start + timedelta(hours=i) for i in range(config.days * 24)]
    injected = wholesale is not None
    wholesale = load_wholesale_hourly(config) if wholesale is None else wholesale
    if any(h not in wholesale or not math.isfinite(wholesale[h]) for h in hours):
        raise ValueError("Hourly wholesale prices must cover the complete generation period")
    mean = sum(wholesale[h] for h in hours) / len(hours)
    rng, run_id = random.Random(config.seed), uuid4().hex
    config.output_dir.mkdir(parents=True, exist_ok=True)
    counts = dict(stations=len(stations), prices=0, sessions=0, meters=0)
    with ExitStack() as stack:
        writers = {}
        for name, fields in CSV_FIELDS.items():
            stream = stack.enter_context((config.output_dir / f"{name}.csv").open("w", newline="", encoding="utf-8"))
            writers[name] = csv.DictWriter(stream, fieldnames=fields.split())
            writers[name].writeheader()
        for st in stations:
            writers["stations_input"].writerow({
                key: st["charger_id" if key == "station_id" else key]
                for key in CSV_FIELDS["stations_input"].split()})
            base = supplied.station_base_price(st, rng)
            st["base_price"] = base
            writers["stations"].writerow(st)
            busy_until = [start] * st["connectors"]
            per_day = config.sessions_per_connector_day[st["site_type"] == "regional"]
            prices = {}
            for hour in hours:
                price = supplied.dynamic_price(base, wholesale[hour], mean, hour.hour, config)
                writers["prices_hourly"].writerow(dict(ts=hour.isoformat(), charger_id=st["charger_id"],
                                                       price_per_kwh=price, wholesale_per_kwh=wholesale[hour]))
                counts["prices"] += 1
                prices[hour] = price
                if plan is not None:
                    continue
                weight = supplied.BASE_START_PROFILE[hour.hour] / sum(supplied.BASE_START_PROFILE)
                if st["site_type"] == "urban" and hour.weekday() < 5:
                    weight *= supplied.URBAN_WEEKDAY_EVENING.get(hour.hour, 1)
                lam = per_day * weight * (price / base) ** config.elasticity
                for c in range(st["connectors"]):
                    arrivals = sorted(rng.randrange(60) for _ in range(supplied.poisson(lam, rng)))
                    for minute in arrivals:
                        t0 = hour + timedelta(minutes=minute)
                        if t0 < busy_until[c]:
                            continue
                        sid = f"{st['charger_id']}-{c + 1}-{t0:%Y%m%d%H%M}"
                        row, meters, busy_until[c] = simulate_session(rng, st, c + 1, sid, t0, price, config)
                        writers["sessions"].writerow(row)
                        writers["session_metering"].writerows(meters)
                        counts["sessions"] += 1
                        counts["meters"] += len(meters)
            if plan is not None:
                for row, meters in scheduled_sessions(rng, st, plan, start, prices, config):
                    writers["sessions"].writerow(row)
                    writers["session_metering"].writerows(meters)
                    counts["sessions"] += 1
                    counts["meters"] += len(meters)
    settings = {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()}
    manifest = dict(run_id=run_id, counts=counts, settings=settings, source_time="AEST UTC+10",
                    station_scope=dict(policy=STATION_SCOPE_POLICY,
                                       ports={str(st['charger_id']): st['connectors'] for st in stations}),
                    wholesale_source="injected hourly prices (testing)" if injected else supplied.AEMO_URL,
                    assumptions="See stations.csv assumptions and README for AC model; "
                                "sessions started inside the period retain all tail events.")
    if plan is not None:
        manifest["schedule"] = dict(
            mode="coverage-controlled synthetic demonstration", focus_region=config.focus_region,
            focus_chargers=sum(st["charger_id"] in config.focus_charger_ids for st in stations),
            focus_ports=sum(st["connectors"] for st in stations if st["charger_id"] in config.focus_charger_ids),
            daily_sessions={str((start + timedelta(days=d)).date()): sum(n for (_, _, day), n in plan.items() if day == d)
                            for d in range(config.days)},
            policy="Focus ports: one to three sessions/day; other ports: one session/period. "
                   "This replaces Poisson arrival counts, not the supplied charging physics or AEMO prices.")
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def _source_time(value):
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=NEM_TIME)


def write_events_json(events, path):
    """Write one JSON array incrementally, retaining completed records if the stream fails."""
    count = 0
    with Path(path).open("w", encoding="utf-8") as stream:
        stream.write("[\n")
        try:
            for event in events:
                message = event.to_json()
                stream.write((",\n" if count else "") + message)
                stream.flush()
                count += 1
        finally:
            stream.write("\n]\n")
    return count


def generate_evc_state_update(output_dir, run_id=None):
    """Stream sorted event entities; replay preserves IDs and omits unchanged tariffs."""
    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    scope = manifest.get("station_scope", {})
    if scope.get("policy") != STATION_SCOPE_POLICY or not scope.get("ports"):
        raise ValueError("Dataset has no registered-station scope; regenerate from Ass1 into a new directory")
    ports = scope["ports"]
    run_id = run_id or manifest["run_id"]
    # At equal times, process final meter readings and endings before new starts.
    sources = [("prices_hourly", "price_update", "ts"),
               ("session_metering", "meter", "ts"),
               ("sessions", "session_end", "end_ts"),
               ("sessions", "session_start", "start_ts")]
    queries, paths = [], []
    for name, kind, ts_column in sources:
        priority = EVENT_TYPE_ORDER.index(kind)
        queries.append(f"SELECT CAST({ts_column} AS TIMESTAMPTZ) AS event_time, {priority} AS priority, "
                       f"'{kind}' AS event_type, charger_id, to_json(t) AS row_json "
                       "FROM read_csv(?, header=true, all_varchar=true) AS t")
        paths.append(str(output_dir / f"{name}.csv"))
    # Stage CSVs on disk before sorting so their read buffers can be released.
    with TemporaryDirectory(prefix=".events-", dir=output_dir) as scratch, duckdb.connect(
            str(Path(scratch) / "events.duckdb"),
            config={"memory_limit": "512MB", "threads": "1",
                    "preserve_insertion_order": "false"}) as db:
        db.execute("CREATE TABLE event_rows AS " + " UNION ALL ".join(queries), paths)
        # Validate the whole staged stream before yielding anything to the publisher.
        identities = db.execute("""SELECT DISTINCT charger_id, event_type = 'price_update',
            json_extract_string(row_json, '$.connector_id') FROM event_rows""").fetchall()
        for cid, price_event, connector in identities:
            if cid not in ports or (not price_event and
                    (connector is None or not 1 <= int(connector) <= ports[cid])):
                raise ValueError(f"Event outside selected station/port scope: {cid}/{connector}")
        result = db.execute("SELECT event_type, charger_id, row_json FROM event_rows "
                            "ORDER BY event_time, priority, charger_id, row_json")
        last_prices = {}
        while batch := result.fetchmany(1000):
            for kind, charger_id, row_json in batch:
                row = json.loads(row_json)
                ts = _source_time(row["start_ts" if kind == "session_start" else
                                      "end_ts" if kind == "session_end" else "ts"])
                required, optional = PAYLOAD_FIELDS[kind]
                payload = {}
                for key in required | optional:
                    if row.get(key) not in (None, ""):
                        payload[key] = (_source_time(row[key]) if key == "charge_end_ts" else
                                        row[key] if key == "vehicle_model" else float(row[key]))
                if kind == "price_update":
                    price = payload["price_per_kwh"]
                    if last_prices.get(charger_id) == price:
                        continue
                    last_prices[charger_id] = price
                session = row.get("session_id")
                connector = int(row["connector_id"]) if row.get("connector_id") else None
                # Stable IDs let subscribers deduplicate a replay of the same run.
                identity = json.dumps([run_id, kind, charger_id, session, connector, ts.isoformat()])
                yield EVChargerStateEvent(run_id=run_id, id=uuid5(NAMESPACE_URL, identity).hex,
                                          type=kind, ts=ts, object_id=charger_id, session_id=session,
                                          connector_id=connector, payload=payload)
