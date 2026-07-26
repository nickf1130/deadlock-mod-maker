from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path

from ..models import (
    SoundAsset,
    SoundCategory,
    VisualResourceAsset,
    VisualResourceKind,
)
from ..paths import AppPaths


class Database:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.connection = sqlite3.connect(paths.database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        migration_root = files("deadlock_sound_studio.database").joinpath("migrations")
        for migration in sorted(
            (entry for entry in migration_root.iterdir() if entry.name.endswith(".sql")),
            key=lambda entry: entry.name,
        ):
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.connection.close()

    def upsert_assets(
        self, assets: Iterable[SoundAsset], *, replace_catalog: bool = False
    ) -> int:
        values = [
            (
                asset.id,
                asset.internal_path,
                asset.compiled_path,
                asset.filename,
                asset.extension,
                asset.category.value,
                asset.hero_id,
                asset.hero_name,
                asset.ability_name,
                asset.sound_event,
                asset.duration_ms,
                asset.sample_rate,
                asset.channels,
                asset.source_archive,
                asset.archive_fingerprint,
                asset.asset_fingerprint,
                asset.last_indexed_at,
            )
            for asset in assets
        ]
        with self.connection:
            if replace_catalog:
                self.connection.execute("DELETE FROM sound_assets")
            self.connection.executemany(
                """
                INSERT INTO sound_assets (
                  id, internal_path, compiled_path, filename, extension, category,
                  hero_id, hero_name, ability_name, sound_event, duration_ms,
                  sample_rate, channels, source_archive, archive_fingerprint,
                  asset_fingerprint, last_indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  internal_path=excluded.internal_path,
                  compiled_path=excluded.compiled_path,
                  filename=excluded.filename,
                  extension=excluded.extension,
                  category=excluded.category,
                  hero_id=excluded.hero_id,
                  hero_name=excluded.hero_name,
                  ability_name=excluded.ability_name,
                  sound_event=excluded.sound_event,
                  duration_ms=COALESCE(excluded.duration_ms, sound_assets.duration_ms),
                  sample_rate=COALESCE(excluded.sample_rate, sound_assets.sample_rate),
                  channels=COALESCE(excluded.channels, sound_assets.channels),
                  source_archive=excluded.source_archive,
                  archive_fingerprint=excluded.archive_fingerprint,
                  asset_fingerprint=COALESCE(excluded.asset_fingerprint, sound_assets.asset_fingerprint),
                  last_indexed_at=excluded.last_indexed_at
                """,
                values,
            )
        return len(values)

    def get_asset(self, asset_id: str) -> SoundAsset | None:
        row = self.connection.execute(
            "SELECT * FROM sound_assets WHERE id=?", (asset_id,)
        ).fetchone()
        return self._asset(row) if row else None

    def get_asset_by_path(self, internal_path: str) -> SoundAsset | None:
        row = self.connection.execute(
            "SELECT * FROM sound_assets WHERE internal_path=? COLLATE NOCASE",
            (internal_path,),
        ).fetchone()
        return self._asset(row) if row else None

    def get_assets_by_filename(self, filename: str, limit: int = 250) -> list[SoundAsset]:
        rows = self.connection.execute(
            """
            SELECT * FROM sound_assets
            WHERE filename=? COLLATE NOCASE
            ORDER BY internal_path
            LIMIT ?
            """,
            (filename, min(max(limit, 1), 1000)),
        ).fetchall()
        return [self._asset(row) for row in rows]

    def search_assets(
        self,
        query: str = "",
        category: str | None = None,
        limit: int = 250,
        *,
        scope: str = "all",
    ) -> list[SoundAsset]:
        wildcard = f"%{query.strip()}%"
        rows = self.connection.execute(
            """
            SELECT * FROM sound_assets
            WHERE (
              ?='' OR filename LIKE ? OR internal_path LIKE ?
              OR COALESCE(hero_name, '') LIKE ?
              OR COALESCE(ability_name, '') LIKE ?
              OR COALESCE(sound_event, '') LIKE ?
            )
            AND (?='' OR category=?)
            AND (
              ?='all'
              OR (?='heroes' AND hero_name IS NOT NULL)
              OR (?='general' AND hero_name IS NULL)
            )
            ORDER BY CASE WHEN filename LIKE ? THEN 0 ELSE 1 END, internal_path
            LIMIT ?
            """,
            (
                query.strip(),
                wildcard,
                wildcard,
                wildcard,
                wildcard,
                wildcard,
                category or "",
                category or "",
                scope,
                scope,
                scope,
                wildcard,
                min(max(limit, 1), 1000),
            ),
        ).fetchall()
        return [self._asset(row) for row in rows]

    def count_assets(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM sound_assets").fetchone()[0])

    def upsert_visual_assets(
        self, assets: Iterable[VisualResourceAsset], *, replace_catalog: bool = False
    ) -> int:
        values = [
            (
                asset.id,
                asset.internal_path,
                asset.compiled_path,
                asset.filename,
                asset.kind.value,
                asset.source_archive,
                asset.archive_fingerprint,
                asset.asset_fingerprint,
                asset.stored_size,
                asset.last_indexed_at,
            )
            for asset in assets
        ]
        with self.connection:
            if replace_catalog:
                self.connection.execute("DELETE FROM visual_assets")
            self.connection.executemany(
                """
                INSERT INTO visual_assets(
                  id, internal_path, compiled_path, filename, kind, source_archive,
                  archive_fingerprint, asset_fingerprint, stored_size, last_indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  internal_path=excluded.internal_path,
                  compiled_path=excluded.compiled_path,
                  filename=excluded.filename,
                  kind=excluded.kind,
                  source_archive=excluded.source_archive,
                  archive_fingerprint=excluded.archive_fingerprint,
                  asset_fingerprint=excluded.asset_fingerprint,
                  stored_size=excluded.stored_size,
                  last_indexed_at=excluded.last_indexed_at
                """,
                values,
            )
        return len(values)

    def search_visual_assets(
        self, query: str = "", kind: str | None = None, limit: int = 250
    ) -> list[VisualResourceAsset]:
        wildcard = f"%{query.strip()}%"
        rows = self.connection.execute(
            """
            SELECT * FROM visual_assets
            WHERE (?='' OR filename LIKE ? OR internal_path LIKE ?)
              AND (?='' OR kind=?)
            ORDER BY CASE WHEN filename LIKE ? THEN 0 ELSE 1 END, internal_path
            LIMIT ?
            """,
            (
                query.strip(),
                wildcard,
                wildcard,
                kind or "",
                kind or "",
                wildcard,
                min(max(limit, 1), 1000),
            ),
        ).fetchall()
        return [self._visual_asset(row) for row in rows]

    def get_visual_asset(self, asset_id: str) -> VisualResourceAsset | None:
        row = self.connection.execute(
            "SELECT * FROM visual_assets WHERE id=?", (asset_id,)
        ).fetchone()
        return self._visual_asset(row) if row else None

    def get_visual_asset_by_path(
        self, internal_path: str
    ) -> VisualResourceAsset | None:
        row = self.connection.execute(
            "SELECT * FROM visual_assets WHERE internal_path=? COLLATE NOCASE",
            (internal_path,),
        ).fetchone()
        return self._visual_asset(row) if row else None

    def count_visual_assets(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM visual_assets").fetchone()[0])

    def record_catalog_snapshot(
        self,
        assets: Iterable[SoundAsset],
        *,
        archive_fingerprint: str,
        indexed_at: str,
    ) -> dict[str, int | str | None]:
        asset_values = list(assets)
        prior = self.connection.execute(
            """
            SELECT archive_fingerprint
            FROM update_history
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        prior_fingerprint = str(prior[0]) if prior else None
        prior_rows = {
            str(row["id"]): str(row["asset_fingerprint"] or "")
            for row in self.connection.execute(
                "SELECT id, asset_fingerprint FROM sound_assets"
            ).fetchall()
        }
        current_rows = {
            asset.id: asset.asset_fingerprint or "" for asset in asset_values
        }
        added = len(current_rows.keys() - prior_rows.keys())
        removed = len(prior_rows.keys() - current_rows.keys())
        changed = sum(
            prior_rows[asset_id] != current_rows[asset_id]
            for asset_id in current_rows.keys() & prior_rows.keys()
        )
        unchanged = len(current_rows.keys() & prior_rows.keys()) - changed

        with self.connection:
            if prior_fingerprint != archive_fingerprint:
                self.connection.execute(
                    """
                    INSERT INTO update_history(
                      archive_fingerprint, indexed_at, asset_count, prior_fingerprint
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        archive_fingerprint,
                        indexed_at,
                        len(asset_values),
                        prior_fingerprint,
                    ),
                )
            self.connection.executemany(
                """
                INSERT INTO catalog_asset_history(
                  archive_fingerprint, asset_id, internal_path, asset_fingerprint,
                  indexed_at, asset_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(archive_fingerprint, asset_id) DO UPDATE SET
                  internal_path=excluded.internal_path,
                  asset_fingerprint=excluded.asset_fingerprint,
                  indexed_at=excluded.indexed_at,
                  asset_json=excluded.asset_json
                """,
                (
                    (
                        archive_fingerprint,
                        asset.id,
                        asset.internal_path,
                        asset.asset_fingerprint,
                        indexed_at,
                        json.dumps(asset.model_dump(by_alias=True)),
                    )
                    for asset in asset_values
                ),
            )
        return {
            "archiveFingerprint": archive_fingerprint,
            "priorFingerprint": prior_fingerprint,
            "added": added,
            "changed": changed,
            "removed": removed,
            "unchanged": unchanged,
        }

    def index_history(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT archive_fingerprint, indexed_at, asset_count, prior_fingerprint
            FROM update_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (min(max(limit, 1), 100),),
        ).fetchall()
        return [
            {
                "archiveFingerprint": row["archive_fingerprint"],
                "indexedAt": row["indexed_at"],
                "assetCount": row["asset_count"],
                "priorFingerprint": row["prior_fingerprint"],
            }
            for row in rows
        ]

    def register_project(
        self,
        project_id: str,
        name: str,
        display_name: str,
        manifest_path: Path,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO projects(id, name, display_name, manifest_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, display_name=excluded.display_name,
              manifest_path=excluded.manifest_path, updated_at=excluded.updated_at
            """,
            (project_id, name, display_name, str(manifest_path), created_at, updated_at),
        )
        self.connection.commit()

    def delete_project(self, project_id: str) -> None:
        self.connection.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self.connection.commit()

    def project_rows(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()

    @staticmethod
    def _asset(row: sqlite3.Row) -> SoundAsset:
        return SoundAsset(
            id=row["id"],
            internal_path=row["internal_path"],
            compiled_path=row["compiled_path"],
            filename=row["filename"],
            extension=row["extension"],
            category=SoundCategory(row["category"]),
            hero_id=row["hero_id"],
            hero_name=row["hero_name"],
            ability_name=row["ability_name"],
            sound_event=row["sound_event"],
            duration_ms=row["duration_ms"],
            sample_rate=row["sample_rate"],
            channels=row["channels"],
            source_archive=row["source_archive"],
            archive_fingerprint=row["archive_fingerprint"],
            asset_fingerprint=row["asset_fingerprint"],
            last_indexed_at=row["last_indexed_at"],
        )

    @staticmethod
    def _visual_asset(row: sqlite3.Row) -> VisualResourceAsset:
        return VisualResourceAsset(
            id=row["id"],
            internal_path=row["internal_path"],
            compiled_path=row["compiled_path"],
            filename=row["filename"],
            kind=VisualResourceKind(row["kind"]),
            source_archive=row["source_archive"],
            archive_fingerprint=row["archive_fingerprint"],
            asset_fingerprint=row["asset_fingerprint"],
            stored_size=row["stored_size"],
            last_indexed_at=row["last_indexed_at"],
        )
