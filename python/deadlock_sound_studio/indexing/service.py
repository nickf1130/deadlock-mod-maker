from __future__ import annotations

import hashlib
import time
from pathlib import Path, PurePosixPath

from ..database import Database
from ..models import (
    IndexResult,
    SoundAsset,
    SoundCategory,
    VisualResourceAsset,
    VisualResourceKind,
    utc_now,
)
from ..paths import normalize_internal_path
from ..vpk import list_vpk
from .enrichment import (
    association_for,
    hero_display_name,
    read_catalog_metadata,
)


def quick_fingerprint(path: Path) -> str:
    hasher = hashlib.sha256()
    size = path.stat().st_size
    hasher.update(size.to_bytes(8, "little"))
    with path.open("rb") as stream:
        hasher.update(stream.read(1024 * 1024))
        if size > 1024 * 1024:
            stream.seek(max(0, size - 1024 * 1024))
            hasher.update(stream.read(1024 * 1024))
    return hasher.hexdigest()


def classify_sound(path: str) -> tuple[SoundCategory, str | None, str | None]:
    lower = path.lower()
    parts = PurePosixPath(lower).parts
    hero: str | None = None
    ability: str | None = None
    for marker in ("heroes", "hero"):
        if marker in parts and parts.index(marker) + 1 < len(parts):
            hero = parts[parts.index(marker) + 1]
            break
    if hero is None and "vo" in parts and parts.index("vo") + 1 < len(parts):
        candidate = parts[parts.index("vo") + 1]
        if candidate not in {"announcer", "npc", "general"}:
            hero = candidate
    if "abilities" in parts and parts.index("abilities") + 1 < len(parts):
        ability_index = parts.index("abilities")
        if hero is None:
            hero = parts[ability_index + 1]
        if ability_index + 2 < len(parts):
            ability = parts[ability_index + 2]
    rules: list[tuple[SoundCategory, tuple[str, ...]]] = [
        (SoundCategory.VOICE, ("/vo/", "/voice/", "vo_", "response")),
        (SoundCategory.ABILITY, ("/abilities/", "/ability/", "ability_")),
        (SoundCategory.WEAPON, ("/weapons/", "/weapon/", "weapon_")),
        (SoundCategory.UI, ("/ui/", "/panorama/", "ui_")),
        (SoundCategory.MUSIC, ("/music/", "music_")),
        (SoundCategory.AMBIENT, ("/ambient/", "/ambience/", "ambient_")),
        (SoundCategory.ANNOUNCER, ("/announcer/", "announcer_")),
        (SoundCategory.OBJECTIVE, ("/objectives/", "/objective/", "objective_")),
        (SoundCategory.ITEM, ("/items/", "/item/", "item_")),
    ]
    padded = f"/{lower}"
    for category, needles in rules:
        if any(needle in padded for needle in needles):
            return category, hero, ability
    if hero:
        return SoundCategory.HERO, hero, ability
    if lower.startswith(("sounds/", "sound/")):
        return SoundCategory.GENERAL, None, ability
    return SoundCategory.UNCLASSIFIED, hero, ability


def index_archive(database: Database, archive: Path) -> IndexResult:
    """Index sound and visual resources from one Deadlock VPK catalog."""
    started = time.monotonic()
    fingerprint = quick_fingerprint(archive)
    timestamp = utc_now()
    assets: list[SoundAsset] = []
    visual_assets: list[VisualResourceAsset] = []
    entries = list_vpk(archive)
    metadata = read_catalog_metadata(archive, entries)
    for entry in entries:
        internal = normalize_internal_path(entry.path)
        visual_kind = (
            VisualResourceKind.TEXTURE
            if internal.lower().endswith(".vtex_c")
            else VisualResourceKind.MATERIAL
            if internal.lower().endswith(".vmat_c")
            else None
        )
        if visual_kind:
            visual_assets.append(
                VisualResourceAsset(
                    id=hashlib.sha256(
                        internal.lower().encode("utf-8")
                    ).hexdigest(),
                    internal_path=internal,
                    compiled_path=internal,
                    filename=PurePosixPath(internal).name,
                    kind=visual_kind,
                    source_archive=str(archive),
                    archive_fingerprint=fingerprint,
                    asset_fingerprint=f"{entry.crc32:08x}",
                    stored_size=entry.length + entry.preload_bytes,
                    last_indexed_at=timestamp,
                )
            )
        if not internal.lower().endswith(".vsnd_c"):
            continue
        category, hero, ability = classify_sound(internal)
        association = association_for(metadata, internal)
        hero = association.hero_id or hero
        ability_label = association.ability_name or (
            ability.replace("_", " ").title() if ability else None
        )
        filename = PurePosixPath(internal).name
        asset_id = hashlib.sha256(
            internal.lower().encode("utf-8")
        ).hexdigest()
        assets.append(
            SoundAsset(
                id=asset_id,
                internal_path=internal,
                compiled_path=internal,
                filename=filename,
                extension=".vsnd_c",
                category=category,
                hero_id=hero,
                hero_name=(
                    association.hero_name
                    or hero_display_name(metadata, hero)
                    or (hero.replace("_", " ").title() if hero else None)
                ),
                ability_name=ability_label,
                sound_event=association.sound_event,
                source_archive=str(archive),
                archive_fingerprint=fingerprint,
                asset_fingerprint=f"{entry.crc32:08x}",
                last_indexed_at=timestamp,
            )
        )
    # Save history before replacing the live catalog so compatibility checks
    # can compare projects against older game versions.
    delta = database.record_catalog_snapshot(
        assets,
        archive_fingerprint=fingerprint,
        indexed_at=timestamp,
    )
    database.upsert_assets(assets, replace_catalog=True)
    database.upsert_visual_assets(visual_assets, replace_catalog=True)
    return IndexResult(
        indexed=len(assets),
        visual_indexed=len(visual_assets),
        archive_fingerprint=fingerprint,
        warnings=[
            "Catalog associations combine conservative paths with heroes, abilities, "
            "sound-event, response-rule, and talker metadata.",
            (
                f"Catalog delta: {delta['added']} added, {delta['changed']} changed, "
                f"{delta['removed']} removed."
            ),
        ],
        duration_ms=round((time.monotonic() - started) * 1000),
    )
