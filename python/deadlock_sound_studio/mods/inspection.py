"""Work out what an already-built mod package actually replaces.

A mod ships as a VPK full of *compiled* resources (``.vsnd_c``, ``.vtex_c`` and
friends) stored at the same internal paths the game uses. To understand a mod
you therefore only need two things:

1. the list of paths inside its VPK, and
2. the catalog of paths the game currently ships.

Comparing the two answers the question players actually ask: "is this mod still
going to work?" A path the game no longer has is a replacement that silently
does nothing, which is the usual reason a mod breaks after a patch.

This module deliberately does **not** try to turn a mod back into an editable
project. The VPK contains compiled output, and the original MP3 or PSD that
produced it cannot be recovered from it. See ``ModPackageReport.importable``
for what can honestly be offered instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..database import Database
from ..errors import validation_error
from ..paths import normalize_internal_path
from ..vpk import list_vpk

# Compiled Source 2 extensions this application understands well enough to
# describe. Anything else is reported as "other" rather than guessed at.
# Add to this map as the app learns to handle more resource kinds.
KIND_BY_EXTENSION = {
    ".vsnd_c": "sound",
    ".vtex_c": "texture",
    ".vmat_c": "material",
    ".vmdl_c": "model",
    ".vpcf_c": "particle",
}
UNKNOWN_KIND = "other"

# Kinds where one file holds several things a player thinks of separately. A
# Deadlock hero and the weapon they carry share a single .vmdl_c, so two mods
# that both replace it cannot be merged by picking files: whichever wins brings
# its whole mesh. Only 4 of the game's 152 hero models ship a separate weapon.
INSEPARABLE_KINDS = frozenset({"model"})

# Only these kinds reach the catalog, so only these can be checked against it.
# A Panorama or model path is absent from the index because the indexer skips
# it, not because the game stopped shipping it. Reporting those as missing
# would call plenty of perfectly good mods broken. When the indexer learns a
# new kind, add it here too.
CHECKABLE_KINDS = frozenset({"sound", "texture", "material"})

MATCHED = "matched"
MISSING = "missing"
UNCHECKED = "unchecked"


@dataclass(frozen=True, slots=True)
class ModEntry:
    """One file inside a mod package, described against the game catalog."""

    path: str
    kind: str
    size_bytes: int
    # MATCHED   - the game ships this path, so the replacement will apply.
    # MISSING   - a kind we index, but the path is not in the catalog.
    # UNCHECKED - a kind we do not index, so nothing can be said either way.
    status: str
    # Populated for sounds the indexer managed to attribute to a hero.
    hero_name: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "sizeBytes": self.size_bytes,
            "status": self.status,
            "heroName": self.hero_name,
        }


@dataclass(slots=True)
class ModPackageReport:
    """The full picture for one mod package."""

    path: Path
    entries: list[ModEntry] = field(default_factory=list)

    @property
    def matched(self) -> list[ModEntry]:
        """Entries that override a path the game still ships."""
        return [entry for entry in self.entries if entry.status == MATCHED]

    @property
    def missing(self) -> list[ModEntry]:
        """Entries of an indexed kind whose target path is not in the catalog.

        These are the interesting ones: either the mod predates a patch that
        moved the file, or it was built for a different game version.
        """
        return [entry for entry in self.entries if entry.status == MISSING]

    @property
    def unchecked(self) -> list[ModEntry]:
        """Entries this application cannot verify, such as Panorama UI or models."""
        return [entry for entry in self.entries if entry.status == UNCHECKED]

    @property
    def heroes(self) -> list[str]:
        names = {entry.hero_name for entry in self.entries if entry.hero_name}
        return sorted(names)

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return counts

    def as_payload(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "filename": self.path.name,
            "sizeBytes": self.path.stat().st_size,
            "entryCount": len(self.entries),
            "matchedCount": len(self.matched),
            "missingCount": len(self.missing),
            "uncheckedCount": len(self.unchecked),
            "countsByKind": self.counts_by_kind(),
            "heroes": self.heroes,
            "suggestedProjectName": suggest_project_name(self.path),
            "entries": [entry.as_payload() for entry in self.entries],
        }


def classify_extension(internal_path: str) -> str:
    """Map an internal path to one of the kinds in :data:`KIND_BY_EXTENSION`."""
    suffix = PurePosixPath(internal_path).suffix.casefold()
    return KIND_BY_EXTENSION.get(suffix, UNKNOWN_KIND)


def suggest_project_name(package_path: Path) -> str:
    """Turn ``abrams_voice_pack.vpk`` into ``Abrams Voice Pack``."""
    stem = package_path.stem.replace("_", " ").replace("-", " ")
    return " ".join(word.capitalize() for word in stem.split() if word) or package_path.stem


def inspect_mod_package(package_path: Path, database: Database) -> ModPackageReport:
    """Describe every entry in ``package_path`` against the indexed game files.

    The database lookups are what make this useful, so an empty index produces
    a report where nothing matches. Callers should check that the archive has
    been indexed before presenting the result as a verdict on the mod.
    """
    package = _validated_package(package_path)
    report = ModPackageReport(path=package)

    for entry in list_vpk(package):
        internal = normalize_internal_path(entry.path)
        kind = classify_extension(internal)
        sound = None
        if kind in CHECKABLE_KINDS:
            sound = database.get_asset_by_path(internal)
            visual = None if sound else database.get_visual_asset_by_path(internal)
            status = MATCHED if sound or visual else MISSING
        else:
            status = UNCHECKED
        report.entries.append(
            ModEntry(
                path=internal,
                kind=kind,
                size_bytes=entry.preload_bytes + entry.length,
                status=status,
                hero_name=sound.hero_name if sound else None,
            )
        )

    report.entries.sort(key=lambda entry: entry.path.casefold())
    return report


def _validated_package(package_path: Path) -> Path:
    if package_path.suffix.casefold() not in {".vpk", ".pak"}:
        raise validation_error(
            "A mod package must end in .vpk or .pak", path=str(package_path)
        )
    if not package_path.is_file():
        raise validation_error("Mod package does not exist", path=str(package_path))
    return package_path
