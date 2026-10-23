-- v5: pre-purchase checklist, seller contact log, and data for the relist/flip detector.
ALTER TABLE listings ADD COLUMN days_on_market_here INTEGER;   -- MarketCheck dom_active: days at the current seller

CREATE TABLE IF NOT EXISTS checklist (
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    item        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'todo',   -- todo | ok | problem | na
    note        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (vehicle_id, item)
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    at          TEXT NOT NULL,
    channel     TEXT NOT NULL,                  -- call | text | email | visit | other
    person      TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    follow_up   TEXT                            -- YYYY-MM-DD
);
CREATE INDEX IF NOT EXISTS ix_contacts_vehicle ON contacts(vehicle_id, at);

UPDATE listings SET days_on_market_here = json_extract(raw_json, '$.dom_active')
 WHERE source_key = 'marketcheck' AND raw_json IS NOT NULL AND json_valid(raw_json);
