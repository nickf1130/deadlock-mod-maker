"""Find mods in the addons folder that try to replace the same game file.

Two installed mods that both contain ``sounds/ui/click.vsnd_c`` cannot both
win. One of them silently loses, which is the usual explanation for "I
installed a mod and nothing happened".

Finding that out only needs the directory listing of each VPK, so this check is
cheap: no compiling, no extraction, and the game does not need to be running.

A deliberate limitation: this module reports *that* packages collide, not which
one the game ends up using. Source 2 addon load order depends on the game's own
addon configuration, and guessing it would produce confident-sounding advice
that is wrong some of the time. Collisions are actionable on their own - the
fix is almost always to remove one of the mods.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import validation_error
from ..paths import normalize_internal_path
from ..vpk import list_vpk

PACKAGE_SUFFIXES = {".vpk", ".pak"}

# Guard against being pointed at something enormous by mistake.
MAX_PACKAGES = 200


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    """One mod file found in the addons folder."""

    path: Path
    entry_count: int
    size_bytes: int
    # Set when the package could not be read; it is reported rather than
    # skipped so a corrupt mod does not just vanish from the results.
    error: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "filename": self.path.name,
            "entryCount": self.entry_count,
            "sizeBytes": self.size_bytes,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class Conflict:
    """One game path claimed by more than one installed mod."""

    path: str
    filenames: list[str]

    def as_payload(self) -> dict[str, object]:
        return {"path": self.path, "filenames": self.filenames}


@dataclass(slots=True)
class ConflictReport:
    directory: Path
    packages: list[InstalledPackage] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def conflicting_filenames(self) -> list[str]:
        """Every mod involved in at least one collision."""
        names: set[str] = set()
        for conflict in self.conflicts:
            names.update(conflict.filenames)
        return sorted(names, key=str.casefold)

    @property
    def unreadable(self) -> list[InstalledPackage]:
        return [package for package in self.packages if package.error]

    def as_payload(self) -> dict[str, object]:
        return {
            "directory": str(self.directory),
            "packageCount": len(self.packages),
            "conflictCount": len(self.conflicts),
            "conflictingFilenames": self.conflicting_filenames,
            "unreadableCount": len(self.unreadable),
            "packages": [package.as_payload() for package in self.packages],
            "conflicts": [conflict.as_payload() for conflict in self.conflicts],
        }


def find_addon_conflicts(directory: Path) -> ConflictReport:
    """Compare every mod package in ``directory`` and report shared paths."""
    addons = _validated_directory(directory)
    report = ConflictReport(directory=addons)

    # Which packages claim each internal path. Paths are compared case
    # insensitively because the VPK format and Windows both treat them that way.
    claims: dict[str, list[str]] = defaultdict(list)

    for package_path in _package_files(addons):
        try:
            entries = list_vpk(package_path)
        except Exception as error:  # noqa: BLE001 - reported, never swallowed
            report.packages.append(
                InstalledPackage(
                    path=package_path,
                    entry_count=0,
                    size_bytes=package_path.stat().st_size,
                    error=str(error),
                )
            )
            continue

        report.packages.append(
            InstalledPackage(
                path=package_path,
                entry_count=len(entries),
                size_bytes=package_path.stat().st_size,
            )
        )
        # A package listing the same path twice should still only claim it once.
        seen: set[str] = set()
        for entry in entries:
            key = normalize_internal_path(entry.path).casefold()
            if key in seen:
                continue
            seen.add(key)
            claims[key].append(package_path.name)

    report.conflicts = [
        Conflict(path=path, filenames=sorted(filenames, key=str.casefold))
        for path, filenames in sorted(claims.items())
        if len(filenames) > 1
    ]
    return report


def _package_files(directory: Path) -> list[Path]:
    """Mod packages directly inside ``directory``, in a stable order.

    Only the top level is searched. Source 2 does not load addons from nested
    folders, so recursing would report conflicts that cannot actually happen.
    """
    files = sorted(
        (
            candidate
            for candidate in directory.iterdir()
            if candidate.is_file() and candidate.suffix.casefold() in PACKAGE_SUFFIXES
        ),
        key=lambda candidate: candidate.name.casefold(),
    )
    if len(files) > MAX_PACKAGES:
        raise validation_error(
            f"The addons folder contains more than {MAX_PACKAGES} packages",
            directory=str(directory),
            found=len(files),
        )
    return files


def _validated_directory(directory: Path) -> Path:
    if not directory.exists():
        raise validation_error(
            "The addons folder does not exist yet. It is created the first time "
            "you install a mod.",
            directory=str(directory),
        )
    if not directory.is_dir():
        raise validation_error("The addons path is not a folder", directory=str(directory))
    return directory
