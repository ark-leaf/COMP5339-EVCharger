# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with the station-reading queries and entity mapping.
from .duckdb_repo import DuckDBRepository
from .entity.ev_charger import EVCharger


_SELECT_CHARGERS = """
    SELECT l.charger_id, l.source_objectid, l.station_name, l.station_address,
           l.latitude, l.longitude, c.charger_type, c.number_of_plugs,
           c.rating_kw, o.operator_name
    FROM charger_location AS l
    LEFT JOIN charger_characteristic AS c ON c.charger_id = l.charger_id
    LEFT JOIN operator AS o ON o.operator_id = l.operator_id
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

    def list_augmented_charger_ids(self, region_prefix: str) -> tuple[int, ...]:
        """Accepted Ass1 augmentation records in SA4 regions starting with the prefix."""
        rows = self.repo.fetch_all("""
            SELECT DISTINCT a.charger_id FROM charger AS a
            JOIN charger_location AS l USING (charger_id)
            JOIN sa4_region AS r USING (sa4_code)
            WHERE starts_with(r.sa4_name, ?) ORDER BY a.charger_id
        """, [region_prefix])
        return tuple(row["charger_id"] for row in rows)

