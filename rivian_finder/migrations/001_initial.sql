-- Rivian Finder schema v1
-- All timestamps are ISO-8601 UTC strings (e.g. 2026-10-20T12:00:00Z).

CREATE TABLE IF NOT EXISTS sources (
    key              TEXT PRIMARY KEY,          -- 'autodev', 'marketcheck', 'demo', 'autotrader', ...
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL,             -- api | email | assisted | manual | demo | site
    enabled          INTEGER NOT NULL DEFAULT 1,
    config_json      TEXT NOT NULL DEFAULT '{}',
    last_attempt_at  TEXT,
    last_success_at  TEXT,
    last_status      TEXT,                      -- success | partial | failed | skipped
    last_error       TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    trigger            TEXT NOT NULL,           -- run_search | manual_entry | csv_import | email_import | capture | maintenance
    status             TEXT NOT NULL DEFAULT 'running',  -- running | success | partial | failed
    sources_requested  TEXT NOT NULL DEFAULT '[]',
    summary_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_key     TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT NOT NULL DEFAULT 'running',  -- running | success | partial | failed | skipped
    complete       INTEGER NOT NULL DEFAULT 0,       -- 1 only when every page of the scope was retrieved
    scope_hash     TEXT,                             -- hash of the collection query; disappearance detection compares like with like
    listings_seen  INTEGER NOT NULL DEFAULT 0,
    api_calls      INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    notes          TEXT
);
CREATE INDEX IF NOT EXISTS ix_source_runs_source ON source_runs(source_key, id);

CREATE TABLE IF NOT EXISTS vehicles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    vin              TEXT UNIQUE,               -- validated 17-char VIN, NULL for provisional (VIN-less) vehicles
    vin_raw          TEXT,                      -- unvalidated VIN text as seen (e.g. failed checksum)
    year             INTEGER,
    make             TEXT,
    model            TEXT,
    trim             TEXT,
    notes            TEXT NOT NULL DEFAULT '',
    is_demo          INTEGER NOT NULL DEFAULT 0,
    merged_into_id   INTEGER REFERENCES vehicles(id),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id         INTEGER NOT NULL REFERENCES vehicles(id),
    source_key         TEXT NOT NULL,           -- where the listing lives / came from (autodev, autotrader, rivian, dealer...)
    import_method      TEXT NOT NULL,           -- api | email | capture | manual | csv | demo
    source_listing_id  TEXT,
    url                TEXT,
    url_canonical      TEXT,
    title              TEXT,
    description        TEXT,
    seller_name        TEXT,
    seller_type        TEXT,                    -- dealer | private | manufacturer | retailer | unknown
    city               TEXT,
    state              TEXT,
    zip                TEXT,
    lat                REAL,
    lon                REAL,
    exterior_color     TEXT,
    interior_color     TEXT,
    current_price      INTEGER,
    current_miles      INTEGER,
    status             TEXT NOT NULL DEFAULT 'active',  -- active | missing | removed
    status_reason      TEXT,
    missing_since      TEXT,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    last_run_id        INTEGER,
    content_hash       TEXT,
    transport_cost     INTEGER,                 -- user-entered estimate
    is_demo            INTEGER NOT NULL DEFAULT 0,
    raw_json           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_listings_source_id ON listings(source_key, source_listing_id) WHERE source_listing_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_listings_vehicle ON listings(vehicle_id);
CREATE INDEX IF NOT EXISTS ix_listings_url ON listings(url_canonical);

CREATE TABLE IF NOT EXISTS observations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id     INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    run_id         INTEGER REFERENCES runs(id),
    observed_at    TEXT NOT NULL,
    import_method  TEXT NOT NULL,
    price          INTEGER,
    miles          INTEGER,
    available      INTEGER NOT NULL DEFAULT 1,
    seller_name    TEXT,
    content_hash   TEXT
);
CREATE INDEX IF NOT EXISTS ix_observations_listing ON observations(listing_id, observed_at);

CREATE TABLE IF NOT EXISTS change_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES runs(id),
    listing_id  INTEGER REFERENCES listings(id) ON DELETE CASCADE,
    vehicle_id  INTEGER REFERENCES vehicles(id),
    event_type  TEXT NOT NULL,   -- new_listing | new_source_for_vin | price_drop | price_increase | mileage_update
                                 -- seller_change | disappeared | returned | equipment_change | marked_removed
    old_value   TEXT,
    new_value   TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_run ON change_events(run_id);
CREATE INDEX IF NOT EXISTS ix_events_vehicle ON change_events(vehicle_id);

-- Every claim about a vehicle attribute, with where it came from and how much to trust it.
CREATE TABLE IF NOT EXISTS vehicle_attributes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id   INTEGER NOT NULL REFERENCES vehicles(id),
    listing_id   INTEGER REFERENCES listings(id) ON DELETE SET NULL,
    field        TEXT NOT NULL,   -- battery | motor | generation | tonneau | epa_range | wheels | in_service_date
                                  -- warranty_expiration | title_status | accident_history | trim | exterior_color ...
    value        TEXT NOT NULL,
    source       TEXT NOT NULL,   -- autodev | nhtsa_vpic | vin_rule | listing_text | ...
    method       TEXT NOT NULL,   -- human-readable: how the value was obtained
    confidence   TEXT NOT NULL,   -- high | medium | low
    evidence     TEXT,
    observed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attrs_vehicle ON vehicle_attributes(vehicle_id, field);

-- Manually verified values always win over any source claim.
CREATE TABLE IF NOT EXISTS user_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    field       TEXT NOT NULL,
    value       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(vehicle_id, field)
);

CREATE TABLE IF NOT EXISTS match_candidates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id            INTEGER NOT NULL REFERENCES vehicles(id),   -- the provisional (new) vehicle
    candidate_vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),   -- existing vehicle it may duplicate
    score                 REAL NOT NULL,
    reasons               TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'pending',            -- pending | merged | rejected
    created_at            TEXT NOT NULL,
    resolved_at           TEXT,
    UNIQUE(vehicle_id, candidate_vehicle_id)
);

CREATE TABLE IF NOT EXISTS merges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kept_vehicle_id  INTEGER NOT NULL,
    merged_vehicle_id INTEGER NOT NULL,
    reason           TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    source_key  TEXT NOT NULL,
    url         TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    is_template INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    vehicle_id  INTEGER PRIMARY KEY REFERENCES vehicles(id),
    added_at    TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS capture_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at  TEXT NOT NULL,
    origin       TEXT NOT NULL,     -- extension | paste
    url          TEXT,
    title        TEXT,
    text         TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | saved | discarded
    listing_id   INTEGER
);

CREATE TABLE IF NOT EXISTS api_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key  TEXT NOT NULL,
    called_at   TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    status_code INTEGER
);
CREATE INDEX IF NOT EXISTS ix_api_usage ON api_usage(source_key, called_at);
