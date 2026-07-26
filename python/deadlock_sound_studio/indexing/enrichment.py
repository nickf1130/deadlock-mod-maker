from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..paths import normalize_internal_path
from ..vpk import VpkEntry, read_vpk_entry

SOUND_REFERENCE = re.compile(
    r"(?P<path>(?:sounds?/)?[a-zA-Z0-9_./-]+\.vsnd(?:_c)?)",
    re.IGNORECASE,
)
PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{3,}")


@dataclass(frozen=True, slots=True)
class SoundAssociation:
    hero_id: str | None = None
    hero_name: str | None = None
    ability_name: str | None = None
    sound_event: str | None = None


def _field(context: str, names: tuple[str, ...]) -> str | None:
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(
        rf"\b(?:{alternatives})\b\s*(?:=|:)?\s*[\"']?([a-zA-Z0-9_.:/ -]+)",
        context,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).strip().strip("\"'")
    return value.splitlines()[0].strip() or None


def _sound_path(value: str) -> str:
    normalized = value.replace("\\", "/").lstrip("/")
    if not normalized.casefold().startswith(("sound/", "sounds/")):
        normalized = f"sounds/{normalized}"
    if normalized.casefold().endswith(".vsnd"):
        normalized += "_c"
    return normalize_internal_path(normalized)


def _metadata_candidate(entry: VpkEntry) -> bool:
    lower = entry.path.casefold()
    name = PurePosixPath(lower).name
    return (
        name == "heroes.vdata_c"
        or lower.endswith(".vsndevts_c")
        or lower.endswith(".vrr_c")
        or lower.endswith(".talker_c")
        or "response" in lower
        or "talker" in lower
        or ("abilit" in lower and lower.endswith(".vdata_c"))
        or ("hero" in lower and lower.endswith(".vdata_c"))
    )


def _printable_text(payload: bytes) -> str:
    return "\n".join(
        match.group(0).decode("utf-8", errors="ignore")
        for match in PRINTABLE_RUN.finditer(payload)
    )


@dataclass(frozen=True, slots=True)
class CatalogMetadata:
    associations: dict[str, SoundAssociation]
    hero_names: dict[str, str]
    associations_by_unique_basename: dict[str, SoundAssociation]


def read_catalog_metadata(
    archive: Path, entries: list[VpkEntry]
) -> CatalogMetadata:
    """Read optional hero, ability, event, and talker hints from the archive."""
    associations: dict[str, SoundAssociation] = {}
    hero_names: dict[str, str] = {}
    for entry in entries:
        if not _metadata_candidate(entry):
            continue
        try:
            text = _printable_text(read_vpk_entry(archive, entry))
        except Exception:
            # Metadata enrichment is best-effort; path classification still works.
            continue
        for match in re.finditer(
            r"\bhero(?:_id)?\b\s*(?:=|:)?\s*[\"']?([a-zA-Z0-9_-]+)"
            r".{0,180}?\b(?:display_name|name)\b\s*(?:=|:)?\s*[\"']?"
            r"([a-zA-Z][a-zA-Z0-9 '._-]+)",
            text,
            re.IGNORECASE | re.DOTALL,
        ):
            hero_names[match.group(1).casefold()] = match.group(2).strip()
        for reference in SOUND_REFERENCE.finditer(text):
            start = max(0, reference.start() - 320)
            end = min(len(text), reference.end() + 320)
            context = text[start:end]
            hero_id = _field(context, ("hero_id", "hero", "talker"))
            ability = _field(context, ("ability_name", "ability"))
            event = _field(
                context,
                ("event_name", "sound_event", "event", "response_rule"),
            )
            if event and event.casefold().startswith(("sound", "sounds")):
                event = None
            path = _sound_path(reference.group("path"))
            normalized_hero_id = None
            hero_name = None
            if hero_id:
                normalized_hero_id = hero_id.casefold().replace(" ", "_")
                hero_name = hero_names.get(hero_id.casefold())
            associations[path.casefold()] = SoundAssociation(
                hero_id=normalized_hero_id,
                hero_name=hero_name,
                ability_name=ability,
                sound_event=event,
            )

    basename_groups: dict[str, list[SoundAssociation]] = {}
    for path, association in associations.items():
        name = PurePosixPath(path).name.casefold()
        basename_groups.setdefault(name, []).append(association)
    unique = {
        name: values[0]
        for name, values in basename_groups.items()
        if len(values) == 1
    }
    return CatalogMetadata(associations, hero_names, unique)


def association_for(
    metadata: CatalogMetadata, internal_path: str
) -> SoundAssociation:
    direct = metadata.associations.get(internal_path.casefold())
    if direct:
        return direct
    return metadata.associations_by_unique_basename.get(
        PurePosixPath(internal_path).name.casefold(), SoundAssociation()
    )


def hero_display_name(
    metadata: CatalogMetadata, hero_id: str | None
) -> str | None:
    if not hero_id:
        return None
    return metadata.hero_names.get(hero_id.casefold())
