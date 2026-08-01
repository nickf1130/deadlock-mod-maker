"""Take mod packages out of the addons folder without destroying them.

Used for the packages a mod manager has lost track of. Those are usually the
installed copy of a mod the manager thinks it uninstalled, so the game keeps
loading something the player believes is gone.

Nothing here deletes. Every package is *moved* into the application's backup
folder, which sits outside the game directory so Source 2 cannot mount it. If
the removal turns out to be a mistake, the fix is to move the file back, and
:func:`move_packages_to_backup` returns exactly where each one went so the
interface can say so.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..errors import validation_error

# Each run gets its own folder, so removing two mods a week apart cannot have
# the second overwrite the first.
BACKUP_FOLDER = "removed-mods"

MAX_PACKAGES = 50


@dataclass(frozen=True, slots=True)
class MovedPackage:
    original_path: Path
    backup_path: Path
    size_bytes: int

    def as_payload(self) -> dict[str, object]:
        return {
            "originalPath": str(self.original_path),
            "backupPath": str(self.backup_path),
            "filename": self.original_path.name,
            "sizeBytes": self.size_bytes,
        }


@dataclass(slots=True)
class BackupResult:
    backup_directory: Path
    moved: list[MovedPackage] = field(default_factory=list)

    def as_payload(self) -> dict[str, object]:
        return {
            "backupDirectory": str(self.backup_directory),
            "movedCount": len(self.moved),
            "movedBytes": sum(item.size_bytes for item in self.moved),
            "moved": [item.as_payload() for item in self.moved],
        }


def move_packages_to_backup(packages: list[Path], backup_root: Path) -> BackupResult:
    """Move each package in ``packages`` into a timestamped backup folder.

    Every package is validated *before* anything moves. A half-finished cleanup
    that emptied three of five files and then failed would leave the player
    worse off than not starting, and with no obvious way to tell what happened.
    """
    if not packages:
        raise validation_error("Choose at least one package to remove")
    if len(packages) > MAX_PACKAGES:
        raise validation_error(
            f"At most {MAX_PACKAGES} packages can be removed at once",
            count=len(packages),
        )

    validated = [_validated_package(package) for package in packages]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = backup_root / BACKUP_FOLDER / stamp
    destination.mkdir(parents=True, exist_ok=True)

    result = BackupResult(backup_directory=destination)
    for package in validated:
        size = package.stat().st_size
        target = _unique_name(destination / package.name)
        # move, not copy-then-delete: on the same volume it is a rename, and it
        # can never leave the file in both places.
        shutil.move(str(package), str(target))
        result.moved.append(
            MovedPackage(original_path=package, backup_path=target, size_bytes=size)
        )
    return result


def _validated_package(package: Path) -> Path:
    if package.suffix.casefold() not in {".vpk", ".pak"}:
        raise validation_error(
            "Only .vpk or .pak files can be removed", path=str(package)
        )
    if not package.is_file():
        raise validation_error("Package does not exist", path=str(package))
    return package


def _unique_name(target: Path) -> Path:
    """Avoid clobbering a file already in the backup folder.

    Two mods can ship packages with the same name, and both may need removing
    in one go.
    """
    if not target.exists():
        return target
    for index in range(2, 100):
        candidate = target.with_name(f"{target.stem}-{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise validation_error("Could not find a free name in the backup folder")
