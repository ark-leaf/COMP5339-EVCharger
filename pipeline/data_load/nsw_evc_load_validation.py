# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex generated and revised validation code during
# development and added SA4 integrity and spatial-consistency checks.
# Other validation logic derives from the team's staged implementation.
# Codex also added postcode format and source-to-database preservation checks.

EXPECTED_TABLES = {
    "operator",
    "sa4_region",
    "charger_location",
    "charger_characteristic",
    "charger_connector",
    "charger",
}


def validate_sa4_regions(conn, expected_count, source=None):
    """Check region integrity and preserve Task 2 assignments, including NULLs."""
    count, invalid = conn.execute("""
        SELECT COUNT(*), COUNT(*) FILTER (
            WHERE sa4_name IS NULL OR TRIM(sa4_name) = ''
               OR geometry IS NULL OR ST_IsEmpty(geometry)
               OR NOT ST_IsValid(geometry)
        ) FROM sa4_region
    """).fetchone()
    if count != expected_count or count == 0 or invalid:
        raise RuntimeError("SA4 region count/name/geometry validation failed")
    if source is None:
        return
    assignments = conn.execute(
        "SELECT charger_id, sa4_code FROM charger_location ORDER BY charger_id"
    ).fetchall()
    if assignments != sorted(source["sa4_assignments"]):
        raise RuntimeError("SA4 loading changed Task 2 assignments")
    orphans = conn.execute("""
        SELECT COUNT(*) FROM charger_location AS c
        LEFT JOIN sa4_region AS r ON c.sa4_code = r.sa4_code
        WHERE c.sa4_code IS NOT NULL AND r.sa4_code IS NULL
    """).fetchone()[0]
    # Use the same strict 'within' predicate and CRS as Task 2. This checks
    # missing and extra spatial assignments, not only foreign-key existence.
    spatial = conn.execute("""
        SELECT c.charger_id, r.sa4_code
        FROM charger_location AS c
        LEFT JOIN sa4_region AS r ON ST_Within(c.geom, r.geometry)
        ORDER BY c.charger_id, r.sa4_code
    """).fetchall()
    if orphans or spatial != assignments:
        raise RuntimeError("SA4 foreign-key or spatial assignment validation failed")
    print(f"  sa4_regions: {count}; assigned: {sum(code is not None for _, code in assignments)}; "
          f"unassigned: {sum(code is None for _, code in assignments)}; spatial_mismatches: 0")


def validate_stage_2(conn, source_operator_count, source_region_count):
    validate_sa4_regions(conn, source_region_count)
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

    print("stage_2_validation:")
    print(f"  source_operator_distinct_count: {source_operator_count}")
    print(f"  operator_rows: {operator_count}")
    print(f"  operator_distinct_names: {distinct_operator_count}")
    for table_name in sorted(EXPECTED_TABLES - {"operator", "sa4_region"}):
        row_count = conn.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]
        print(f"  {table_name}: {row_count}")
        if row_count != 0:
            raise RuntimeError(f"Stage 2 must leave {table_name} empty")


def validate_postcodes(conn, source):
    """Preserve source postcode identifiers, including leading zeroes and NULLs."""
    invalid = conn.execute("""
        SELECT COUNT(*) FROM charger_location
        WHERE postcode IS NOT NULL AND NOT regexp_full_match(postcode, '[0-9]{4}')
    """).fetchone()[0]
    actual = conn.execute(
        "SELECT charger_id, postcode FROM charger_location ORDER BY charger_id"
    ).fetchall()
    if invalid or actual != sorted(source["postcode_assignments"]):
        raise RuntimeError("Postcode format or source/database preservation failed")


def validate_stage_3(conn, source, source_operator_count):
    validate_sa4_regions(conn, source["sa4_region_count"], source)
    validate_postcodes(conn, source)
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

    if charger_location_count != source["row_count"]:
        raise RuntimeError("charger_location source/database row count mismatch")
    if duplicate_charger_ids != 0:
        raise RuntimeError("charger_location contains duplicate charger_id")
    if null_operator_ids != 0 or source["operator_unmatched_count"] != 0:
        raise RuntimeError("charger_location operator mapping validation failed")
    if null_geometries != source["coordinate_null_count"]:
        raise RuntimeError("charger_location geometry NULL count mismatch")
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
    connector_count = conn.execute(
        "SELECT COUNT(*) FROM charger_connector"
    ).fetchone()[0]
    augmentation_count = conn.execute(
        "SELECT COUNT(*) FROM charger"
    ).fetchone()[0]
    if operator_count != source_operator_count:
        raise RuntimeError("Stage 3 changed frozen operator table row count")
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
    print(f"  charger_characteristic_rows: {characteristic_count}")
    print(f"  characteristic_orphans: {orphan_characteristics}")
    print(f"  characteristic_missing_rows: {missing_characteristics}")
    print(f"  charger_type_nulls: {characteristic_nulls[0]}")
    print(f"  number_of_plugs_nulls: {characteristic_nulls[1]}")
    print(f"  rating_raw_nulls: {characteristic_nulls[2]}")
    print(f"  rating_kw_nulls: {characteristic_nulls[3]}")
    print(f"  operator_rows: {operator_count}")
    print(f"  charger_connector: {connector_count}")
    print(f"  charger: {augmentation_count}")


def validate_stage_4(
    conn,
    source,
    source_operator_count,
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
        "SELECT COUNT(*) FROM charger"
    ).fetchone()[0]
    augmentation_id_duplicates = conn.execute(
        """
        SELECT COUNT(*) - COUNT(DISTINCT augmentation_id)
        FROM charger
        """
    ).fetchone()[0]
    augmentation_charger_nulls = conn.execute(
        """
        SELECT COUNT(*) FROM charger WHERE charger_id IS NULL
        """
    ).fetchone()[0]
    augmentation_orphans = conn.execute(
        """
        SELECT COUNT(*)
        FROM charger AS augmentation
        LEFT JOIN charger_location AS location
            ON augmentation.charger_id = location.charger_id
        WHERE location.charger_id IS NULL
        """
    ).fetchone()[0]
    augmentation_fields = list(source["augmentation_null_counts"])
    database_augmentation_null_counts = {}
    for field in augmentation_fields:
        database_augmentation_null_counts[field] = conn.execute(
            f"SELECT COUNT(*) FROM charger WHERE {field} IS NULL"
        ).fetchone()[0]
    if augmentation_count != source["accepted_count"]:
        raise RuntimeError("charger accepted/database count mismatch")
    if augmentation_id_duplicates != 0:
        raise RuntimeError("charger contains duplicate IDs")
    if augmentation_charger_nulls != 0 or augmentation_orphans != 0:
        raise RuntimeError("charger NULL/FK validation failed")
    if (
        database_augmentation_null_counts
        != source["augmentation_null_counts"]
    ):
        raise RuntimeError(
            "charger NULL counts mismatch: "
            f"source={source['augmentation_null_counts']}, "
            f"database={database_augmentation_null_counts}"
        )

    frozen_counts = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM operator),
            (SELECT COUNT(*) FROM charger_location),
            (SELECT COUNT(*) FROM charger_characteristic)
        """
    ).fetchone()
    expected_frozen_counts = (
        source_operator_count,
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
    print(f"  charger_rows: {augmentation_count}")
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
):
    """Run final cross-table and spatial consistency checks for Task 4."""
    validate_postcodes(conn, stage_3_source)
    expected_counts = {
        "operator": source_operator_count,
        "sa4_region": stage_3_source["sa4_region_count"],
        "charger_location": stage_3_source["row_count"],
        "charger_characteristic": stage_3_source["row_count"],
        "charger_connector": stage_4_source[
            "deduplicated_connector_count"
        ],
        "charger": stage_4_source["accepted_count"],
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
        "charger": "augmentation_id",
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
        "charger_location.sa4_code": conn.execute(
            """
            SELECT COUNT(*) FROM charger_location AS location
            LEFT JOIN sa4_region AS region ON location.sa4_code = region.sa4_code
            WHERE location.sa4_code IS NOT NULL AND region.sa4_code IS NULL
            """
        ).fetchone()[0],
        "charger_location.operator_id": conn.execute(
            """
            SELECT COUNT(*)
            FROM charger_location AS location
            LEFT JOIN operator AS operator
                ON location.operator_id = operator.operator_id
            WHERE operator.operator_id IS NULL
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
        "charger.charger_id": conn.execute(
            """
            SELECT COUNT(*)
            FROM charger AS augmentation
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
        SELECT COUNT(*) FROM charger WHERE charger_id IS NULL
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
            "SELECT charger_id FROM charger"
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

    validate_sa4_regions(conn, stage_3_source["sa4_region_count"], stage_3_source)

    charger_geometry_nulls = conn.execute(
        "SELECT COUNT(*) FROM charger_location WHERE geom IS NULL"
    ).fetchone()[0]
    if charger_geometry_nulls != stage_3_source["coordinate_null_count"]:
        raise RuntimeError("Final charger geometry NULL count mismatch")
    print("Final Task 4 validation:")
    for table_name in (
        "operator",
        "sa4_region",
        "charger_location",
        "charger_characteristic",
        "charger_connector",
        "charger",
    ):
        print(f"  {table_name}_rows: {table_counts[table_name]}")
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
