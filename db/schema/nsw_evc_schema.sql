-- USYD CODE CITATION ACKNOWLEDGEMENT
-- I declare that OpenAI Codex restored SA4 region storage/linkage and added
-- preservation of the remaining augmentation fields to the team's schema.

INSTALL spatial;
LOAD spatial;

DROP TABLE IF EXISTS charger;
DROP TABLE IF EXISTS charger_connector;
DROP TABLE IF EXISTS charger_characteristic;
DROP TABLE IF EXISTS charger_location;
DROP TABLE IF EXISTS sa4_region;
DROP TABLE IF EXISTS operator;

CREATE TABLE operator (
    operator_id INTEGER PRIMARY KEY,
    operator_name VARCHAR,
    operator_name_normalised VARCHAR
);

CREATE TABLE sa4_region (
    sa4_code VARCHAR PRIMARY KEY,
    sa4_name VARCHAR NOT NULL,
    geom GEOMETRY NOT NULL
);

CREATE TABLE charger_location (
    charger_id INTEGER PRIMARY KEY,
    source_objectid BIGINT,
    station_name VARCHAR,
    station_address VARCHAR,
    operator_id INTEGER NOT NULL,
    latitude DOUBLE,
    longitude DOUBLE,
    postcode VARCHAR,
    lga_name VARCHAR,
    source_category VARCHAR,
    geom GEOMETRY,
    sa4_code VARCHAR,
    FOREIGN KEY (operator_id) REFERENCES operator(operator_id),
    FOREIGN KEY (sa4_code) REFERENCES sa4_region(sa4_code)
);

CREATE TABLE charger_characteristic (
    charger_id INTEGER PRIMARY KEY,
    charger_type VARCHAR,
    number_of_plugs INTEGER,
    rating_raw VARCHAR,
    rating_kw DOUBLE,
    FOREIGN KEY (charger_id) REFERENCES charger_location(charger_id)
);

CREATE TABLE charger_connector (
    charger_connector_id INTEGER PRIMARY KEY,
    charger_id INTEGER NOT NULL,
    connector_type VARCHAR NOT NULL,
    FOREIGN KEY (charger_id) REFERENCES charger_location(charger_id),
    UNIQUE (charger_id, connector_type)
);

CREATE TABLE charger (
    augmentation_id INTEGER PRIMARY KEY,
    charger_id INTEGER NOT NULL,
    external_source VARCHAR,
    external_station_id VARCHAR,
    external_operator VARCHAR,
    external_number_of_plugs INTEGER,
    external_power_kw_min DOUBLE,
    external_power_kw_max DOUBLE,
    external_usage_cost VARCHAR,
    augmentation_match_method VARCHAR,
    augmentation_match_confidence DOUBLE,
    augmentation_quality_review_reason VARCHAR,
    external_opening_hours VARCHAR,
    external_network VARCHAR,
    external_access_condition VARCHAR,
    external_is_free BOOLEAN,
    augmentation_quality_review BOOLEAN,
    external_attributes_json JSON,
    FOREIGN KEY (charger_id) REFERENCES charger_location(charger_id)
);
