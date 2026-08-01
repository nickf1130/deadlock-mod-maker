"""Find mods in the addons folder that try to replace the same game file.

Two installed mods that both contain ``sounds/ui/click.vsnd_c`` cannot both
win. One of them silently loses, which is the usual explanation for "I
installed a mod and nothing happened".

Finding that out only needs the directory listing of each VPK, so this check is
cheap: no compiling, no extraction, and the game does not need to be running.

Three things stop a raw path comparison from being useful on a real machine,
and each is handled below:

* **Disabled mods.** Deadlock Mod Manager leaves disabled mods in the folder
  under a renamed file. The game never loads them, so they cannot conflict.
* **One mod, several VPKs.** A single mod is often shipped as two or three
  packages. Paths shared between them belong to the same author and are not a
  conflict the player can act on.
* **Files the game never loads.** Almost every mod bundles a ``readme.txt``.
  Those collide constantly and mean nothing.

A deliberate limitation: this module reports *that* mods collide, not which one
the game ends up using. See the note on load order in ``find_addon_conflicts``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..errors import validation_error
from ..paths import normalize_internal_path
from ..vpk import list_vpk

PACKAGE_SUFFIXES = {".vpk", ".pak"}

# Guard against being pointed at something enormous by mistake.
MAX_PACKAGES = 200

# Deadlock Mod Manager writes this alongside the packages it installs.
MOD_MANAGER_STATE_FILE = ".dmm.json"

# Its catalogue lives outside the game folder and is the only place the
# human-readable mod names exist. The file next to the packages records ids and
# filenames but no titles, so "Mod 650634" is the best a folder-only scan can
# do. Reading this turns that into "QOL Lock".
MOD_MANAGER_CATALOGUE = Path("dev.stormix.deadlock-mod-manager") / "state.json"


@dataclass(frozen=True, slots=True)
class ModManagerState:
    """What Deadlock Mod Manager believes is installed.

    Present only when the player uses that manager. Without it every package is
    treated as its own enabled mod, which is the right guess for a hand-managed
    addons folder.
    """

    # Lower-cased VPK filename -> the manager's id for the mod that owns it.
    owner_by_file: dict[str, str] = field(default_factory=dict)
    # Lower-cased VPK filename -> whether that mod is currently switched on.
    enabled_by_file: dict[str, bool] = field(default_factory=dict)
    # Mod id -> the name the player sees in the manager. Empty when the
    # catalogue could not be read; ids remain a usable fallback.
    name_by_mod_id: dict[str, str] = field(default_factory=dict)

    def owner(self, filename: str) -> str | None:
        return self.owner_by_file.get(filename.casefold())

    def name(self, mod_id: str) -> str | None:
        return self.name_by_mod_id.get(mod_id)

    def is_enabled(self, filename: str) -> bool:
        # Unknown files are assumed live: a package the manager does not track
        # was probably dropped in by hand, and the game will load it.
        return self.enabled_by_file.get(filename.casefold(), True)


def read_mod_names(catalogue: Path | None = None) -> dict[str, str]:
    """Mod id to display name, read from Deadlock Mod Manager's catalogue.

    The file wraps its real contents in a JSON string under "local-config",
    so it is decoded twice. Entries are keyed by both ids the manager uses:
    ``remoteId`` for mods downloaded from the site, and ``id`` for ones added
    locally, because the folder records reference whichever applies.

    Returns an empty mapping if anything is missing or unreadable. Names are a
    presentation nicety, never a reason to fail a scan.
    """
    if catalogue is None:
        app_data = os.environ.get("APPDATA")
        if not app_data:
            return {}
        catalogue = Path(app_data) / MOD_MANAGER_CATALOGUE
    if not catalogue.is_file():
        return {}
    try:
        outer = json.loads(catalogue.read_text(encoding="utf-8"))
        state = json.loads(outer["local-config"])["state"]
        mods = state["localMods"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}

    names: dict[str, str] = {}
    for mod in mods:
        if not isinstance(mod, dict):
            continue
        name = mod.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        for key in (mod.get("remoteId"), mod.get("id")):
            if key is not None:
                names[str(key)] = name.strip()
    return names


def read_mod_manager_state(directory: Path) -> ModManagerState | None:
    """Load Deadlock Mod Manager's record of the folder, if it wrote one."""
    state_file = directory / MOD_MANAGER_STATE_FILE
    if not state_file.is_file():
        return None
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        mods = raw["mods"]
    except (OSError, ValueError, KeyError, TypeError):
        # A manager file we cannot parse is not worth failing the scan over.
        return None

    owner_by_file: dict[str, str] = {}
    enabled_by_file: dict[str, bool] = {}
    for mod_id, info in mods.items():
        if not isinstance(info, dict):
            continue
        enabled = bool(info.get("enabled"))
        # "currentVpks" are the live filenames; "disabledVpks" are the renamed
        # copies left behind when a mod is switched off.
        for filename in list(info.get("currentVpks") or []) + list(
            info.get("disabledVpks") or []
        ):
            if not isinstance(filename, str):
                continue
            key = filename.casefold()
            owner_by_file[key] = str(mod_id)
            enabled_by_file[key] = enabled
    return ModManagerState(owner_by_file, enabled_by_file, read_mod_names())


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    """One mod file found in the addons folder."""

    path: Path
    entry_count: int
    size_bytes: int
    # The mod this package belongs to. Falls back to the filename when no mod
    # manager is present, so every package still has a stable identity.
    mod_id: str
    # The manager's display name, when it could be resolved.
    mod_name: str | None = None
    enabled: bool = True
    # Whether a mod manager claims this file. Only meaningful when one is
    # actually present: without a manager every package is managed by hand, so
    # singling any of them out would be noise. Hence the default.
    tracked: bool = True
    # Set when the package could not be read; it is reported rather than
    # skipped so a corrupt mod does not just vanish from the results.
    error: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "filename": self.path.name,
            "entryCount": self.entry_count,
            "sizeBytes": self.size_bytes,
            "modId": self.mod_id,
            "modName": self.mod_name,
            "enabled": self.enabled,
            "tracked": self.tracked,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class Conflict:
    """One game path claimed by more than one installed mod."""

    path: str
    filenames: list[str]
    mod_ids: list[str]

    def as_payload(self) -> dict[str, object]:
        return {"path": self.path, "filenames": self.filenames, "modIds": self.mod_ids}


@dataclass(frozen=True, slots=True)
class ModConflict:
    """Two mods that overlap, and by how much.

    This is the view that answers "which of my mods are fighting", rather than
    making the player work it out from a list of paths.
    """

    mod_ids: list[str]
    filenames: list[str]
    path_count: int
    example_paths: list[str]

    def as_payload(self) -> dict[str, object]:
        return {
            "modIds": self.mod_ids,
            "filenames": self.filenames,
            "pathCount": self.path_count,
            "examplePaths": self.example_paths,
        }


@dataclass(slots=True)
class ConflictReport:
    directory: Path
    packages: list[InstalledPackage] = field(default_factory=list)
    # Conflicts on compiled resources, which the game definitely loads.
    conflicts: list[Conflict] = field(default_factory=list)
    # Overlaps on everything else: readmes, uncompiled sources, loose art.
    other_overlaps: list[Conflict] = field(default_factory=list)
    # The same conflicts grouped by which mods are involved.
    mod_conflicts: list[ModConflict] = field(default_factory=list)
    # Enabled packages that share no path with any other enabled package, so
    # merging them cannot lose anything.
    mergeable: list[InstalledPackage] = field(default_factory=list)
    uses_mod_manager: bool = False

    @property
    def enabled_packages(self) -> list[InstalledPackage]:
        return [package for package in self.packages if package.enabled]

    @property
    def disabled_packages(self) -> list[InstalledPackage]:
        return [package for package in self.packages if not package.enabled]

    @property
    def unreadable(self) -> list[InstalledPackage]:
        return [package for package in self.packages if package.error]

    @property
    def untracked(self) -> list[InstalledPackage]:
        """Packages the mod manager does not know about.

        Uninstalling through Deadlock Mod Manager does not always remove the
        installed copy. The manager renames a mod's file when it is switched
        off, so the folder can end up holding both the renamed copy the manager
        tracks *and* the original the game still loads. The manager then shows
        the mod as off while it is very much on, which is a confusing way to
        lose an afternoon.

        Empty when no manager is present, because then nothing is being tracked
        and every package is deliberate.
        """
        return [package for package in self.packages if not package.tracked]

    def as_payload(self) -> dict[str, object]:
        return {
            "directory": str(self.directory),
            "packageCount": len(self.packages),
            "enabledCount": len(self.enabled_packages),
            "disabledCount": len(self.disabled_packages),
            "usesModManager": self.uses_mod_manager,
            "conflictCount": len(self.conflicts),
            "otherOverlapCount": len(self.other_overlaps),
            "modConflictCount": len(self.mod_conflicts),
            "mergeableCount": len(self.mergeable),
            "mergeable": [package.as_payload() for package in self.mergeable],
            "untrackedCount": len(self.untracked),
            "untracked": [package.as_payload() for package in self.untracked],
            "unreadableCount": len(self.unreadable),
            "packages": [package.as_payload() for package in self.packages],
            "conflicts": [conflict.as_payload() for conflict in self.conflicts],
            "otherOverlaps": [conflict.as_payload() for conflict in self.other_overlaps],
            "modConflicts": [conflict.as_payload() for conflict in self.mod_conflicts],
        }


def is_compiled_resource(internal_path: str) -> bool:
    """True for the compiled assets Source 2 actually loads at runtime.

    Compiled Source 2 resources all end in ``_c`` - ``.vtex_c``, ``.vsnd_c``,
    ``.vxml_c`` and so on. Everything else in a mod VPK is documentation, or an
    uncompiled source the author bundled for reference. Those overlap all the
    time without affecting the game, so they are reported separately.
    """
    return PurePosixPath(internal_path).suffix.casefold().endswith("_c")


def find_addon_conflicts(directory: Path) -> ConflictReport:
    """Compare every enabled mod in ``directory`` and report shared paths.

    Load order is deliberately not predicted. Source 2 mounts the addons folder
    as one search path, and the effective winner depends on how the engine
    orders the packages inside it. Deadlock Mod Manager expresses order through
    the ``pakNN`` numbering it assigns, so that is where order should be
    changed - guessing here would produce confident advice that is wrong some
    of the time.
    """
    addons = _validated_directory(directory)
    manager = read_mod_manager_state(addons)
    report = ConflictReport(directory=addons, uses_mod_manager=manager is not None)

    # Which mods claim each internal path. Paths are compared case
    # insensitively because the VPK format and Windows both treat them that way.
    claims: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    original_case: dict[str, str] = {}

    for package_path in _package_files(addons):
        filename = package_path.name
        owner = manager.owner(filename) if manager else None
        mod_id = owner or filename
        mod_name = manager.name(mod_id) if manager else None
        enabled = manager.is_enabled(filename) if manager else True
        tracked = manager is None or owner is not None

        try:
            entries = list_vpk(package_path)
        # A corrupt package is reported below, never silently skipped.
        except Exception as error:  # noqa: BLE001
            report.packages.append(
                InstalledPackage(
                    path=package_path,
                    entry_count=0,
                    size_bytes=package_path.stat().st_size,
                    mod_id=mod_id,
                    mod_name=mod_name,
                    enabled=enabled,
                    tracked=tracked,
                    error=str(error),
                )
            )
            continue

        report.packages.append(
            InstalledPackage(
                path=package_path,
                entry_count=len(entries),
                size_bytes=package_path.stat().st_size,
                mod_id=mod_id,
                mod_name=mod_name,
                enabled=enabled,
                tracked=tracked,
            )
        )
        # A disabled mod is still on disk but never mounted, so it cannot take
        # part in a conflict.
        if not enabled:
            continue

        for entry in entries:
            normalized = normalize_internal_path(entry.path)
            key = normalized.casefold()
            original_case.setdefault(key, normalized)
            claims[key][mod_id].add(filename)

    _collect_conflicts(report, claims, original_case)
    _collect_mod_conflicts(report)
    report.mergeable = _collect_mergeable(report, claims)
    return report


def _collect_mergeable(
    report: ConflictReport, claims: dict[str, dict[str, set[str]]]
) -> list[InstalledPackage]:
    """Enabled packages that share no path with any other enabled package.

    Note this is deliberately stricter than the conflict list. Conflicts are
    reported per *mod*, because two packages from one author overlapping is not
    something a player can act on. Merging is per *file*, so that same overlap
    would silently drop one copy. A package is only offered for merging when no
    other package claims any of its paths, whoever owns it.
    """
    entangled: set[str] = set()
    for key, owners in claims.items():
        # Only files the game loads matter. Almost every mod bundles a
        # readme.txt, and treating that as an entanglement would rule out
        # nearly every package for no benefit: one readme simply wins.
        if not is_compiled_resource(key):
            continue
        filenames = {name for names in owners.values() for name in names}
        if len(filenames) > 1:
            entangled.update(filenames)

    return [
        package
        for package in report.packages
        if package.enabled and not package.error and package.path.name not in entangled
    ]


def _collect_conflicts(
    report: ConflictReport,
    claims: dict[str, dict[str, set[str]]],
    original_case: dict[str, str],
) -> None:
    """Split shared paths into real conflicts and harmless overlaps.

    A path only conflicts when *different mods* claim it. Two packages from the
    same mod sharing a path is the author's own business, not something the
    player can fix by uninstalling something.
    """
    for key in sorted(claims):
        owners = claims[key]
        if len(owners) < 2:
            continue
        path = original_case[key]
        filenames = sorted(
            (name for names in owners.values() for name in names), key=str.casefold
        )
        conflict = Conflict(
            path=path,
            filenames=filenames,
            mod_ids=sorted(owners, key=str.casefold),
        )
        if is_compiled_resource(path):
            report.conflicts.append(conflict)
        else:
            report.other_overlaps.append(conflict)


def _collect_mod_conflicts(report: ConflictReport) -> None:
    """Group the path conflicts by which pair of mods they involve."""
    grouped: dict[tuple[str, ...], list[Conflict]] = defaultdict(list)
    for conflict in report.conflicts:
        grouped[tuple(conflict.mod_ids)].append(conflict)

    report.mod_conflicts = sorted(
        (
            ModConflict(
                mod_ids=list(mod_ids),
                filenames=sorted(
                    {name for conflict in conflicts for name in conflict.filenames},
                    key=str.casefold,
                ),
                path_count=len(conflicts),
                example_paths=[conflict.path for conflict in conflicts[:5]],
            )
            for mod_ids, conflicts in grouped.items()
        ),
        key=lambda value: (-value.path_count, value.mod_ids),
    )


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
