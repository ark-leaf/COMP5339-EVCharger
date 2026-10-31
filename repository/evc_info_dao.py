# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the station-reading queries and entity mapping.
import duckdb

from data_utils.duckdb_repo import DuckDBRepository
from entity.ev_charger import EVCharger


_SELECT_CHARGERS = """
    SELECT l.charger_id, l.source_objectid, l.station_name, l.station_address,
           l.latitude, l.longitude, c.charger_type, c.number_of_plugs,
           c.rating_kw, o.operator_name
    FROM charger_location AS l
    LEFT JOIN charger_characteristic AS c ON c.charger_id = l.charger_id
    LEFT JOIN operator AS o ON o.operator_id = l.operator_id
"""
# One row per charger: its area and the first accepted augmentation record, if any.
_SELECT_STATION_DETAILS = """
    SELECT l.charger_id, l.postcode, l.lga_name, s.sa4_name,
           a.external_opening_hours, a.external_access_condition, a.external_is_free,
           a.external_network, a.external_usage_cost
    FROM charger_location AS l
    LEFT JOIN sa4_region AS s ON s.sa4_code = l.sa4_code
    LEFT JOIN charger AS a ON a.charger_id = l.charger_id
    QUALIFY row_number() OVER (PARTITION BY l.charger_id ORDER BY a.augmentation_id NULLS LAST) = 1
"""


class EVChargerInfoDAO:
    def __init__(self, repo: DuckDBRepository):
        """Use a caller-owned connection, reusable by other DAOs."""
        self.repo = repo

    def list_chargers(self) -> list[EVCharger]:
        """All AC/DC locations, preserving IDs and missing joined attributes."""
        rows = self.repo.fetch_all(_SELECT_CHARGERS + " ORDER BY l.charger_id")
        return [EVCharger.from_record(row) for row in rows]

    def list_generation_chargers(self) -> list[EVCharger]:
        """Only registered, physically specified AC/DC stations may generate events."""
        rows = self.repo.fetch_all(_SELECT_CHARGERS + """
            WHERE EXISTS (SELECT 1 FROM charger a WHERE a.charger_id = l.charger_id)
              AND EXISTS (SELECT 1 FROM charger_connector cc WHERE cc.charger_id = l.charger_id)
              AND c.charger_type IN ('AC', 'DC') AND c.number_of_plugs > 0
            ORDER BY l.charger_id
        """)
        return [EVCharger.from_record(row) for row in rows]

    def get_charger(self, charger_id: int) -> EVCharger | None:
        if type(charger_id) is not int or charger_id <= 0:
            raise ValueError("charger_id must be a positive integer")
        rows = self.repo.fetch_all(_SELECT_CHARGERS + " WHERE l.charger_id = ?", [charger_id])
        return EVCharger.from_record(rows[0]) if rows else None

    def count_chargers(self) -> int:
        rows = self.repo.fetch_all("SELECT COUNT(*) AS charger_count FROM charger_location")
        return rows[0]["charger_count"]

    def list_connector_types(self) -> dict[int, tuple[str, ...]]:
        """Assignment 1 connector types by charger_id, e.g. ("CCS2", "CHAdeMO")."""
        types: dict[int, list[str]] = {}
        for row in self.repo.fetch_all("SELECT charger_id, connector_type FROM charger_connector "
                                       "ORDER BY charger_id, connector_type"):
            types.setdefault(row["charger_id"], []).append(row["connector_type"])
        return {charger_id: tuple(values) for charger_id, values in types.items()}

    def list_station_details(self) -> dict[int, dict]:
        """Postcode, LGA, SA4 region and augmentation fields by charger_id."""
        try:
            rows = self.repo.fetch_all(_SELECT_STATION_DETAILS)
        except (duckdb.CatalogException, duckdb.BinderException):
            return {}  # A minimal Assignment 1 database has no enrichment tables or columns.
        return {row["charger_id"]: row for row in rows}

    def list_augmented_charger_ids(self, region_prefix: str) -> tuple[int, ...]:
        """Accepted Ass1 augmentation records in SA4 regions starting with the prefix."""
        rows = self.repo.fetch_all("""
            SELECT DISTINCT a.charger_id FROM charger AS a
            JOIN charger_location AS l USING (charger_id)
            JOIN sa4_region AS r USING (sa4_code)
            WHERE starts_with(r.sa4_name, ?) ORDER BY a.charger_id
        """, [region_prefix])
        return tuple(row["charger_id"] for row in rows)

