-- v3: vehicle-history links, listing age (days on market), seller phone, and NHTSA recalls.
ALTER TABLE listings ADD COLUMN history_report_url TEXT;   -- dealer-provided Carfax link (free report)
ALTER TABLE listings ADD COLUMN listed_at TEXT;            -- earliest date a provider reports the listing appeared
ALTER TABLE listings ADD COLUMN days_on_market INTEGER;    -- provider-reported days on market (MarketCheck "dom")
ALTER TABLE listings ADD COLUMN seller_phone TEXT;

CREATE TABLE IF NOT EXISTS recalls (
    campaign     TEXT NOT NULL,       -- NHTSA campaign number, e.g. 24V408000
    model        TEXT NOT NULL,
    model_year   INTEGER NOT NULL,
    report_date  TEXT,
    component    TEXT,
    summary      TEXT,
    consequence  TEXT,
    remedy       TEXT,
    ota          INTEGER,             -- fixed by over-the-air update
    park_it      INTEGER,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (campaign, model, model_year)
);

-- Backfill from provider payloads already stored.
UPDATE listings SET history_report_url = json_extract(raw_json, '$.retailListing.carfaxUrl')
 WHERE source_key = 'autodev' AND raw_json IS NOT NULL AND json_valid(raw_json);
UPDATE listings SET listed_at = replace(substr(json_extract(raw_json, '$.createdAt'), 1, 19), ' ', 'T') || 'Z'
 WHERE source_key = 'autodev' AND raw_json IS NOT NULL AND json_valid(raw_json)
   AND json_extract(raw_json, '$.createdAt') IS NOT NULL;
UPDATE listings SET listed_at = substr(json_extract(raw_json, '$.first_seen_at_date'), 1, 19) || 'Z',
                    days_on_market = json_extract(raw_json, '$.dom')
 WHERE source_key = 'marketcheck' AND raw_json IS NOT NULL AND json_valid(raw_json)
   AND json_extract(raw_json, '$.first_seen_at_date') IS NOT NULL;
