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


class EVChargerDAO:
    def __init__(self, repo: DuckDBRepository):
        """Use a caller-owned connection, reusable by other DAOs."""
        self.repo = repo

    def list_chargers(self) -> list[EVCharger]:
        """All AC/DC locations, preserving IDs and missing joined attributes."""
        rows = self.repo.fetch_all(_SELECT_CHARGERS + " ORDER BY l.charger_id")
        return [EVCharger.from_record(row) for row in rows]

    def get_charger(self, charger_id: int) -> EVCharger | None:
        if type(charger_id) is not int or charger_id <= 0:
            raise ValueError("charger_id must be a positive integer")
        rows = self.repo.fetch_all(_SELECT_CHARGERS + " WHERE l.charger_id = ?", [charger_id])
        return EVCharger.from_record(rows[0]) if rows else None

    def count_chargers(self) -> int:
        rows = self.repo.fetch_all("SELECT COUNT(*) AS charger_count FROM charger_location")
        return rows[0]["charger_count"]

