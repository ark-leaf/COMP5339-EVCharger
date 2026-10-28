"""Read-only Assignment 1 data adapter for the dashboard.

The adapter deliberately opens a short-lived ``DuckDBRepository`` connection only
during startup, then closes it before the UI is built.  This keeps Step 1 separate
from the shared write connection used by the Assignment 2 event store in later
steps.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from repository.duckdb_repo import DuckDBRepository
from repository.entity.ev_charger import EVCharger
from repository.evc_info_dao import EVChargerInfoDAO
from view.dashboard_queries import DashboardEventSnapshot, DashboardQueryService


@dataclass(frozen=True)
class DashboardStation:
    """One Assignment 1 station and its real connector-type metadata."""

    charger: EVCharger
    connector_types: tuple[str, ...]
    postcode: str | None = None
    lga_name: str | None = None
    sa4_name: str | None = None
    external_opening_hours: str | None = None
    external_access_condition: str | None = None
    external_is_free: bool | None = None
    external_network: str | None = None
    external_usage_cost: str | None = None

    @property
    def has_valid_coordinates(self) -> bool:
        latitude, longitude = self.charger.latitude, self.charger.longitude
        return (
            latitude is not None
            and longitude is not None
            and math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        )


@dataclass(frozen=True)
class DashboardSnapshot:
    """Static initial data used by Step 1 and extended by later live-state steps."""

    total_chargers: int
    stations: tuple[DashboardStation, ...]
    events: DashboardEventSnapshot

    @property
    def mappable_stations(self) -> tuple[DashboardStation, ...]:
        return tuple(station for station in self.stations if station.has_valid_coordinates)


def load_dashboard_snapshot(db_path: str | Path | None = None,
                            run_id: str | None = None) -> DashboardSnapshot:
    """Load Assignment 1 station data without changing its database or schema.

    ``charger_connector.connector_type`` is Assignment 1 metadata.  It is never
    confused with Assignment 2's simulated ``connector_no``.
    """
    with DuckDBRepository(db_path) as repository:
        charger_dao = EVChargerInfoDAO(repository)
        chargers = charger_dao.list_chargers()
        connector_rows = repository.fetch_all(
            "SELECT charger_id, connector_type FROM charger_connector "
            "ORDER BY charger_id, connector_type"
        )
        connector_types: dict[int, list[str]] = {}
        for row in connector_rows:
            connector_types.setdefault(row["charger_id"], []).append(row["connector_type"])
        try:
            extra_rows = repository.fetch_all("""SELECT l.charger_id,l.postcode,l.lga_name,s.sa4_name,
                a.external_opening_hours,a.external_access_condition,a.external_is_free,a.external_network,a.external_usage_cost
                FROM charger_location l LEFT JOIN sa4_region s ON s.sa4_code=l.sa4_code
                LEFT JOIN charger a ON a.charger_id=l.charger_id
                QUALIFY row_number() OVER (PARTITION BY l.charger_id ORDER BY a.augmentation_id NULLS LAST)=1""")
        except Exception:  # Minimal Assignment 1 fixtures intentionally omit enrichment tables.
            extra_rows = []
        extra = {row["charger_id"]: row for row in extra_rows}
        stations = tuple(DashboardStation(charger, tuple(connector_types.get(charger.charger_id, [])),
            **{key: extra.get(charger.charger_id, {}).get(key) for key in ("postcode", "lga_name", "sa4_name", "external_opening_hours", "external_access_condition", "external_is_free", "external_network", "external_usage_cost")}) for charger in chargers)
        events = DashboardQueryService(repository).load_snapshot(run_id)
        return DashboardSnapshot(
            total_chargers=charger_dao.count_chargers(), stations=stations, events=events,
        )


def database_guidance(db_path: str | Path) -> str:
    """Return a user-facing repair instruction for a missing Assignment 1 database."""
    return (
        f"找不到 Assignment 1 DuckDB：{Path(db_path)}。"
        "请先安装项目依赖，并在项目根目录执行 "
        "`python main_ass_1.py --stage load`；已有数据库请勿重新运行 Loader。"
    )
