CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL,
  quantity REAL NOT NULL CHECK (quantity > 0 AND quantity <= 1),
  state TEXT NOT NULL CHECK (state IN ('PREPARED','APPROVED','SUBMITTING','SUBMITTED','UNKNOWN','UPSTREAM_REJECTED')),
  prepared_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  approved_at TEXT,
  submitted_at TEXT,
  order_id TEXT,
  error_code TEXT
);
CREATE INDEX IF NOT EXISTS proposals_state_expiry ON proposals(state, expires_at);
