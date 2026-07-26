PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sound_assets (
  id TEXT PRIMARY KEY,
  internal_path TEXT NOT NULL,
  compiled_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  extension TEXT NOT NULL,
  category TEXT NOT NULL,
  hero_id TEXT,
  hero_name TEXT,
  ability_name TEXT,
  sound_event TEXT,
  duration_ms INTEGER,
  sample_rate INTEGER,
  channels INTEGER,
  source_archive TEXT NOT NULL,
  archive_fingerprint TEXT NOT NULL,
  asset_fingerprint TEXT,
  last_indexed_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sound_assets_path
ON sound_assets(internal_path COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_sound_assets_search
ON sound_assets(filename, category, hero_name, ability_name, sound_event);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  manifest_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT,
  executable_path TEXT NOT NULL,
  executable_version TEXT,
  arguments_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  duration_ms INTEGER NOT NULL,
  exit_code INTEGER,
  stdout TEXT NOT NULL,
  stderr TEXT NOT NULL,
  produced_files_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS update_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  archive_fingerprint TEXT NOT NULL,
  indexed_at TEXT NOT NULL,
  asset_count INTEGER NOT NULL,
  prior_fingerprint TEXT
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
