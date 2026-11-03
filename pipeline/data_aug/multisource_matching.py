# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that I wrote/adapted the initial matching functions using OpenAI
# Codex references. Codex also revised source/attribute handling, candidate
# selection and shared-ID checks, and assisted with corrections and tests.

"""Normalise external charging records and match them to Task 2 DC rows."""
from __future__ import annotations

import json
import math
import re

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from pipeline.data_aug.nsw_evc_aug_config import (
    Task3Config, matching_input, display_path, COORDINATE_THRESHOLD_M,
    AUTO_COORDINATE_THRESHOLD_M, MIN_NEAREST_GAP_M, ADDRESS_THRESHOLD,
)
from pipeline.data_aug import charging_match_rules as relaxed
from pipeline.data_aug.charging_match_rules import as_float
from pipeline.data_aug.ocm_reference import load_nsw_ocm_records


def explicit_postcode(address) -> str:
    """Extract a postcode printed at the end of an address."""
    if address is None or pd.isna(address):
        return ""
    match = re.search(r"(?<!\d)(\d{4})(?!\d)\s*$", str(address))
    return match.group(1) if match else ""


def optional_bool(value) -> bool | None:
    """Preserve unknown values instead of treating them as false."""
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"true", "yes", "1"}:
        return True
    if token in {"false", "no", "0"}:
        return False
    return None


def as_positive_count(value, maximum: int = 100) -> int | None:
    """Keep positive whole counts within the chosen quality-review limit."""
    number = as_float(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    if number > maximum:
        return None
    return int(number)


def power_values(value) -> list[float]:
    """Read positive power values and convert explicit W/MW units to kW."""
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(power_values(item))
        return sorted(set(values))

    if isinstance(value, (int, float)):
        number = as_float(value)
        return [number] if number is not None and number > 0 else []

    text = str(value).strip()
    matches = re.findall(
        r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(kW|MW|W)\b",
        text,
        flags=re.IGNORECASE,
    )
    if matches:
        factors = {"w": 0.001, "kw": 1, "mw": 1000}
        values = [
            float(number) * factors[unit.lower()]
            for number, unit in matches
        ]
        return sorted(set(value for value in values if value > 0))

    # A bare number is interpreted as kW only because the source fields
    # calling this function are explicitly named PowerKW/max_power_kw.
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        number = float(text)
        return [number] if number > 0 else []
    return []


def power_attributes(value) -> dict[str, object]:
    """Summarise powers only when the input values share the same meaning."""
    values = power_values(value)
    return {
        "power_kw_values": values,
        "power_kw_min": min(values) if values else None,
        "power_kw_max": max(values) if values else None,
    }


def normalised_connectors(value) -> str:
    """Unify known connector labels while retaining unfamiliar source labels."""
    labels = set()
    parts = value if isinstance(value, (list, tuple, set)) else re.split(
        r"[;,|]", str(value or "")
    )
    for part in parts:
        raw = "" if part is None else str(part).strip()
        token = raw.lower().replace(" ", "")

        if not raw:
            continue
        if "chademo" in token:
            labels.add("CHAdeMO")
        elif "ccs" in token:
            labels.add("CCS")
        elif token in {"type2", "type2(socketonly)", "type2(tetheredconnector)"}:
            labels.add("Type2")
        else:
            labels.add(raw)  # Preserve an unknown connector rather than guessing.

    return ";".join(sorted(labels))


def external_id_text(value) -> str:
    """Keep source IDs as text, including any meaningful leading zeroes."""
    if value is None or pd.isna(value):
        return ""
    token = str(value).strip()
    if re.fullmatch(r"\d+\.0", token):
        return token[:-2]
    return token


def load_ocm_candidates(settings: Task3Config) -> list[dict]:
    """Convert the NSW OCM snapshot into the shared candidate format."""
    path = settings.snapshot_dir / "task3_ocm_tiled_snapshot.json"
    records, _ = load_nsw_ocm_records(path, settings.boundary_file)

    candidates = []
    for record in records:
        latitude = as_float(record.get("latitude"))
        longitude = as_float(record.get("longitude"))
        station_id = record.get("ev_station_id")
        if latitude is None or longitude is None or station_id is None:
            continue

        connectors = normalised_connectors(record.get("plug_types"))
        connector_set = set(connectors.split(";"))
        power = power_attributes(record.get("dc_power_kw_values"))

        candidates.append({
            "source": "OCM",
            "id": str(station_id),
            "latitude": latitude,
            "longitude": longitude,
            "address": record.get("station_address") or "",
            "postcode": record.get("postcode") or "",
            "operator": record.get("operator") or "",
            "station_name": record.get("station_name") or "",
            # Connector evidence describes DC capability; status is separate.
            "fast_dc": bool(connector_set & {"CCS", "CHAdeMO"}),
            "attributes": {
                "data_provider": "Open Charge Map",
                "plug_types": record.get("plug_types") or "",
                "charger_capacities": record.get("charger_capacities") or "",
                "connector_types_normalized": connectors,
                **power,
                "power_scope": "dc_indicated_connection_ratings",
                # OCM reports charging points, not necessarily physical plugs.
                "charging_point_count": record.get("ocm_number_of_points"),
                "number_of_plugs": None,
                "is_operational": optional_bool(record.get("is_operational")),
                "status": record.get("status") or "",
                "operator": record.get("operator") or "",
                "usage_cost": record.get("usage_cost") or "",
                "last_verified": record.get("last_verified") or "",
            },
        })
    return candidates


def load_osm_candidate_records(records: list[dict]) -> list[dict]:
    """Use the snapshot's WGS84 meta point, not its projected coordinates."""
    candidates = []
    socket_fields = {
        "has_socket_combo_ccs": "CCS",
        "has_socket_chademo": "CHAdeMO",
        "has_socket_type2": "Type2",
        "has_socket_ef": "Schuko/EF",
    }

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("meta_name_state") not in (None, "", "New South Wales"):
            continue
        point = record.get("meta_geo_point") or {}
        if not isinstance(point, dict):
            continue
        latitude = as_float(point.get("lat"))
        longitude = as_float(point.get("lon"))
        # Node and way numeric IDs are different namespaces in OSM.
        station_id = record.get("meta_osm_url") or record.get("meta_osm_id")
        if (latitude is None or longitude is None or not station_id
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            continue

        connectors = {
            label
            for field, label in socket_fields.items()
            if optional_bool(record.get(field)) is True
        }
        power = as_float(record.get("max_power_kw"))
        if power is not None and power <= 0:
            power = None
        raw_count = record.get("charge_points_count")

        candidates.append({
            "source": "OSM",
            "id": str(station_id),
            "latitude": latitude,
            "longitude": longitude,
            "address": "",   # This snapshot has no street-address field.
            "postcode": "",
            "operator": record.get("operator_name") or "",
            "station_name": record.get("station_name") or "",
            "fast_dc": bool(connectors & {"CCS", "CHAdeMO"}),
            "attributes": {
                "data_provider": "OpenStreetMap",
                "connector_types_normalized": ";".join(sorted(connectors)),
                "charging_point_count": as_positive_count(raw_count),
                # Preserve rejected counts for later quality review.
                "charging_point_count_raw": raw_count,
                "number_of_plugs": None,
                "power_kw_min": None,  # The source reports only a maximum.
                "power_kw_max": power,
                "power_scope": "station_reported_maximum",
                "opening_hours": record.get("opening_hours") or "",
                "access_condition": record.get("access_condition") or "",
                "is_free": optional_bool(record.get("is_free")),
                "allows_card_payment": optional_bool(
                    record.get("allows_card_payment")
                ),
                "allows_reservation": optional_bool(
                    record.get("allows_reservation")
                ),
                "network": record.get("network_name") or "",
                "pricing_info": record.get("pricing_info") or "",
            },
        })
    return candidates


def load_chargelarge_candidates(settings: Task3Config) -> list[dict]:
    """Keep NSW stations and count DC ports, not connector labels or devices."""
    path = settings.snapshot_dir / "task3_chargelarge_raw.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Charge@Large snapshot must contain a JSON list")

    candidates = []
    for station in payload:
        if not isinstance(station, dict):
            continue
        station_id = external_id_text(station.get("id"))
        coordinate = station.get("coordinate") or {}
        if not station_id or not isinstance(coordinate, dict):
            continue
        latitude = as_float(coordinate.get("latitude"))
        longitude = as_float(coordinate.get("longitude"))
        if (latitude is None or longitude is None
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            continue

        all_ports = []
        dc_ports = []
        connector_labels = set()
        seen_port_ids = set()
        for device in station.get("chargePoints") or []:
            if not isinstance(device, dict):
                continue
            for port in device.get("ports") or []:
                if not isinstance(port, dict):
                    continue
                # Port IDs are local to a device, so de-duplicate by both IDs.
                port_key = (
                    external_id_text(device.get("id")),
                    external_id_text(port.get("id")),
                )
                if all(port_key):
                    if port_key in seen_port_ids:
                        continue
                    seen_port_ids.add(port_key)
                all_ports.append(port)
                labels = set(normalised_connectors(
                    port.get("connectorTypes")
                ).split(";"))
                if labels & {"CCS", "CHAdeMO"}:
                    dc_ports.append(port)
                    connector_labels.update(labels - {""})

        dc_powers = [as_float(port.get("powerKilowatts")) for port in dc_ports]
        dc_powers = [power for power in dc_powers if power is not None and power > 0]
        status_counts = {}
        for port in dc_ports:
            status = str(port.get("status") or "").strip()
            if status:
                status_counts[status] = status_counts.get(status, 0) + 1

        address = str(station.get("address") or "").strip()
        candidates.append({
            "source": "Charge@Large",
            "id": station_id,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "postcode": explicit_postcode(address),
            "operator": "",  # The raw station payload does not identify a CPO.
            "station_name": str(station.get("name") or ""),
            "fast_dc": bool(dc_ports),
            "attributes": {
                "data_provider": "Charge@Large",
                "connector_types_normalized": ";".join(sorted(connector_labels)),
                "dc_port_count": len(dc_ports) if dc_ports else None,
                "total_port_count": len(all_ports) if all_ports else None,
                # A port with two connectors is one port, not two plugs.
                "number_of_plugs": None,
                "power_kw_values": sorted(set(dc_powers)),
                "power_kw_min": min(dc_powers) if dc_powers else None,
                "power_kw_max": max(dc_powers) if dc_powers else None,
                "power_scope": "dc_indicated_ports",
                "status_counts": status_counts,
                "status_observed_at": None,
                "site_power_range_raw": station.get("powerRange"),
            },
        })

    if not candidates:
        return []
    boundary = gpd.read_file(f"zip://{settings.boundary_file}")
    if boundary.crs is None or "STE_NAME26" not in boundary.columns:
        raise ValueError("NSW boundary has no CRS or state name column")
    nsw = boundary.loc[boundary["STE_NAME26"].eq("New South Wales")]
    if nsw.empty:
        raise ValueError("NSW boundary is missing")

    points = gpd.GeoSeries(
        [Point(item["longitude"], item["latitude"]) for item in candidates],
        crs="EPSG:4326",
    ).to_crs(boundary.crs)
    nsw_geometry = nsw.geometry.union_all()
    return [
        item for item, point in zip(candidates, points)
        if point.intersects(nsw_geometry)
    ]


def source_row_candidates(source: pd.DataFrame, candidates: list[dict]) -> pd.DataFrame:
    """Find candidates within 500 m and apply the conservative acceptance gate."""
    # Candidate addresses do not change between source rows. Parse each once.
    prepared = [
        (candidate, relaxed.address_parts(candidate.get("address"), candidate.get("postcode")))
        for candidate in candidates
        if candidate.get("fast_dc") is True
        and (candidate.get("attributes") or {}).get("is_operational") is not False
    ]
    rows = []
    for source_index, row in source.iterrows():
        raw_address = row.get("Station_address")
        source_address = (
            "" if raw_address is None or pd.isna(raw_address)
            else str(raw_address).strip()
        )
        source_parts = relaxed.address_parts(source_address, row.get("PCODE"))
        printed_postcode = explicit_postcode(source_address)
        original_postcode = (
            external_id_text(row.get("PCODE_ORIGINAL"))
            or external_id_text(row.get("PCODE"))
        )
        source_postcode_conflict = bool(
            printed_postcode and original_postcode
            and printed_postcode != original_postcode
        )

        scored = []
        for candidate, candidate_parts in prepared:
            distance = as_float(relaxed.distance_metres(
                row.get("Latitude"), row.get("Longitude"),
                candidate.get("latitude"), candidate.get("longitude"),
            ))
            if distance is not None and distance < 0:
                distance = None
            coordinate_ok = (
                distance is not None and distance <= COORDINATE_THRESHOLD_M
            )

            candidate_address = str(candidate.get("address") or "").strip()
            score = as_float(relaxed.address_score(
                source_parts, candidate_parts
            )) or 0.0
            address_ok = bool(
                source_address and candidate_address
                and score >= ADDRESS_THRESHOLD
                and relaxed.address_accepted(
                    source_parts, candidate_parts, score
                )
            )
            if not (coordinate_ok or address_ok):
                continue

            # Prefer corroborated coordinates, then coordinate-only evidence.
            if coordinate_ok and address_ok:
                rank = 0
            elif coordinate_ok:
                rank = 1
            elif address_ok:
                rank = 2
            scored.append({
                "candidate": candidate,
                "candidate_parts": candidate_parts,
                "distance": distance,
                "address_score": score,
                "coordinate_ok": coordinate_ok,
                "address_ok": address_ok,
                "rank": rank,
            })

        scored.sort(key=lambda item: (
            item["rank"],
            item["distance"] if item["distance"] is not None else math.inf,
            -item["address_score"],
            external_id_text(item["candidate"].get("id")),
        ))
        nearby = sorted(
            (item for item in scored if item["coordinate_ok"]),
            key=lambda item: item["distance"],
        )
        gap = (
            nearby[1]["distance"] - nearby[0]["distance"]
            if len(nearby) >= 2 else None
        )
        best = scored[0] if scored else None
        selected = best["candidate"] if best else {}

        # Record the evidence before deciding whether attributes can be used.
        reasons = []
        if best:
            candidate_postcode = (
                explicit_postcode(selected.get("address"))
                or external_id_text(selected.get("postcode"))
            )
            comparable_postcode = printed_postcode or original_postcode
            if source_postcode_conflict:
                reasons.append("source address and original postcode conflict")
            if (candidate_postcode and comparable_postcode
                    and candidate_postcode != comparable_postcode):
                reasons.append("external postcode conflicts with source")

            source_house = source_parts.get("house_number", "")
            candidate_house = best["candidate_parts"].get("house_number", "")
            if source_house and candidate_house and source_house != candidate_house:
                reasons.append("house numbers conflict")
            if best["address_ok"] and (not source_house or not candidate_house):
                reasons.append("address evidence is street-level only")
            if (source_address and selected.get("address")
                    and not best["address_ok"]):
                reasons.append("address evidence is inconsistent")

            if not best["coordinate_ok"]:
                reasons.append(
                    f"address-only match; coordinates exceed {COORDINATE_THRESHOLD_M:g} m"
                )
            if gap is not None and gap < MIN_NEAREST_GAP_M:
                reasons.append("another coordinate candidate is similarly close")
            if (nearby and best["coordinate_ok"] and best is not nearby[0]
                    and best["distance"] - nearby[0]["distance"]
                    > MIN_NEAREST_GAP_M):
                reasons.append("selected candidate is not the nearest location")
            if len(scored) > 1 and best["rank"] == scored[1]["rank"]:
                second = scored[1]
                distances_close = (
                    best["distance"] is not None
                    and second["distance"] is not None
                    and abs(best["distance"] - second["distance"])
                    < MIN_NEAREST_GAP_M
                )
                scores_close = (
                    not best["coordinate_ok"]
                    and abs(best["address_score"] - second["address_score"])
                    < 0.05
                )
                if distances_close or scores_close:
                    reasons.append("multiple candidates have similar evidence")

        blocking = any(
            phrase in reason
            for reason in reasons
            for phrase in ("postcode", "house numbers conflict", "similarly close",
                           "similar evidence", "not the nearest")
        )
        corroborated = bool(best and best["address_ok"]
                            and source_parts["house_number"]
                            and best["candidate_parts"]["house_number"])
        automatic = bool(best and best["coordinate_ok"] and not blocking
                         and (best["distance"] <= AUTO_COORDINATE_THRESHOLD_M
                              or corroborated))
        if best and best["coordinate_ok"] and not automatic:
            reasons.append("candidate does not pass the automatic identity gate")
        status = "unmatched" if best is None else "accepted" if automatic else "review"
        method = "unmatched"
        if best is not None:
            if best["coordinate_ok"] and best["address_ok"]:
                method = "coordinate_and_fuzzy_address"
            elif best["coordinate_ok"]:
                method = "coordinate_only"
            else:
                method = "fuzzy_address_only"

        rows.append({
            "source_index": source_index,
            "source_station_address": source_address,
            "source_operator": row.get("Operator", ""),
            "source_pcode_original": original_postcode,
            "source_pcode_repaired_from_address": (
                optional_bool(row.get("PCODE_REPAIRED_FROM_ADDRESS")) is True
            ),
            "source_postcode_conflict": source_postcode_conflict,
            "match_status": status,
            "review_reason": "; ".join(reasons) if status == "review" else "",
            "match_quality_flags": "; ".join(reasons) if status == "accepted" else "",
            "match_method": method,
            "match_distance_m": best["distance"] if best else None,
            "address_score": best["address_score"] if best else None,
            "candidate_count": len(scored),
            "coordinate_candidate_count": len(nearby),
            "nearest_coordinate_gap_m": gap,
            "matched_id": external_id_text(selected.get("id")),
            "matched_station_name": selected.get("station_name", ""),
            "matched_address": selected.get("address", ""),
            "matched_operator": selected.get("operator", ""),
            "matched_fast_dc_indicator": selected.get("fast_dc"),
            "matched_attributes": json.dumps(
                selected.get("attributes", {}), ensure_ascii=False, sort_keys=True
            ),
        })
    return pd.DataFrame(rows, index=source.index)


def resolve_reused_ids(matches: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    """Allow co-located source rows, but review reuse across distinct sites."""
    accepted = matches.loc[matches["match_status"].eq("accepted")]
    for external_id, group in accepted.groupby("matched_id"):
        if len(group) < 2:
            continue
        indices = group["source_index"].astype(int).tolist()
        compatible = True
        for position, left_index in enumerate(indices):
            left = source.loc[left_index]
            left_address = relaxed.address_parts(left.get("Station_address"), left.get("PCODE"))
            for right_index in indices[position + 1:]:
                right = source.loc[right_index]
                right_address = relaxed.address_parts(right.get("Station_address"), right.get("PCODE"))
                distance = relaxed.distance_metres(
                    left["Latitude"], left["Longitude"], right["Latitude"], right["Longitude"]
                )
                same_address = (
                    bool(left_address["house_number"])
                    and bool(right_address["house_number"])
                    and relaxed.address_accepted(left_address, right_address,
                                                 relaxed.address_score(left_address, right_address))
                )
                if distance > 50 and not same_address:
                    compatible = False
        if not compatible:
            matches.loc[group.index, "match_status"] = "review"
            matches.loc[group.index, "review_reason"] = (
                f"external ID {external_id} is shared by distinct source sites"
            )
            matches.loc[group.index, "match_quality_flags"] = ""
    return matches


def run_matching(settings: Task3Config = Task3Config()) -> dict:
    """Write a deterministic three-source evidence table for Task 2 DC rows."""
    source = matching_input(settings)
    dc = source["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")
    source = source.loc[dc.fillna(False)].copy()
    if source.empty or not source.index.is_unique:
        raise ValueError("Task 2 DC rows must have a non-empty, unique index")

    osm_file = settings.snapshot_dir / "task3_osm_nsw_snapshot_for_multisource.json"
    osm_payload = json.loads(osm_file.read_text(encoding="utf-8"))
    if not isinstance(osm_payload, list):
        raise ValueError("OSM snapshot must contain a JSON list")

    ocm = load_ocm_candidates(settings)
    osm = load_osm_candidate_records(osm_payload)
    chargelarge = load_chargelarge_candidates(settings)
    source_groups = {
        "ocm": [item for item in ocm if item["fast_dc"]],
        "osm_fast_dc": [item for item in osm if item["fast_dc"]],
        "chargelarge_fast_dc": [
            item for item in chargelarge if item["fast_dc"]
        ],
    }
    per_source = {
        prefix: resolve_reused_ids(source_row_candidates(source, candidates), source)
        for prefix, candidates in source_groups.items()
    }

    output = source.copy(deep=True)
    output.insert(0, "source_index", source.index)
    field_names = {
        "match_status": "status",
        "match_method": "method",
        "match_distance_m": "distance_m",
        "address_score": "address_score",
        "matched_id": "id",
        "matched_address": "address",
        "matched_station_name": "station_name",
        "matched_operator": "operator",
        "matched_attributes": "attributes",
        "matched_fast_dc_indicator": "fast_dc_indicator",
        "candidate_count": "candidate_count",
        "coordinate_candidate_count": "coordinate_candidate_count",
        "nearest_coordinate_gap_m": "nearest_coordinate_gap_m",
        "review_reason": "review_reason",
        "match_quality_flags": "quality_flags",
        "source_postcode_conflict": "source_postcode_conflict",
    }
    for prefix, matches in per_source.items():
        if not matches.index.equals(source.index):
            raise ValueError(f"{prefix} matching changed Task 2 row identity")
        for source_column, suffix in field_names.items():
            output[f"{prefix}_{suffix}"] = matches[source_column]

    status_columns = [f"{prefix}_status" for prefix in source_groups]
    accepted = output[status_columns].eq("accepted").any(axis=1)
    review = output[status_columns].eq("review").any(axis=1)
    quality_columns = [f"{prefix}_quality_flags" for prefix in source_groups]
    accepted_quality_flags = (
        accepted & output[quality_columns].fillna("").ne("").any(axis=1)
    )
    output["combined_dc_indicated_status"] = [
        "accepted" if has_accepted else "review" if has_review else "unmatched"
        for has_accepted, has_review in zip(accepted, review)
    ]

    settings.matches_file.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(settings.matches_file, index=False)
    summary = {
        "source_dc_rows": len(source),
        "candidate_counts": {
            "ocm_nsw_all": len(ocm),
            "ocm_dc_indicated": len(source_groups["ocm"]),
            "osm_nsw": len(osm),
            "osm_fast_dc": len(source_groups["osm_fast_dc"]),
            "chargelarge_nsw": len(chargelarge),
            "chargelarge_fast_dc": len(source_groups["chargelarge_fast_dc"]),
        },
        "accepted_counts": {
            prefix: int(matches["match_status"].eq("accepted").sum())
            for prefix, matches in per_source.items()
        },
        "review_counts": {
            prefix: int(matches["match_status"].eq("review").sum())
            for prefix, matches in per_source.items()
        },
        "combined_dc_indicated_count": int(accepted.sum()),
        "accepted_with_quality_flags": int(accepted_quality_flags.sum()),
        "accepted_without_quality_flags": int(
            (accepted & ~accepted_quality_flags).sum()
        ),
        "combined_dc_review_only_count": int((review & ~accepted).sum()),
        "combined_dc_indicated_coverage": float(accepted.mean()),
        "rules": {
            "coordinate_or_fuzzy_address": True,
            "coordinate_threshold_m": COORDINATE_THRESHOLD_M,
            "automatic_coordinate_threshold_m": AUTO_COORDINATE_THRESHOLD_M,
            "minimum_nearest_gap_m": MIN_NEAREST_GAP_M,
            "address_threshold": ADDRESS_THRESHOLD,
            "postcode_conflicts_require_review": True,
            "house_number_conflicts_require_review": True,
            "coordinate_accepts_weak_address_evidence_within_100m": True,
            "address_only_requires_review": True,
            "ambiguous_candidates_require_review": True,
            "one_to_one_enforced": False,
            "reused_ids": "same numbered address or source points within 50 m; otherwise review",
        },
        "output_file": display_path(settings.matches_file),
        "osm_snapshot_file": display_path(osm_file),
    }
    summary_file = settings.result_dir / "task3_multisource_summary.json"
    summary_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
