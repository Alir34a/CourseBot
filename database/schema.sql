-- Reusable telegram-bot core schema (SQLite, normalized).
-- All timestamps: UTC ISO8601 TEXT. Money: INTEGER minor units or NULL.
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER NOT NULL UNIQUE,
  username TEXT,
  full_name TEXT,
  phone TEXT,
  status TEXT NOT NULL DEFAULT 'new',           -- new|phone_submitted|in_course|finished|customer
  created_at TEXT NOT NULL,
  phone_registered_at TEXT,
  last_activity_at TEXT,
  last_episode_id INTEGER,
  last_part_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity_at);

CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,                    -- e.g. 'sample-course'
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  episode_no INTEGER NOT NULL,                  -- 1..N human number
  title TEXT NOT NULL,
  caption TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(course_id, episode_no)
);
CREATE INDEX IF NOT EXISTS idx_episodes_course ON episodes(course_id, sort_order);

CREATE TABLE IF NOT EXISTS episode_parts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  part_no INTEGER NOT NULL,                     -- 1..M within episode
  kind TEXT NOT NULL DEFAULT 'text',            -- text|video|photo|audio|file
  file_id TEXT,                                 -- telegram file_id after upload, or URL
  text TEXT DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(episode_id, part_no)
);
CREATE INDEX IF NOT EXISTS idx_parts_episode ON episode_parts(episode_id, sort_order);

-- History-capable progress (never just current_episode=7):
CREATE TABLE IF NOT EXISTS user_episode_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(user_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_uep_user ON user_episode_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_uep_episode ON user_episode_progress(episode_id);

CREATE TABLE IF NOT EXISTS user_part_progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  part_id INTEGER NOT NULL REFERENCES episode_parts(id) ON DELETE CASCADE,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(user_id, part_id)
);
CREATE INDEX IF NOT EXISTS idx_upp_user ON user_part_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_upp_part ON user_part_progress(part_id);

-- Generic event tracking (append-only, analytics source of truth):
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  type TEXT NOT NULL,                           -- user_registered|phone_submitted|episode_started|...
  payload TEXT DEFAULT '{}',                    -- JSON
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(type, created_at);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  media_kind TEXT,                              -- photo|video|none
  media_ref TEXT,
  url TEXT NOT NULL,
  button_text TEXT NOT NULL DEFAULT 'خرید',
  trigger_rule TEXT DEFAULT 'episode:15',       -- generic rule string parsed by offers module
  is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS offer_interactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                           -- viewed|clicked|started|completed
  created_at TEXT NOT NULL,
  meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_offer_user ON offer_interactions(user_id, offer_id);

CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  offer_id INTEGER REFERENCES offers(id) ON DELETE SET NULL,
  amount INTEGER,                               -- minor units, NULL if unknown
  status TEXT NOT NULL DEFAULT 'completed',     -- started|completed|refunded
  external_ref TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id);

CREATE TABLE IF NOT EXISTS admin_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL DEFAULT 'single',         -- single|filtered|broadcast
  filter_json TEXT DEFAULT '{}',
  target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',       -- pending|sent|failed
  created_at TEXT NOT NULL,
  sent_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- ---- Hardening indexes (added in finalization; idempotent) ----
-- Analytics/event volume: filter by user and by type+time.
CREATE INDEX IF NOT EXISTS idx_events_user_type ON events(user_id, type);
-- Offer funnel: per-offer kind counts.
CREATE INDEX IF NOT EXISTS idx_offer_interactions_offer_kind ON offer_interactions(offer_id, kind);
-- Outbox dispatcher: pending-first scan.
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_messages(status, id);
-- Admin search-by-phone and purchase stats.
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
CREATE INDEX IF NOT EXISTS idx_purchases_offer ON purchases(offer_id);
CREATE INDEX IF NOT EXISTS idx_purchases_created ON purchases(created_at);
-- Inactive-user reminders: last-activity scan.
CREATE INDEX IF NOT EXISTS idx_users_status_activity ON users(status, last_activity_at);
-- Progress history per user+episode.
CREATE INDEX IF NOT EXISTS idx_uep_user_completed ON user_episode_progress(user_id, completed_at);
CREATE INDEX IF NOT EXISTS idx_upp_user_completed ON user_part_progress(user_id, completed_at);
