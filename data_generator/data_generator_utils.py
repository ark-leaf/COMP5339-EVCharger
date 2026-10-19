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
from uuid import NAMESPACE_URL, uuid4, uuid5

import duckdb

from repository.event.ev_charger_state_event import EVChargerStateEvent, PAYLOAD_FIELDS
from .data_generator_config import NEM_TIME
from . import generate_dataset as supplied

CSV_FIELDS = {
    "stations": "station_id name lat lon site_type connectors max_kw charger_type model_type assumptions base_price",
    "prices_hourly": "ts station_id price_per_kwh wholesale_per_kwh",
    "sessions": "session_id station_id connector_id site_type vehicle_model start_ts charge_end_ts end_ts charge_minutes energy_kwh avg_kw peak_kw price_per_kwh cost_aud",
    "session_metering": "ts type station_id connector_id session_id voltage_v current_a power_kw energy_kwh soc_pct",
}


def station_record(charger, config):
    """Keep database identity; record every synthetic default alongside the station."""
    kind = (charger.charger_type or "unknown").upper()
    model = "DC" if kind == "DC" else "AC"
    assumptions = [f"site_type assumed {config.default_site_type}"]
    if kind not in ("AC", "DC"):
        assumptions.append(f"{kind} simulated as hypothetical AC")
    plugs = charger.number_of_plugs
    if plugs is None or plugs <= 0:
        plugs = 1
        assumptions.append("missing plug count assumed 1")
    power = charger.rating_kw
    if power is None or not math.isfinite(power) or power <= 0:
        power = 50.0 if model == "DC" else 7.0
        assumptions.append(f"missing rating assumed {power:g} kW")
    return dict(station_id=charger.station_id, name=charger.station_name or charger.station_id,
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


def generate_dataset(chargers, config, *, wholesale=None):
    """Write all stations and time series. Injected hourly prices are for offline tests."""
    stations = [station_record(charger, config) for charger in chargers]
    if not stations or len({s["station_id"] for s in stations}) != len(stations):
        raise ValueError("Need at least one station, with unique Ass1 station IDs")
    start = datetime.fromisoformat(config.start).replace(tzinfo=NEM_TIME)
    hours = [start + timedelta(hours=i) for i in range(config.days * 24)]
    injected = wholesale is not None
    wholesale = load_wholesale_hourly(config) if wholesale is None else wholesale
    if any(h not in wholesale or not math.isfinite(wholesale[h]) for h in hours):
        raise ValueError("Hourly wholesale prices must cover the complete generation period")
    mean = sum(wholesale[h] for h in hours) / len(hours)
    rng, run_id = random.Random(config.seed), uuid4().hex
    config.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_dir / "manifest.json"
    manifest_path.unlink(missing_ok=True)  # A failed regeneration cannot look complete.
    counts = dict(stations=len(stations), prices=0, sessions=0, meters=0)
    with ExitStack() as stack:
        writers = {}
        for name, fields in CSV_FIELDS.items():
            stream = stack.enter_context((config.output_dir / f"{name}.csv").open("w", newline="", encoding="utf-8"))
            writers[name] = csv.DictWriter(stream, fieldnames=fields.split())
            writers[name].writeheader()
        for st in stations:
            base = supplied.station_base_price(st, rng)
            st["base_price"] = base
            writers["stations"].writerow(st)
            busy_until = [start] * st["connectors"]
            per_day = config.sessions_per_connector_day[st["site_type"] == "regional"]
            for hour in hours:
                price = supplied.dynamic_price(base, wholesale[hour], mean, hour.hour, config)
                writers["prices_hourly"].writerow(dict(ts=hour.isoformat(), station_id=st["station_id"],
                                                       price_per_kwh=price, wholesale_per_kwh=wholesale[hour]))
                counts["prices"] += 1
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
                        sid = f"{st['station_id']}-{c + 1}-{t0:%Y%m%d%H%M}"
                        row, meters, busy_until[c] = supplied.simulate_session(rng, st, c + 1, sid, t0, price, config)
                        writers["sessions"].writerow(row)
                        writers["session_metering"].writerows(meters)
                        counts["sessions"] += 1
                        counts["meters"] += len(meters)
    settings = {key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()}
    manifest = dict(run_id=run_id, counts=counts, settings=settings, source_time="AEST UTC+10",
                    wholesale_source="injected hourly prices (testing)" if injected else supplied.AEMO_URL,
                    assumptions="See stations.csv assumptions and README for AC model; "
                                "sessions started inside the period retain all tail events.")
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def _source_time(value):
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=NEM_TIME)


def generate_evc_state_update(output_dir, run_id=None):
    """Stream sorted event entities; replay preserves IDs and omits unchanged tariffs."""
    output_dir = Path(output_dir)
    if run_id is None:
        run_id = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))["run_id"]
    sources = [("prices_hourly", "price_update", "ts", 0),
               ("session_metering", "meter", "ts", 1),
               ("sessions", "session_end", "end_ts", 2),
               ("sessions", "session_start", "start_ts", 3)]
    queries, paths = [], []
    for name, kind, ts_column, priority in sources:
        queries.append(f"SELECT CAST({ts_column} AS TIMESTAMPTZ) AS event_time, {priority} AS priority, "
                       f"'{kind}' AS event_type, station_id, to_json(t) AS row_json "
                       "FROM read_csv(?, header=true, all_varchar=true) AS t")
        paths.append(str(output_dir / f"{name}.csv"))
    # DuckDB sorts on disk when necessary; no list of millions of Python events.
    with duckdb.connect(config={"memory_limit": "256MB", "threads": "2",
                                "temp_directory": str(output_dir / ".sort_tmp")}) as db:
        result = db.execute("SELECT event_type, station_id, row_json FROM (" +
                            " UNION ALL ".join(queries) + ") "
                            "ORDER BY event_time, priority, station_id, row_json", paths)
        last_prices = {}
        while batch := result.fetchmany(1000):
            for kind, station_id, row_json in batch:
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
                    if last_prices.get(station_id) == price:
                        continue
                    last_prices[station_id] = price
                session = row.get("session_id")
                connector = int(row["connector_id"]) if row.get("connector_id") else None
                identity = json.dumps([run_id, kind, station_id, session, connector, ts.isoformat()])
                yield EVChargerStateEvent(run_id=run_id, event_id=uuid5(NAMESPACE_URL, identity).hex,
                                          type=kind, ts=ts, station_id=station_id, session_id=session,
                                          connector_id=connector, payload=payload)
