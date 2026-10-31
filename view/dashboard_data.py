"""Dashboard data, read through the repository DAOs when a page opens.

Pages read with the process's shared DuckDB connection (SharedDuckDBRepository and
EVChargerEventDAO), the same connection main_ass_2's event store writes with.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math

from data_utils.duckdb_repo import SharedDuckDBRepository
from entity.ev_charger import EVCharger
from repository.evc_event_dao import EVChargerEventDAO
from repository.evc_info_dao import EVChargerInfoDAO
from view.dashboard_model import DashboardEventSnapshot, DashboardRunModel

_DETAIL_FIELDS = ("postcode", "lga_name", "sa4_name", "external_opening_hours", "external_access_condition",
                  "external_is_free", "external_network", "external_usage_cost")


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


def load_stations() -> tuple[tuple[DashboardStation, ...], int]:
    """Every Assignment 1 station with its connector types and area details, and the charger count.

    ``charger_connector.connector_type`` is Assignment 1 metadata. It is never confused
    with Assignment 2's simulated ``connector_no``.
    """
    dao = EVChargerInfoDAO(SharedDuckDBRepository())
    connector_types, details = dao.list_connector_types(), dao.list_station_details()
    stations = tuple(DashboardStation(charger, connector_types.get(charger.charger_id, ()),
                                      **{key: details.get(charger.charger_id, {}).get(key) for key in _DETAIL_FIELDS})
                     for charger in dao.list_chargers())
    return stations, dao.count_chargers()


def load_run_ids() -> tuple[str, ...]:
    """Runs with stored events, latest first; none before the event tables exist."""
    dao = EVChargerEventDAO()
    return dao.list_run_ids() if dao.has_tables() else ()


def load_run(run_id: str | None, charger_ids: Iterable[int]) -> tuple[tuple[str, ...], DashboardRunModel | None]:
    """Stored runs (latest first) and a model of run_id built from its stored events.

    None selects the latest stored run. A run with nothing stored yet, such as one whose
    first events are still reaching storage, gets an empty model. The model is None only
    when there is no run at all.
    """
    dao = EVChargerEventDAO()
    run_ids = dao.list_run_ids() if dao.has_tables() else ()
    run_id = run_id if run_id is not None else next(iter(run_ids), None)
    if run_id is None:
        return run_ids, None
    model = DashboardRunModel(run_id, charger_ids)
    if run_id in run_ids:
        for event in dao.list_run_events(run_id):
            model.apply(event)
    return run_ids, model
