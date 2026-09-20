from pathlib import Path

import duckdb

from task4_loaders import (
    load_charger_tables,
    load_connector_and_augmentation_tables,
    load_parent_tables,
)
from task4_validation import (
    validate_final_database,
    validate_stage_2,
    validate_stage_3,
    validate_stage_4,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DDL_PATH = PROJECT_ROOT / "sql" / "task4_schema.sql"
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "task4.duckdb"
EXPECTED_TABLES = {
    "operator",
    "sa4_region",
    "charger_location",
    "charger_characteristic",
    "charger_connector",
    "augmentation_record",
}


def main():
    schema_sql = DDL_PATH.read_text(encoding="utf-8")
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(DATABASE_PATH))
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
        print("describe sa4_region:")
        sa4_description = conn.execute(
            "SELECT * FROM (DESCRIBE sa4_region)"
        ).fetchall()
        print(sa4_description)
        geometry_columns = {
            ("charger_location", row[0])
            for row in charger_description
            if row[1] == "GEOMETRY"
        }
        geometry_columns.update(
            ("sa4_region", row[0])
            for row in sa4_description
            if row[1] == "GEOMETRY"
        )
        expected_geometry_columns = {
            ("charger_location", "geom"),
            ("sa4_region", "geometry"),
        }
        if geometry_columns != expected_geometry_columns:
            raise RuntimeError(f"Unexpected geometry columns: {geometry_columns}")
        print("geometry_columns:", sorted(geometry_columns))

        (
            source_operator_count,
            source_sa4_count,
            source_geometry_null_count,
            source_geometry_non_null_count,
            source_crs,
        ) = load_parent_tables(conn)
        validate_stage_2(
            conn,
            source_operator_count=source_operator_count,
            source_sa4_count=source_sa4_count,
            source_geometry_null_count=source_geometry_null_count,
            source_geometry_non_null_count=source_geometry_non_null_count,
            source_crs=source_crs,
        )
        print("spatial_extension: loaded")
        print("Loader Stage 2 passed — ready for Stage 3 charger loading.")

        stage_3_source = load_charger_tables(conn)
        validate_stage_3(
            conn,
            stage_3_source,
            source_operator_count=source_operator_count,
            source_sa4_count=source_sa4_count,
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
            source_sa4_count=source_sa4_count,
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
            source_sa4_count=source_sa4_count,
            source_sa4_geometry_null_count=source_geometry_null_count,
            source_sa4_geometry_non_null_count=(
                source_geometry_non_null_count
            ),
        )
        print("Task 4 final database validation passed.")
    finally:
        conn.close()



if __name__ == "__main__":
    main()

