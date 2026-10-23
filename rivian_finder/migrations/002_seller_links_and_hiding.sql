-- v2: "not interested" hiding, and the selling dealer's website when a provider reports it.
ALTER TABLE vehicles ADD COLUMN hidden_at TEXT;          -- NULL = visible
ALTER TABLE vehicles ADD COLUMN hidden_reason TEXT;      -- key from HIDE_REASONS
ALTER TABLE vehicles ADD COLUMN hidden_note TEXT;
ALTER TABLE listings ADD COLUMN dealer_website TEXT;     -- e.g. MarketCheck dealer.website
