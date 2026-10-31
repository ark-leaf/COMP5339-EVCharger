DROP TABLE IF EXISTS connector_state;
DROP TABLE IF EXISTS charger_state;
DROP TABLE IF EXISTS charger_event;
DROP TYPE IF EXISTS connector_status;
DROP TYPE IF EXISTS charger_event_type;

-- Declared in the publisher's order for events at the same time (EVENT_TYPE_ORDER), so
-- ORDER BY event_ts, event_type replays a charger's events exactly as they were published.
CREATE TYPE charger_event_type AS ENUM ('price_update', 'meter', 'session_end', 'session_start');
CREATE TYPE connector_status AS ENUM ('available', 'occupied');

-- Event log: one row per unique MQTT event, never updated.
CREATE TABLE charger_event (
    -- Every event
    event_id UUID PRIMARY KEY,                  -- MQTT "id"; replays repeat it, so duplicates are skipped
    run_id VARCHAR NOT NULL,                    -- data-generation run
    event_type charger_event_type NOT NULL,
    event_ts TIMESTAMPTZ NOT NULL,              -- for session_end: unplugged
    charger_id INTEGER NOT NULL,                -- MQTT "object_id"
    connector_no SMALLINT,                      -- simulated port 1..n, not charger_connector's key
    session_id VARCHAR,
    -- Payload: one column per field, NULL when the event type has no such field
    price_per_kwh DECIMAL(8, 4),                -- price_update, session_start, session_end (AUD/kWh)
    wholesale_per_kwh DOUBLE,                   -- price_update: NEM hourly average, may be negative
    vehicle_model VARCHAR,                      -- session_start
    power_kw DOUBLE,                            -- meter
    energy_kwh DOUBLE,                          -- meter: cumulative in the session; session_end: total
    voltage_v DOUBLE,                           -- meter
    current_a DOUBLE,                           -- meter
    soc_pct DOUBLE,                             -- meter
    charge_end_ts TIMESTAMPTZ,                  -- session_end: charging stopped
    charge_minutes DOUBLE,                      -- session_end
    cost_aud DECIMAL(10, 2),                    -- session_end
    avg_kw DOUBLE,                              -- session_end
    peak_kw DOUBLE,                             -- session_end
    FOREIGN KEY (charger_id) REFERENCES charger_location(charger_id),
    CHECK (event_type = 'price_update' OR (connector_no > 0 AND session_id IS NOT NULL))
);
CREATE INDEX charger_event_event_type_idx ON charger_event (event_type);
CREATE INDEX charger_event_event_ts_idx ON charger_event (event_ts);
CREATE INDEX charger_event_charger_id_idx ON charger_event (charger_id);
CREATE INDEX charger_event_connector_no_idx ON charger_event (connector_no);

-- Latest state of each charger, rewritten with every event of that charger.
CREATE TABLE charger_state (
    charger_id INTEGER PRIMARY KEY,             -- one row per Assignment 1 charger
    run_id VARCHAR NOT NULL,                    -- run of the latest event
    price_per_kwh DECIMAL(8, 4),                -- current retail price; NULL before the run's first price_update
    wholesale_per_kwh DOUBLE,                   -- NEM price at the last price_update
    price_updated_ts TIMESTAMPTZ,
    active_sessions SMALLINT NOT NULL,          -- connectors occupied now
    last_event_id UUID NOT NULL,                -- latest event of this charger
    last_event_type charger_event_type NOT NULL,
    last_event_ts TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (charger_id) REFERENCES charger_location(charger_id),
    FOREIGN KEY (last_event_id) REFERENCES charger_event(event_id)
);
CREATE INDEX charger_state_price_updated_ts_idx ON charger_state (price_updated_ts);

-- Latest state of each simulated connector, rewritten with every session event on it.
CREATE TABLE connector_state (
    charger_id INTEGER NOT NULL,
    connector_no SMALLINT NOT NULL,             -- simulated port 1..n, not charger_connector's key
    run_id VARCHAR NOT NULL,                    -- run of the latest event
    status connector_status NOT NULL,
    session_id VARCHAR,                         -- current session; NULL when available
    session_start_ts TIMESTAMPTZ,
    session_price_per_kwh DECIMAL(8, 4),        -- tariff fixed when the session started
    vehicle_model VARCHAR,
    power_kw DOUBLE,                            -- latest meter reading of the current session
    energy_kwh DOUBLE,                          -- cumulative in the current session
    soc_pct DOUBLE,
    last_event_id UUID NOT NULL,                -- latest event on this connector
    last_event_type charger_event_type NOT NULL,
    last_event_ts TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (charger_id, connector_no),     -- connector_no repeats across chargers
    FOREIGN KEY (charger_id) REFERENCES charger_location(charger_id),
    FOREIGN KEY (last_event_id) REFERENCES charger_event(event_id),
    CHECK ((status = 'occupied') = (session_id IS NOT NULL))
);
CREATE INDEX connector_state_charger_id_idx ON connector_state (charger_id);
CREATE INDEX connector_state_run_id_idx ON connector_state (run_id);
CREATE INDEX connector_state_session_start_ts_idx ON connector_state (session_start_ts);
CREATE INDEX connector_state_status_idx ON connector_state (status);
