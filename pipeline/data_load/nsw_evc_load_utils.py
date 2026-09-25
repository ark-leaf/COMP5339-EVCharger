# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex generated and revised augmentation-field mapping
# and boolean conversion in load_connector_and_augmentation_tables(). Codex also
# implemented SA4 region loading and foreign-key mapping, and helped verify
# these changes within the team's loading functions.

import geopandas as gpd
import pandas as pd

from config import NSW_EV_CHARGING_AUG_FILE, AUS_ASGS_LV4_FILE


def load_sa4_regions(conn):
    """Load NSW spatial SA4 regions from the same ABS file used by Task 2."""
    regions = gpd.read_file(AUS_ASGS_LV4_FILE)
    if regions.crs is None:
        raise ValueError("ABS SA4 boundaries have no CRS")
    regions = regions.loc[regions["STE_NAME26"].eq("New South Wales")].copy()
    # ABS also lists non-spatial categories (197/199); do not invent polygons.
    regions = regions.loc[regions.geometry.notna() & ~regions.geometry.is_empty]
    if regions.empty or not regions.geometry.is_valid.all():
        raise ValueError("NSW SA4 boundaries are empty or invalid")
    regions = regions.to_crs("EPSG:7844")
    # State is a retrieval filter; only the region identity and boundary are stored.
    region_input = pd.DataFrame(regions[["SA4_CODE26", "SA4_NAME26"]]).rename(columns={
        "SA4_CODE26": "sa4_code", "SA4_NAME26": "sa4_name",
    })
    region_input["sa4_code"] = region_input["sa4_code"].astype("string").str.strip()
    if region_input["sa4_code"].isna().any() or region_input["sa4_code"].duplicated().any():
        raise ValueError("ABS SA4 codes must be non-null and unique")
    region_input["geometry_wkt"] = regions.geometry.to_wkt(rounding_precision=-1)
    conn.execute("""
        INSERT INTO sa4_region
        SELECT sa4_code, sa4_name, ST_GeomFromText(geometry_wkt)
        FROM region_input
        ORDER BY sa4_code
    """)
    return len(region_input)


def load_parent_tables(conn):
    """Load operator parent table for Task 4 Stage 2."""
    chargers = pd.read_csv(NSW_EV_CHARGING_AUG_FILE)
    operators = (
        chargers[["Operator"]]
        .dropna()
        .drop_duplicates()
        .sort_values("Operator")
        .reset_index(drop=True)
    )
    source_operator_count = operators["Operator"].nunique()
    operators["operator_id"] = operators.index + 1
    operators["operator_name_normalised"] = operators["Operator"]
    operators = operators.rename(columns={"Operator": "operator_name"})[
        ["operator_id", "operator_name", "operator_name_normalised"]
    ]
    operator_input = operators
    conn.execute(
        """
        INSERT INTO operator
        SELECT operator_id, operator_name, operator_name_normalised
        FROM operator_input
        """
    )

    return source_operator_count


def load_charger_tables(conn):
    """Load charger_location and charger_characteristic for Task 4 Stage 3."""
    chargers = pd.read_csv(
        NSW_EV_CHARGING_AUG_FILE,
        dtype={"SA4_CODE26": "string"},
    ).reset_index(drop=True)
    source_row_count = len(chargers)
    chargers["charger_id"] = chargers.index + 1
    required = {"SA4_CODE26", "SA4_NAME26"}
    if not required.issubset(chargers.columns):
        raise ValueError("Task 4 requires Task 2 SA4 code and name columns")
    chargers["SA4_CODE26"] = chargers["SA4_CODE26"].str.strip().replace("", pd.NA)
    # Preserve the upstream spatial assignment rather than guessing a nearest region.
    region_names = dict(conn.execute("SELECT sa4_code, sa4_name FROM sa4_region").fetchall())
    assigned = chargers["SA4_CODE26"].notna()
    unknown = set(chargers.loc[assigned, "SA4_CODE26"]) - set(region_names)
    if unknown:
        raise ValueError(f"Task 2 references unknown NSW SA4 codes: {sorted(unknown)}")
    if not chargers.loc[assigned, "SA4_CODE26"].map(region_names).eq(
        chargers.loc[assigned, "SA4_NAME26"]
    ).all():
        raise ValueError("Task 2 SA4 names disagree with the ABS boundary file")

    operator_lookup = conn.execute(
        "SELECT operator_id, operator_name FROM operator"
    ).df()
    chargers = chargers.merge(
        operator_lookup,
        how="left",
        left_on="Operator",
        right_on="operator_name",
        sort=False,
        validate="many_to_one",
    )
    operator_unmatched_count = int(chargers["operator_id"].isna().sum())
    if operator_unmatched_count != 0:
        raise RuntimeError(
            f"Unable to map {operator_unmatched_count} chargers to operator_id"
        )

    source_coordinate_null_count = int(
        (chargers["Latitude"].isna() | chargers["Longitude"].isna()).sum()
    )
    charger_points = gpd.GeoDataFrame(
        chargers[["charger_id"]].copy(),
        geometry=gpd.points_from_xy(
            chargers["Longitude"], chargers["Latitude"]
        ),
        crs="EPSG:4326",
    ).to_crs("EPSG:7844")
    charger_geometry_crs = str(charger_points.crs)

    charger_location_input = pd.DataFrame(
        {
            "charger_id": chargers["charger_id"],
            "source_objectid": pd.to_numeric(
                chargers["OBJECTID"], errors="coerce"
            ).astype("Int64"),
            "station_name": chargers["Station_name"],
            "station_address": chargers["Station_address"],
            "operator_id": chargers["operator_id"],
            "latitude": chargers["Latitude"],
            "longitude": chargers["Longitude"],
            "postcode": chargers["PCODE"],
            "lga_name": chargers["LGANAME"],
            "source_category": chargers["Source"],
            "geom_wkt": charger_points.geometry.apply(
                lambda value: value.wkt if value is not None else None
            ),
            "sa4_code": chargers["SA4_CODE26"],
        }
    )
    conn.execute(
        """
        INSERT INTO charger_location
        SELECT
            charger_id, source_objectid, station_name, station_address,
            operator_id, latitude, longitude, postcode, lga_name,
            source_category, ST_GeomFromText(geom_wkt), sa4_code
        FROM charger_location_input
        """
    )

    rating_columns = [
        column
        for column in chargers.columns
        if column.startswith("Charger_rating.") and column.endswith("kW")
    ]
    rating_kw = pd.Series(pd.NA, index=chargers.index, dtype="Float64")
    for column in rating_columns:
        power_kw = float(column[len("Charger_rating.") : -len("kW")])
        has_rating = chargers[column].gt(0)
        rating_kw = rating_kw.mask(
            has_rating & (rating_kw.isna() | rating_kw.lt(power_kw)), power_kw
        )

    charger_characteristic_input = pd.DataFrame(
        {
            "charger_id": chargers["charger_id"],
            "charger_type": chargers["Charger_Type"],
            "number_of_plugs": chargers["Number_of_plugs"],
            "rating_raw": chargers["Charger_rating"],
            "rating_kw": rating_kw,
        }
    )
    conn.execute(
        """
        INSERT INTO charger_characteristic
        SELECT charger_id, charger_type, number_of_plugs, rating_raw, rating_kw
        FROM charger_characteristic_input
        """
    )

    return {
        "row_count": source_row_count,
        "operator_unmatched_count": operator_unmatched_count,
        "coordinate_null_count": source_coordinate_null_count,
        "charger_type_null_count": int(chargers["Charger_Type"].isna().sum()),
        "number_of_plugs_null_count": int(
            chargers["Number_of_plugs"].isna().sum()
        ),
        "rating_raw_null_count": int(chargers["Charger_rating"].isna().sum()),
        "rating_kw_null_count": int(rating_kw.isna().sum()),
        "geometry_crs": charger_geometry_crs,
        "sa4_region_count": len(region_names),
        "sa4_assignments": [
            (int(row.charger_id), None if pd.isna(row.SA4_CODE26) else row.SA4_CODE26)
            for row in chargers.itertuples()
        ],
    }


def load_connector_and_augmentation_tables(conn):
    """Load accepted Task 3 connector and augmentation rows for Stage 4."""
    chargers = pd.read_csv(
        NSW_EV_CHARGING_AUG_FILE,
    ).reset_index(drop=True)

    chargers["charger_id"] = chargers.index + 1

    status_counts = chargers["augmentation_match_status"].value_counts()
    accepted = chargers.loc[
        chargers["augmentation_match_status"].eq("accepted")
    ].copy()
    accepted_count = len(accepted)
    accepted_duplicate_charger_count = int(
        accepted["charger_id"].duplicated().sum()
    )

    connector_column = "external_connector_types_normalized"
    source_connector_record_count = int(
        accepted[connector_column].notna().sum()
    )
    atomic_connectors = []
    for _, row in accepted.iterrows():
        value = row[connector_column]
        if pd.isna(value):
            continue
        # Reuse the Task 3 final-adapter delimiter semantics. The source field
        # already contains Task 3's canonical connector names.
        for token in str(value).replace("|", ";").split(";"):
            connector_type = token.strip()
            if connector_type:
                atomic_connectors.append(
                    {
                        "charger_id": int(row["charger_id"]),
                        "connector_type": connector_type,
                    }
                )

    atomic_connector_count = len(atomic_connectors)
    connector_input = pd.DataFrame(
        atomic_connectors, columns=["charger_id", "connector_type"]
    )
    connector_input = (
        connector_input.drop_duplicates(
            subset=["charger_id", "connector_type"]
        )
        .sort_values(["charger_id", "connector_type"])
        .reset_index(drop=True)
    )
    connector_input.insert(
        0, "charger_connector_id", connector_input.index + 1
    )
    conn.execute(
        """
        INSERT INTO charger_connector
        SELECT charger_connector_id, charger_id, connector_type
        FROM connector_input
        """
    )

    numeric_fields = [
        "external_number_of_plugs",
        "external_power_kw_min",
        "external_power_kw_max",
        "augmentation_match_confidence",
    ]
    converted_numeric = {}
    numeric_non_null_counts = {}
    for field in numeric_fields:
        before_non_null = int(accepted[field].notna().sum())
        converted = pd.to_numeric(accepted[field], errors="coerce")
        after_non_null = int(converted.notna().sum())
        numeric_non_null_counts[field] = (
            before_non_null,
            after_non_null,
        )
        if before_non_null != after_non_null:
            invalid_examples = accepted.loc[
                accepted[field].notna() & converted.isna(), field
            ].drop_duplicates().tolist()
            raise RuntimeError(
                f"Numeric conversion lost {field} values: {invalid_examples}"
            )
        converted_numeric[field] = converted

    plug_values = converted_numeric["external_number_of_plugs"].dropna()
    if not plug_values.mod(1).eq(0).all():
        raise RuntimeError("external_number_of_plugs contains non-integers")
    converted_numeric["external_number_of_plugs"] = converted_numeric[
        "external_number_of_plugs"
    ].astype("Int64")

    for field, values in converted_numeric.items():
        accepted[field] = values
    accepted = accepted.sort_values("charger_id").reset_index(drop=True)
    accepted["augmentation_id"] = accepted.index + 1

    # Keep false distinct from unknown when moving CSV text into SQL BOOLEAN.
    for field in ("external_is_free", "augmentation_quality_review"):
        values = accepted[field].astype("string").str.strip().str.lower()
        boolean_values = values.map({"true": True, "false": False, "yes": True, "no": False})
        if (values.notna() & boolean_values.isna()).any():
            raise ValueError(f"Invalid boolean value in {field}")
        accepted[field] = boolean_values.astype("boolean")

    augmentation_fields = [
        "external_source",
        "external_station_id",
        "external_operator",
        "external_number_of_plugs",
        "external_power_kw_min",
        "external_power_kw_max",
        "external_usage_cost",
        "augmentation_match_method",
        "augmentation_match_confidence",
        "augmentation_quality_review_reason",
        "external_opening_hours",
        "external_network",
        "external_access_condition",
        "external_is_free",
        "augmentation_quality_review",
        "external_attributes_json",
    ]
    source_augmentation_null_counts = {
        field: int(accepted[field].isna().sum())
        for field in augmentation_fields
    }
    augmentation_input = accepted[
        ["augmentation_id", "charger_id", *augmentation_fields]
    ]
    conn.execute(
        """
        INSERT INTO charger
        SELECT
            augmentation_id, charger_id, external_source,
            external_station_id, external_operator,
            external_number_of_plugs, external_power_kw_min,
            external_power_kw_max, external_usage_cost,
            augmentation_match_method, augmentation_match_confidence,
            augmentation_quality_review_reason,
            external_opening_hours, external_network, external_access_condition,
            external_is_free, augmentation_quality_review, external_attributes_json
        FROM augmentation_input
        """
    )

    return {
        "accepted_count": accepted_count,
        "review_count": int(status_counts.get("review", 0)),
        "unmatched_count": int(status_counts.get("unmatched", 0)),
        "accepted_duplicate_charger_count": (
            accepted_duplicate_charger_count
        ),
        "source_connector_record_count": source_connector_record_count,
        "atomic_connector_count": atomic_connector_count,
        "deduplicated_connector_count": len(connector_input),
        "augmentation_null_counts": source_augmentation_null_counts,
        "numeric_non_null_counts": numeric_non_null_counts,
        "accepted_charger_ids": set(
            chargers.loc[
                chargers["augmentation_match_status"].eq("accepted"),
                "charger_id",
            ].astype(int)
        ),
        "review_charger_ids": set(
            chargers.loc[
                chargers["augmentation_match_status"].eq("review"),
                "charger_id",
            ].astype(int)
        ),
        "unmatched_charger_ids": set(
            chargers.loc[
                chargers["augmentation_match_status"].eq("unmatched"),
                "charger_id",
            ].astype(int)
        ),
    }
