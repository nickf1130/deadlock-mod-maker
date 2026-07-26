CREATE TABLE IF NOT EXISTS visual_assets (
  id TEXT PRIMARY KEY,
  internal_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
  compiled_path TEXT NOT NULL,
  filename TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('texture', 'material')),
  source_archive TEXT NOT NULL,
  archive_fingerprint TEXT NOT NULL,
  asset_fingerprint TEXT,
  stored_size INTEGER NOT NULL DEFAULT 0,
  last_indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visual_assets_filename
  ON visual_assets(filename COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_visual_assets_kind_path
  ON visual_assets(kind, internal_path COLLATE NOCASE);
