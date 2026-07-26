CREATE TABLE IF NOT EXISTS catalog_asset_history (
  archive_fingerprint TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  internal_path TEXT NOT NULL,
  asset_fingerprint TEXT,
  indexed_at TEXT NOT NULL,
  asset_json TEXT NOT NULL,
  PRIMARY KEY (archive_fingerprint, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_asset_history_path
ON catalog_asset_history(internal_path COLLATE NOCASE, indexed_at);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
