-- v8: automatic alert-email import. One row per email read from your mailbox, so each email is imported once.
CREATE TABLE IF NOT EXISTS email_inbox (
    message_id   TEXT PRIMARY KEY,                 -- the email's Message-ID (or mailbox:uid when it has none)
    mailbox      TEXT NOT NULL,
    received_at  TEXT,                             -- the email's Date header, ISO UTC
    sender       TEXT NOT NULL DEFAULT '',
    subject      TEXT NOT NULL DEFAULT '',
    listings     INTEGER NOT NULL DEFAULT 0,       -- listing links found in the email
    saved        INTEGER NOT NULL DEFAULT 0,       -- of those, listings imported (they match your searches)
    run_id       INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    imported_at  TEXT NOT NULL
);
