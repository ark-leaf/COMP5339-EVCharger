EXPECTED_TABLES = {
    "operator",
    "sa4_region",
    "charger_location",
    "charger_characteristic",
    "charger_connector",
    "augmentation_record",
}


def validate_stage_2(
    conn,
    source_operator_count,
    source_sa4_count,
    source_geometry_null_count,
    source_geometry_non_null_count,
    source_crs,
):
    operator_count = conn.execute("SELECT COUNT(*) FROM operator").fetchone()[0]
    distinct_operator_count = conn.execute(
        "SELECT COUNT(DISTINCT operator_name) FROM operator"
    ).fetchone()[0]
    duplicate_operator_ids = conn.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT operator_id) FROM operator"
    ).fetchone()[0]
    null_operator_names = conn.execute(
        "SELECT COUNT(*) FROM operator WHERE operator_name IS NULL"
    ).fetchone()[0]
    if operator_count != source_operator_count:
        raise RuntimeError(
            "operator source/database row count mismatch: "
            f"source={source_operator_count}, database={operator_count}"
        )
    if operator_count != distinct_operator_count or duplicate_operator_ids != 0:
        raise RuntimeError("operator uniqueness validation failed")
    if null_operator_names != 0:
        raise RuntimeError("operator_name contains NULL")

    sa4_count = conn.execute("SELECT COUNT(*) FROM sa4_region").fetchone()[0]
    duplicate_sa4_codes = conn.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT sa4_code) FROM sa4_region"
    ).fetchone()[0]
    null_sa4_codes = conn.execute(
        "SELECT COUNT(*) FROM sa4_region WHERE sa4_code IS NULL"
    ).fetchone()[0]
    null_geometries = conn.execute(
        "SELECT COUNT(*) FROM sa4_region WHERE geometry IS NULL"
    ).fetchone()[0]
    non_null_geometries = conn.execute(
        "SELECT COUNT(*) FROM sa4_region WHERE geometry IS NOT NULL"
    ).fetchone()[0]
    if sa4_count != source_sa4_count:
        raise RuntimeError(
            "sa4_region source/database row count mismatch: "
            f"source={source_sa4_count}, database={sa4_count}"
        )
    if source_crs != "EPSG:7844":
        raise RuntimeError(f"Unexpected SA4 source CRS: {source_crs}")
    if duplicate_sa4_codes != 0 or null_sa4_codes != 0:
        raise RuntimeError("sa4_region validation failed")
    if null_geometries != source_geometry_null_count:
        raise RuntimeError(
            "sa4_region NULL geometry count mismatch: "
            f"source={source_geometry_null_count}, database={null_geometries}"
        )
    if non_null_geometries != source_geometry_non_null_count:
        raise RuntimeError(
            "sa4_region non-NULL geometry count mismatch: "
            f"source={source_geometry_non_null_count}, "
            f"database={non_null_geometries}"
        )

    print("stage_2_validation:")
    print(f"  source_operator_distinct_count: {source_operator_count}")
    print(f"  operator_rows: {operator_count}")
    print(f"  operator_distinct_names: {distinct_operator_count}")
    print(f"  source_sa4_rows: {source_sa4_count}")
    print(f"  source_geometry_non_nulls: {source_geometry_non_null_count}")
    print(f"  source_geometry_nulls: {source_geometry_null_count}")
    print(f"  sa4_region_rows: {sa4_count}")
    print(f"  sa4_source_crs: {source_crs}")
    print(f"  sa4_region_geometry_non_nulls: {non_null_geometries}")
    print(f"  sa4_region_geometry_nulls: {null_geometries}")
    for table_name in sorted(EXPECTED_TABLES - {"operator", "sa4_region"}):
        row_count = conn.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]
        print(f"  {table_name}: {row_count}")
        if row_count != 0:
            raise RuntimeError(f"Stage 2 must leave {table_name} empty")


def validate_stage_3(
    conn, source, source_operator_count, source_sa4_count
):
    charger_location_count = conn.execute(
        "SELECT COUNT(*) FROM charger_location"
    ).fetchone()[0]
    duplicate_charger_ids = conn.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT charger_id) FROM charger_location"
    ).fetchone()[0]
    null_operator_ids = conn.execute(
        "SELECT COUNT(*) FROM charger_location WHERE operator_id IS NULL"
    ).fetchone()[0]
    null_geometries = conn.execute(
        "SELECT COUNT(*) FROM charger_location WHERE geom IS NULL"
    ).fetchone()[0]
    null_sa4_codes = conn.execute(
        "SELECT COUNT(*) FROM charger_location WHERE sa4_code IS NULL"
    ).fetchone()[0]

    if charger_location_count != source["row_count"]:
        raise RuntimeError("charger_location source/database row count mismatch")
    if duplicate_charger_ids != 0:
        raise RuntimeError("charger_location contains duplicate charger_id")
    if null_operator_ids != 0 or source["operator_unmatched_count"] != 0:
        raise RuntimeError("charger_location operator mapping validation failed")
    if null_geometries != source["coordinate_null_count"]:
        raise RuntimeError("charger_location geometry NULL count mismatch")
    if null_sa4_codes != source["sa4_null_count"]:
        raise RuntimeError("charger_location SA4 NULL count mismatch")
    if source["geometry_crs"] != "EPSG:7844":
        raise RuntimeError(
            f"Unexpected charger geometry CRS: {source['geometry_crs']}"
        )

    characteristic_count = conn.execute(
        "SELECT COUNT(*) FROM charger_characteristic"
    ).fetchone()[0]
    characteristic_distinct_ids = conn.execute(
        "SELECT COUNT(DISTINCT charger_id) FROM charger_characteristic"
    ).fetchone()[0]
    orphan_characteristics = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger_characteristic AS characteristic
        LEFT JOIN charger_location AS location
            ON characteristic.charger_id = location.charger_id
        WHERE location.charger_id IS NULL
        """
    ).fetchone()[0]
    missing_characteristics = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger_location AS location
        LEFT JOIN charger_characteristic AS characteristic
            ON location.charger_id = characteristic.charger_id
        WHERE characteristic.charger_id IS NULL
        """
    ).fetchone()[0]
    characteristic_nulls = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE charger_type IS NULL),
            COUNT(*) FILTER (WHERE number_of_plugs IS NULL),
            COUNT(*) FILTER (WHERE rating_raw IS NULL),
            COUNT(*) FILTER (WHERE rating_kw IS NULL)
        FROM charger_characteristic
        """
    ).fetchone()

    if characteristic_count != charger_location_count:
        raise RuntimeError("charger_characteristic row count mismatch")
    if characteristic_distinct_ids != characteristic_count:
        raise RuntimeError("charger_characteristic charger_id is not unique")
    if orphan_characteristics != 0 or missing_characteristics != 0:
        raise RuntimeError("charger_characteristic 1:1 relationship failed")
    expected_characteristic_nulls = (
        source["charger_type_null_count"],
        source["number_of_plugs_null_count"],
        source["rating_raw_null_count"],
        source["rating_kw_null_count"],
    )
    if characteristic_nulls != expected_characteristic_nulls:
        raise RuntimeError(
            "charger_characteristic NULL counts mismatch: "
            f"source={expected_characteristic_nulls}, "
            f"database={characteristic_nulls}"
        )

    operator_count = conn.execute("SELECT COUNT(*) FROM operator").fetchone()[0]
    sa4_count = conn.execute("SELECT COUNT(*) FROM sa4_region").fetchone()[0]
    connector_count = conn.execute(
        "SELECT COUNT(*) FROM charger_connector"
    ).fetchone()[0]
    augmentation_count = conn.execute(
        "SELECT COUNT(*) FROM augmentation_record"
    ).fetchone()[0]
    if (
        operator_count != source_operator_count
        or sa4_count != source_sa4_count
    ):
        raise RuntimeError("Stage 3 changed frozen parent-table row counts")
    if connector_count != 0 or augmentation_count != 0:
        raise RuntimeError("Stage 3 must leave child loading tables empty")

    print("stage_3_validation:")
    print(f"  source_charger_rows: {source['row_count']}")
    print(f"  charger_location_rows: {charger_location_count}")
    print(f"  charger_id_duplicates: {duplicate_charger_ids}")
    print(f"  operator_mapping_unmatched: {source['operator_unmatched_count']}")
    print(f"  operator_id_nulls: {null_operator_ids}")
    print(f"  charger_geometry_crs: {source['geometry_crs']}")
    print(f"  charger_geometry_nulls: {null_geometries}")
    print(f"  source_sa4_code_nulls: {source['sa4_null_count']}")
    print(f"  charger_location_sa4_code_nulls: {null_sa4_codes}")
    print(f"  charger_characteristic_rows: {characteristic_count}")
    print(f"  characteristic_orphans: {orphan_characteristics}")
    print(f"  characteristic_missing_rows: {missing_characteristics}")
    print(f"  charger_type_nulls: {characteristic_nulls[0]}")
    print(f"  number_of_plugs_nulls: {characteristic_nulls[1]}")
    print(f"  rating_raw_nulls: {characteristic_nulls[2]}")
    print(f"  rating_kw_nulls: {characteristic_nulls[3]}")
    print(f"  operator_rows: {operator_count}")
    print(f"  sa4_region_rows: {sa4_count}")
    print(f"  charger_connector: {connector_count}")
    print(f"  augmentation_record: {augmentation_count}")


def validate_stage_4(
    conn,
    source,
    source_operator_count,
    source_sa4_count,
    source_charger_count,
):
    connector_count = conn.execute(
        "SELECT COUNT(*) FROM charger_connector"
    ).fetchone()[0]
    connector_id_duplicates = conn.execute(
        """
        SELECT COUNT(*) - COUNT(DISTINCT charger_connector_id)
        FROM charger_connector
        """
    ).fetchone()[0]
    connector_nulls = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE charger_id IS NULL),
            COUNT(*) FILTER (WHERE connector_type IS NULL)
        FROM charger_connector
        """
    ).fetchone()
    connector_pair_duplicates = conn.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT charger_id, connector_type
            FROM charger_connector
            GROUP BY charger_id, connector_type
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    connector_orphans = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger_connector AS connector
        LEFT JOIN charger_location AS location
            ON connector.charger_id = location.charger_id
        WHERE location.charger_id IS NULL
        """
    ).fetchone()[0]
    if connector_count != source["deduplicated_connector_count"]:
        raise RuntimeError("charger_connector source/database count mismatch")
    if connector_id_duplicates != 0 or connector_pair_duplicates != 0:
        raise RuntimeError("charger_connector duplicate validation failed")
    if connector_nulls != (0, 0) or connector_orphans != 0:
        raise RuntimeError("charger_connector NULL/FK validation failed")

    augmentation_count = conn.execute(
        "SELECT COUNT(*) FROM augmentation_record"
    ).fetchone()[0]
    augmentation_id_duplicates = conn.execute(
        """
        SELECT COUNT(*) - COUNT(DISTINCT augmentation_id)
        FROM augmentation_record
        """
    ).fetchone()[0]
    augmentation_charger_nulls = conn.execute(
        """
        SELECT COUNT(*) FROM augmentation_record WHERE charger_id IS NULL
        """
    ).fetchone()[0]
    augmentation_orphans = conn.execute(
        """
        SELECT COUNT(*)
        FROM augmentation_record AS augmentation
        LEFT JOIN charger_location AS location
            ON augmentation.charger_id = location.charger_id
        WHERE location.charger_id IS NULL
        """
    ).fetchone()[0]
    augmentation_fields = list(source["augmentation_null_counts"])
    database_augmentation_null_counts = {}
    for field in augmentation_fields:
        database_augmentation_null_counts[field] = conn.execute(
            f"SELECT COUNT(*) FROM augmentation_record WHERE {field} IS NULL"
        ).fetchone()[0]
    if augmentation_count != source["accepted_count"]:
        raise RuntimeError("augmentation_record accepted/database count mismatch")
    if augmentation_id_duplicates != 0:
        raise RuntimeError("augmentation_record contains duplicate IDs")
    if augmentation_charger_nulls != 0 or augmentation_orphans != 0:
        raise RuntimeError("augmentation_record NULL/FK validation failed")
    if (
        database_augmentation_null_counts
        != source["augmentation_null_counts"]
    ):
        raise RuntimeError(
            "augmentation_record NULL counts mismatch: "
            f"source={source['augmentation_null_counts']}, "
            f"database={database_augmentation_null_counts}"
        )

    frozen_counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM operator),
            (SELECT COUNT(*) FROM sa4_region),
            (SELECT COUNT(*) FROM charger_location),
            (SELECT COUNT(*) FROM charger_characteristic)
        """
    ).fetchone()
    expected_frozen_counts = (
        source_operator_count,
        source_sa4_count,
        source_charger_count,
        source_charger_count,
    )
    if frozen_counts != expected_frozen_counts:
        raise RuntimeError(
            f"Stage 4 changed frozen tables: {frozen_counts}"
        )
    charger_characteristic_1_to_1 = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger_location AS location
        FULL JOIN charger_characteristic AS characteristic
            ON location.charger_id = characteristic.charger_id
        WHERE location.charger_id IS NULL
           OR characteristic.charger_id IS NULL
        """
    ).fetchone()[0]
    if charger_characteristic_1_to_1 != 0:
        raise RuntimeError("Stage 4 broke charger characteristic 1:1")

    print("stage_4_validation:")
    print(f"  source_accepted_rows: {source['accepted_count']}")
    print(f"  source_review_rows: {source['review_count']}")
    print(f"  source_unmatched_rows: {source['unmatched_count']}")
    print(
        "  accepted_duplicate_charger_rows: "
        f"{source['accepted_duplicate_charger_count']}"
    )
    print(
        "  source_accepted_connector_records: "
        f"{source['source_connector_record_count']}"
    )
    print(f"  connector_atomic_rows: {source['atomic_connector_count']}")
    print(
        "  connector_deduplicated_rows: "
        f"{source['deduplicated_connector_count']}"
    )
    print(f"  charger_connector_rows: {connector_count}")
    print(f"  charger_connector_id_duplicates: {connector_id_duplicates}")
    print(f"  charger_connector_pair_duplicates: {connector_pair_duplicates}")
    print(f"  charger_connector_orphans: {connector_orphans}")
    print(f"  augmentation_record_rows: {augmentation_count}")
    print(f"  augmentation_id_duplicates: {augmentation_id_duplicates}")
    print(f"  augmentation_charger_id_nulls: {augmentation_charger_nulls}")
    print(f"  augmentation_orphans: {augmentation_orphans}")
    for field in augmentation_fields:
        print(
            f"  {field}_nulls: "
            f"{database_augmentation_null_counts[field]}"
        )
    for field, counts in source["numeric_non_null_counts"].items():
        print(
            f"  {field}_numeric_non_nulls_before_after: "
            f"{counts[0]}/{counts[1]}"
        )
    print(f"  frozen_table_counts: {frozen_counts}")
    print(
        "  charger_location_characteristic_1_to_1_mismatches: "
        f"{charger_characteristic_1_to_1}"
    )


def validate_final_database(
    conn,
    stage_3_source,
    stage_4_source,
    source_operator_count,
    source_sa4_count,
    source_sa4_geometry_null_count,
    source_sa4_geometry_non_null_count,
):
    """Run final cross-table and spatial consistency checks for Task 4."""
    expected_counts = {
        "operator": source_operator_count,
        "sa4_region": source_sa4_count,
        "charger_location": stage_3_source["row_count"],
        "charger_characteristic": stage_3_source["row_count"],
        "charger_connector": stage_4_source[
            "deduplicated_connector_count"
        ],
        "augmentation_record": stage_4_source["accepted_count"],
    }
    table_counts = {
        table_name: conn.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]
        for table_name in sorted(EXPECTED_TABLES)
    }
    if table_counts != expected_counts:
        raise RuntimeError(
            f"Final table counts mismatch: {table_counts}"
        )

    primary_keys = {
        "operator": "operator_id",
        "sa4_region": "sa4_code",
        "charger_location": "charger_id",
        "charger_characteristic": "charger_id",
        "charger_connector": "charger_connector_id",
        "augmentation_record": "augmentation_id",
    }
    primary_key_duplicates = {
        table_name: conn.execute(
            f"""
            SELECT COUNT(*) - COUNT(DISTINCT {key_name})
            FROM {table_name}
            """
        ).fetchone()[0]
        for table_name, key_name in primary_keys.items()
    }
    if any(primary_key_duplicates.values()):
        raise RuntimeError(
            f"Final primary-key validation failed: {primary_key_duplicates}"
        )

    foreign_key_orphans = {
        "charger_location.operator_id": conn.execute(
            """
            SELECT COUNT(*)
            FROM charger_location AS location
            LEFT JOIN operator AS operator
                ON location.operator_id = operator.operator_id
            WHERE operator.operator_id IS NULL
            """
        ).fetchone()[0],
        "charger_location.sa4_code": conn.execute(
            """
            SELECT COUNT(*)
            FROM charger_location AS location
            LEFT JOIN sa4_region AS region
                ON location.sa4_code = region.sa4_code
            WHERE location.sa4_code IS NOT NULL
              AND region.sa4_code IS NULL
            """
        ).fetchone()[0],
        "charger_characteristic.charger_id": conn.execute(
            """
            SELECT COUNT(*)
            FROM charger_characteristic AS characteristic
            LEFT JOIN charger_location AS location
                ON characteristic.charger_id = location.charger_id
            WHERE location.charger_id IS NULL
            """
        ).fetchone()[0],
        "charger_connector.charger_id": conn.execute(
            """
            SELECT COUNT(*)
            FROM charger_connector AS connector
            LEFT JOIN charger_location AS location
                ON connector.charger_id = location.charger_id
            WHERE location.charger_id IS NULL
            """
        ).fetchone()[0],
        "augmentation_record.charger_id": conn.execute(
            """
            SELECT COUNT(*)
            FROM augmentation_record AS augmentation
            LEFT JOIN charger_location AS location
                ON augmentation.charger_id = location.charger_id
            WHERE location.charger_id IS NULL
            """
        ).fetchone()[0],
    }
    if any(foreign_key_orphans.values()):
        raise RuntimeError(
            f"Final foreign-key validation failed: {foreign_key_orphans}"
        )

    location_characteristic_mismatches = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger_location AS location
        FULL JOIN charger_characteristic AS characteristic
            ON location.charger_id = characteristic.charger_id
        WHERE location.charger_id IS NULL
           OR characteristic.charger_id IS NULL
        """
    ).fetchone()[0]
    connector_null_charger_ids, connector_null_types = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE charger_id IS NULL),
            COUNT(*) FILTER (WHERE connector_type IS NULL)
        FROM charger_connector
        """
    ).fetchone()
    connector_duplicates = conn.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT charger_id, connector_type
            FROM charger_connector
            GROUP BY charger_id, connector_type
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    augmentation_null_charger_ids = conn.execute(
        """
        SELECT COUNT(*) FROM augmentation_record WHERE charger_id IS NULL
        """
    ).fetchone()[0]
    if (
        location_characteristic_mismatches != 0
        or connector_null_charger_ids != 0
        or connector_null_types != 0
        or connector_duplicates != 0
        or augmentation_null_charger_ids != 0
    ):
        raise RuntimeError("Final relational NULL/uniqueness validation failed")

    database_augmentation_charger_ids = {
        row[0]
        for row in conn.execute(
            "SELECT charger_id FROM augmentation_record"
        ).fetchall()
    }
    accepted_charger_ids = stage_4_source["accepted_charger_ids"]
    review_leakage = len(
        database_augmentation_charger_ids
        & stage_4_source["review_charger_ids"]
    )
    unmatched_leakage = len(
        database_augmentation_charger_ids
        & stage_4_source["unmatched_charger_ids"]
    )
    if database_augmentation_charger_ids != accepted_charger_ids:
        raise RuntimeError("Final accepted augmentation ID set mismatch")
    if review_leakage != 0 or unmatched_leakage != 0:
        raise RuntimeError("Review/unmatched augmentation leakage detected")

    charger_total, charger_assigned, charger_unassigned = conn.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (WHERE sa4_code IS NOT NULL),
            COUNT(*) FILTER (WHERE sa4_code IS NULL)
        FROM charger_location
        """
    ).fetchone()
    spatial_consistent = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger_location AS location
        JOIN sa4_region AS region
            ON location.sa4_code = region.sa4_code
        WHERE location.sa4_code IS NOT NULL
          AND ST_Contains(region.geometry, location.geom)
        """
    ).fetchone()[0]
    spatial_mismatch_rows = conn.execute(
        """
        SELECT
            location.charger_id,
            location.station_name,
            location.sa4_code,
            location.latitude,
            location.longitude,
            COALESCE(ST_Intersects(region.geometry, location.geom), FALSE)
                AS intersects_diagnostic
        FROM charger_location AS location
        JOIN sa4_region AS region
            ON location.sa4_code = region.sa4_code
        WHERE location.sa4_code IS NOT NULL
          AND NOT COALESCE(
              ST_Contains(region.geometry, location.geom), FALSE
          )
        ORDER BY location.charger_id
        """
    ).fetchall()
    spatial_mismatch_count = len(spatial_mismatch_rows)
    if spatial_consistent + spatial_mismatch_count != charger_assigned:
        raise RuntimeError("Assigned charger spatial totals do not reconcile")

    unassigned_chargers = conn.execute(
        """
        SELECT charger_id, station_name, latitude, longitude
        FROM charger_location
        WHERE sa4_code IS NULL
        ORDER BY charger_id
        """
    ).fetchall()
    unassigned_candidates = conn.execute(
        """
        SELECT location.charger_id, region.sa4_code, region.sa4_name
        FROM charger_location AS location
        JOIN sa4_region AS region
            ON region.geometry IS NOT NULL
           AND ST_Intersects(region.geometry, location.geom)
        WHERE location.sa4_code IS NULL
        ORDER BY location.charger_id, region.sa4_code
        """
    ).fetchall()
    candidate_counts = {row[0]: 0 for row in unassigned_chargers}
    for charger_id, _, _ in unassigned_candidates:
        candidate_counts[charger_id] += 1

    charger_geometry_nulls = conn.execute(
        "SELECT COUNT(*) FROM charger_location WHERE geom IS NULL"
    ).fetchone()[0]
    sa4_geometry_nulls, sa4_geometry_non_nulls = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE geometry IS NULL),
            COUNT(*) FILTER (WHERE geometry IS NOT NULL)
        FROM sa4_region
        """
    ).fetchone()
    if charger_geometry_nulls != stage_3_source["coordinate_null_count"]:
        raise RuntimeError("Final charger geometry NULL count mismatch")
    if (
        sa4_geometry_nulls != source_sa4_geometry_null_count
        or sa4_geometry_non_nulls != source_sa4_geometry_non_null_count
    ):
        raise RuntimeError("Final SA4 geometry counts mismatch")

    print("Final Task 4 validation:")
    for table_name in (
        "operator",
        "sa4_region",
        "charger_location",
        "charger_characteristic",
        "charger_connector",
        "augmentation_record",
    ):
        print(f"  {table_name}_rows: {table_counts[table_name]}")
    print(f"  charger_sa4_assigned: {charger_assigned}")
    print(f"  charger_sa4_unassigned: {charger_unassigned}")
    print(f"  spatial_primary_predicate: ST_Contains")
    print(f"  spatial_consistent_assignments: {spatial_consistent}")
    print(f"  spatial_mismatches: {spatial_mismatch_count}")
    print(f"  primary_key_duplicates: {primary_key_duplicates}")
    print(f"  foreign_key_orphans: {foreign_key_orphans}")
    print(f"  connector_duplicates: {connector_duplicates}")
    print(
        "  location_characteristic_mismatches: "
        f"{location_characteristic_mismatches}"
    )
    print(f"  accepted_augmentation_rows: {len(accepted_charger_ids)}")
    print(f"  review_augmentation_leakage: {review_leakage}")
    print(f"  unmatched_augmentation_leakage: {unmatched_leakage}")
    print(f"  charger_geometry_nulls: {charger_geometry_nulls}")
    print(f"  sa4_geometry_non_nulls: {sa4_geometry_non_nulls}")
    print(f"  sa4_geometry_nulls: {sa4_geometry_nulls}")
    for charger_id, station_name, latitude, longitude in unassigned_chargers:
        print(
            "  unassigned_sa4_diagnostic: "
            f"charger_id={charger_id}, station_name={station_name!r}, "
            f"latitude={latitude}, longitude={longitude}, "
            f"intersecting_candidates={candidate_counts[charger_id]}"
        )

    if spatial_mismatch_rows:
        print("  spatial_mismatch_details:")
        for row in spatial_mismatch_rows:
            print(f"    {row}")
        raise RuntimeError(
            f"Spatial assignment mismatches found: {spatial_mismatch_count}"
        )

