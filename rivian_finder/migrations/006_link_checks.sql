-- Results of the "Check listing links" tool: does each listing URL still lead to the truck's page?
CREATE TABLE IF NOT EXISTS link_checks (
    url TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL,
    result TEXT NOT NULL,          -- ok | gone | moved | maybe_gone | blocked | not_allowed | not_checkable | error
    http_status INTEGER,
    final_url TEXT,
    note TEXT
);
