"""Load and normalise Open Charge Map records for Task 3."""
from __future__ import annotations

import json
import math
from pathlib import Path

from shapely.geometry import Point

try:
    import geopandas as gpd
except ModuleNotFoundError:
    gpd = None


def _task3_normalise_ocm_record(poi: dict) -> dict:
    """Convert one OCM POI into the Task 3 intermediate format."""
    address_info = poi.get("AddressInfo") or {}
    connections = poi.get("Connections") or []
    operator_info = poi.get("OperatorInfo") or {}
    status_info = poi.get("StatusType") or {}
    provider_info = poi.get("DataProvider") or {}

    if not isinstance(address_info, dict):
        address_info = {}
    if not isinstance(connections, list):
        connections = []
    if not isinstance(operator_info, dict):
        operator_info = {}
    if not isinstance(status_info, dict):
        status_info = {}
    if not isinstance(provider_info, dict):
        provider_info = {}

    address_parts = []
    for field in (
        "AddressLine1", "AddressLine2", "Town", "StateOrProvince", "Postcode"
    ):
        value = address_info.get(field)
        if value:
            address_parts.append(str(value).strip())

    plug_types = set()
    powers_kw = set()
    dc_powers_kw = set()
    for connection in connections:
        if not isinstance(connection, dict):
            continue

        connection_type = connection.get("ConnectionType") or {}
        if isinstance(connection_type, dict):
            title = connection_type.get("Title")
            if title:
                plug_types.add(str(title).strip())

        try:
            power = float(connection.get("PowerKW"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(power) and power > 0:
            powers_kw.add(power)
            title = str(connection_type.get("Title", "")) if isinstance(connection_type, dict) else ""
            if "ccs" in title.lower() or "chademo" in title.lower():
                dc_powers_kw.add(power)

    return {
        "ev_station_id": poi.get("ID"),
        "station_name": str(address_info.get("Title") or ""),
        "station_address": ", ".join(address_parts),
        "postcode": str(address_info.get("Postcode") or ""),
        "operator": str(operator_info.get("Title") or ""),
        "data_provider": str(provider_info.get("Title") or ""),
        "latitude": address_info.get("Latitude"),
        "longitude": address_info.get("Longitude"),
        "plug_types": "; ".join(sorted(plug_types)),
        "charger_capacities": "; ".join(
            f"{power:g} kW" for power in sorted(powers_kw)
        ),
        "dc_power_kw_values": sorted(dc_powers_kw),
        "ocm_number_of_points": poi.get("NumberOfPoints"),
        "number_of_plugs": None,
        "status": str(status_info.get("Title") or ""),
        "is_operational": status_info.get("IsOperational"),
        "usage_cost": str(poi.get("UsageCost") or ""),
        "last_verified": str(poi.get("DateLastVerified") or ""),
        "general_comments": str(poi.get("GeneralComments") or ""),
        "access_comments": str(address_info.get("AccessComments") or ""),
        "opening_hours": "",
    }


def load_nsw_ocm_records(snapshot_file: Path, boundary_file: Path) -> tuple[list[dict], int]:
    """Load OCM records and retain locations inside the NSW boundary."""
    if gpd is None:
        raise RuntimeError("geopandas is required for NSW boundary filtering")

    payload = json.loads(Path(snapshot_file).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("OCM snapshot must contain a JSON list")

    records = [
        _task3_normalise_ocm_record(poi)
        for poi in payload
        if isinstance(poi, dict)
    ]

    valid_records = []
    points = []

    for record in records:
        try:
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
        except (TypeError, ValueError):
            continue

        coordinates_valid = (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        )
        if not coordinates_valid:
            continue

        record["latitude"] = latitude
        record["longitude"] = longitude
        valid_records.append(record)
        points.append(Point(longitude, latitude))

    if not valid_records:
        return [], len(records)

    boundary = gpd.read_file(f"zip://{Path(boundary_file)}")
    if boundary.crs is None or "STE_NAME26" not in boundary.columns:
        raise ValueError("NSW boundary has no CRS or state name column")

    nsw = boundary.loc[
        boundary["STE_NAME26"].eq("New South Wales")
    ]
    if nsw.empty:
        raise ValueError("NSW boundary is missing")

    nsw_geometry = nsw.geometry.union_all()

    locations = gpd.GeoDataFrame(
        valid_records,
        geometry=points,
        crs="EPSG:4326",
    ).to_crs(boundary.crs)

    inside_nsw = locations.geometry.intersects(nsw_geometry)
    nsw_records = locations.loc[inside_nsw].drop(
        columns="geometry"
    ).to_dict("records")

    return nsw_records, len(records)
