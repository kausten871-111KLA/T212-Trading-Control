-- Trading Operations State DB — SQLite, WAL mode.
-- Author: DeepSeek Trading Operations (controller). Deploy first.
-- Broker is AUTHORITATIVE; this DB is a mirror + journal + decision store.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS strategy_version (
  id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  description TEXT, parameters TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'draft',
  effective_from INTEGER, effective_to INTEGER, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_status ON strategy_version(status, effective_from);
CREATE TABLE IF NOT EXISTS candidate (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, t212_ticker TEXT, name TEXT,
  discovered_at INTEGER NOT NULL, source TEXT, discovery_batch TEXT, UNIQUE(symbol, discovered_at)
);
CREATE INDEX IF NOT EXISTS idx_candidate_symbol ON candidate(symbol);
CREATE INDEX IF NOT EXISTS idx_candidate_batch ON candidate(discovery_batch);
CREATE TABLE IF NOT EXISTS candidate_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
  evidence_type TEXT NOT NULL, content TEXT, source_url TEXT, confidence TEXT, observed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_candidate ON candidate_evidence(candidate_id);
CREATE TABLE IF NOT EXISTS decision (
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL REFERENCES candidate(id),
  strategy_version_id INTEGER REFERENCES strategy_version(id), decision TEXT NOT NULL, track TEXT,
  p_green REAL, s_trade REAL, rationale TEXT, entry_condition TEXT, invalidation TEXT,
  proposed_size REAL, proposed_stop REAL, decided_by TEXT NOT NULL DEFAULT 'controller', decided_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_candidate ON decision(candidate_id);
CREATE INDEX IF NOT EXISTS idx_decision_time ON decision(decided_at);
CREATE TABLE IF NOT EXISTS intent (
  id TEXT PRIMARY KEY, decision_id INTEGER REFERENCES decision(id), ticker TEXT NOT NULL,
  side TEXT NOT NULL, quantity REAL NOT NULL, order_type TEXT NOT NULL, limit_price REAL,
  stop_price REAL, time_validity TEXT DEFAULT 'DAY', status TEXT NOT NULL DEFAULT 'CREATED', created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intent_decision ON intent(decision_id);
CREATE INDEX IF NOT EXISTS idx_intent_status ON intent(status);
CREATE TABLE IF NOT EXISTS "order" (
  broker_order_id INTEGER PRIMARY KEY, intent_id TEXT REFERENCES intent(id), ticker TEXT NOT NULL,
  side TEXT NOT NULL, quantity REAL NOT NULL, filled_quantity REAL NOT NULL DEFAULT 0,
  order_type TEXT NOT NULL, limit_price REAL, stop_price REAL, status TEXT NOT NULL,
  avg_fill_price REAL, created_at INTEGER NOT NULL, filled_at INTEGER, broker_receipt TEXT,
  readback_state TEXT, last_reconciled INTEGER
);
CREATE INDEX IF NOT EXISTS idx_order_intent ON "order"(intent_id);
CREATE INDEX IF NOT EXISTS idx_order_status ON "order"(status);
CREATE INDEX IF NOT EXISTS idx_order_ticker ON "order"(ticker);
CREATE TABLE IF NOT EXISTS position (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, quantity REAL NOT NULL,
  avg_entry REAL, opened_at INTEGER NOT NULL, closed_at INTEGER,
  decision_id INTEGER REFERENCES decision(id), strategy_version_id INTEGER REFERENCES strategy_version(id),
  status TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE INDEX IF NOT EXISTS idx_position_status ON position(status);
CREATE TABLE IF NOT EXISTS market_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, observed_at INTEGER NOT NULL,
  source TEXT NOT NULL, feed TEXT, price REAL, bid REAL, ask REAL, spread_pct REAL,
  day_volume REAL, minute_volume REAL, rvol REAL, change_pct REAL, day_high REAL,
  day_low REAL, prev_close REAL, flags TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_symbol_time ON market_observation(symbol, observed_at);
CREATE TABLE IF NOT EXISTS event_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 50, status TEXT NOT NULL DEFAULT 'pending', correlation_id TEXT,
  created_at INTEGER NOT NULL, claimed_at INTEGER, worker_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5, next_retry_at INTEGER, lease_expires_at INTEGER, last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_queue_status_prio ON event_queue(status, priority, next_retry_at);
CREATE TABLE IF NOT EXISTS worker (
  id TEXT PRIMARY KEY, role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idle',
  last_heartbeat INTEGER, lease_expires_at INTEGER
);
CREATE TABLE IF NOT EXISTS monitor_instruction (
  id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER NOT NULL REFERENCES position(id),
  instruction_type TEXT NOT NULL, trigger_condition TEXT, params TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active', created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_monitor_position ON monitor_instruction(position_id, status);
CREATE TABLE IF NOT EXISTS monitor_trigger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_instruction_id INTEGER NOT NULL REFERENCES monitor_instruction(id),
  triggered_at INTEGER NOT NULL, trigger_reason TEXT, payload TEXT, status TEXT NOT NULL DEFAULT 'fired'
);
CREATE INDEX IF NOT EXISTS idx_trigger_inst ON monitor_trigger(monitor_instruction_id);
CREATE TABLE IF NOT EXISTS pnl_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT, position_id INTEGER REFERENCES position(id), order_id INTEGER,
  realized_pnl REAL NOT NULL DEFAULT 0, unrealized_pnl REAL NOT NULL DEFAULT 0,
  equity REAL, cash REAL, recorded_at INTEGER NOT NULL, source TEXT
);
CREATE INDEX IF NOT EXISTS idx_pnl_position ON pnl_record(position_id);
CREATE INDEX IF NOT EXISTS idx_pnl_time ON pnl_record(recorded_at);
CREATE TABLE IF NOT EXISTS portfolio_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at INTEGER NOT NULL, equity REAL, cash REAL,
  invested REAL, realized_pnl REAL, unrealized_pnl REAL, drawdown REAL, capture_rate REAL,
  win_count INTEGER, loss_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshot_time ON portfolio_snapshot(recorded_at);
CREATE TABLE IF NOT EXISTS error_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER REFERENCES event_queue(id),
  agent TEXT, error_type TEXT NOT NULL, message TEXT, context TEXT,
  created_at INTEGER NOT NULL, resolved INTEGER NOT NULL DEFAULT 0, resolution TEXT
);
CREATE INDEX IF NOT EXISTS idx_error_type ON error_log(error_type);
CREATE INDEX IF NOT EXISTS idx_error_resolved ON error_log(resolved);
CREATE TABLE IF NOT EXISTS recovery_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER, order_id INTEGER, intent_id TEXT,
  recovery_type TEXT, state TEXT, detail TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS trade_review (
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER REFERENCES decision(id),
  position_id INTEGER REFERENCES position(id), outcome TEXT, realized_pnl REAL,
  mfe REAL, mae REAL, missed_green INTEGER DEFAULT 0, root_cause_label TEXT,
  learning TEXT, reviewed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_decision ON trade_review(decision_id);
CREATE TABLE IF NOT EXISTS strategy_improvement (
  id INTEGER PRIMARY KEY AUTOINCREMENT, trade_review_id INTEGER REFERENCES trade_review(id),
  rule_change TEXT NOT NULL, applies_to TEXT, version_bump TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS controller_instruction (
  id INTEGER PRIMARY KEY AUTOINCREMENT, instruction_type TEXT NOT NULL, payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'issued', issued_at INTEGER NOT NULL, acknowledged_at INTEGER,
  issued_by TEXT NOT NULL DEFAULT 'controller'
);
CREATE INDEX IF NOT EXISTS idx_ctl_inst_status ON controller_instruction(status, issued_at);
CREATE TABLE IF NOT EXISTS controller_result (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  controller_instruction_id INTEGER REFERENCES controller_instruction(id), event_id INTEGER,
  kind TEXT NOT NULL, payload TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ctl_result_inst ON controller_result(controller_instruction_id);
