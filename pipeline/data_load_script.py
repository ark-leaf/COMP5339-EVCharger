import duckdb

from pipeline.data_load.nsw_evc_load_utils import (
    load_charger_tables,
    load_connector_and_augmentation_tables,
    load_parent_tables,
)
from pipeline.data_load.nsw_evc_load_validation import (
    validate_final_database,
    validate_stage_2,
    validate_stage_3,
    validate_stage_4,
)
from pipeline.data_load.nsw_evc_load_config import DB_SCHEMA, DB_DATA

EXPECTED_TABLES = {
    "operator",
    "charger_location",
    "charger_characteristic",
    "charger_connector",
    "charger",
}

def nsw_evc_load():
    schema_sql = DB_SCHEMA.read_text(encoding="utf-8")
    DB_DATA.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(DB_DATA))
    try:
        conn.execute(schema_sql)
        conn.execute("LOAD spatial")

        tables = {
            row[2]
            for row in conn.execute("SELECT * FROM (SHOW ALL TABLES)").fetchall()
        }
        if tables != EXPECTED_TABLES:
            raise RuntimeError(f"Unexpected tables: {sorted(tables)}")

        print("tables:", sorted(tables))
        print("table_row_counts:")
        for table_name in sorted(EXPECTED_TABLES):
            row_count = conn.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            print(f"  {table_name}: {row_count}")
            if row_count != 0:
                raise RuntimeError(
                    f"Stage 1 expected an empty table: {table_name} has {row_count} rows"
                )

        print("describe charger_location:")
        charger_description = conn.execute(
            "SELECT * FROM (DESCRIBE charger_location)"
        ).fetchall()
        print(charger_description)
        geometry_columns = {
            ("charger_location", row[0])
            for row in charger_description
            if row[1] == "GEOMETRY"
        }
        expected_geometry_columns = {
            ("charger_location", "geom"),
        }
        if geometry_columns != expected_geometry_columns:
            raise RuntimeError(f"Unexpected geometry columns: {geometry_columns}")
        print("geometry_columns:", sorted(geometry_columns))

        source_operator_count = load_parent_tables(conn)
        validate_stage_2(
            conn,
            source_operator_count=source_operator_count,
        )
        print("spatial_extension: loaded")
        print("Loader Stage 2 passed — ready for Stage 3 charger loading.")

        stage_3_source = load_charger_tables(conn)
        validate_stage_3(
            conn,
            stage_3_source,
            source_operator_count=source_operator_count,
        )
        print(
            "Loader Stage 3 passed — ready for Stage 4 connector and "
            "augmentation loading."
        )

        stage_4_source = load_connector_and_augmentation_tables(conn)
        validate_stage_4(
            conn,
            stage_4_source,
            source_operator_count=source_operator_count,
            source_charger_count=stage_3_source["row_count"],
        )
        print(
            "Loader Stage 4 passed — ready for final spatial and database "
            "validation."
        )

        validate_final_database(
            conn,
            stage_3_source=stage_3_source,
            stage_4_source=stage_4_source,
            source_operator_count=source_operator_count,
        )
        print("Data Loading: final database validation passed.")
    finally:
        conn.close()



if __name__ == "__main__":
    nsw_evc_load()

