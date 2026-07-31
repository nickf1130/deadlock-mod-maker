"""Compare mod packages to answer "can I combine these?".

Merging two mods is a path-level operation: for every file both of them
contain, one has to win. So the question is decided entirely by which paths
they share, and what kind of resource sits at those paths.

Two outcomes matter:

* **A shared texture, material or sound.** Harmless. Pick whichever you prefer
  and the rest of both mods is unaffected.
* **A shared model.** Not resolvable by picking files. In Deadlock a hero and
  the weapon they hold live in the same ``.vmdl_c``, so whichever mod wins that
  file brings its body *and* its gun. Wanting the body from one and the gun
  from the other means editing the model itself, not merging packages.

That distinction is the whole point of this module: it turns "here are 40
colliding paths" into "these two cannot be merged, and here is why".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..errors import validation_error
from ..paths import normalize_internal_path
from ..vpk import VpkEntry, list_vpk, read_vpk_entry
from .inspection import INSEPARABLE_KINDS, classify_extension
from .references import references_materials

MIN_PACKAGES = 2
MAX_PACKAGES = 10

# Models are read in full to list what they reference. Hero models run to a few
# megabytes; the cap stops a malformed package from being read into memory.
MAX_MODEL_BYTES = 64_000_000


@dataclass(frozen=True, slots=True)
class ComparedPackage:
    """One package in the comparison."""

    path: Path
    entry_count: int
    size_bytes: int
    # Paths only this package has. These always survive a merge.
    unique_count: int

    def as_payload(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "filename": self.path.name,
            "entryCount": self.entry_count,
            "sizeBytes": self.size_bytes,
            "uniqueCount": self.unique_count,
        }


@dataclass(frozen=True, slots=True)
class SharedPath:
    """One path present in more than one of the compared packages."""

    path: str
    kind: str
    filenames: list[str]
    # True when picking a winner is not enough, because the file bundles
    # several things the player thinks of separately.
    inseparable: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "filenames": self.filenames,
            "inseparable": self.inseparable,
        }


@dataclass(frozen=True, slots=True)
class ReferenceWarning:
    """A package whose materials the other package's model never asks for.

    Two mods can avoid sharing a single path and still fail to combine. If one
    replaces the hero model and points every material slot at its own folder,
    the other mod's materials are simply never loaded: no conflict, no effect.
    """

    model_package: str
    model_path: str
    supplier_package: str
    unreferenced_count: int
    examples: list[str]
    # How to make the supplier's materials reachable: move each one to the slot
    # the model actually reads. Matched on filename, so only slots the model
    # names are offered.
    suggested_renames: list[tuple[str, str]] = field(default_factory=list)
    # Supplier materials with no matching slot. Left alone rather than guessed
    # at: mapping "head" onto "headv2" may or may not be what the author meant.
    unmatched: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, object]:
        return {
            "modelPackage": self.model_package,
            "modelPath": self.model_path,
            "supplierPackage": self.supplier_package,
            "unreferencedCount": self.unreferenced_count,
            "examples": self.examples,
            "suggestedRenames": [
                {"source": source, "target": target}
                for source, target in self.suggested_renames
            ],
            "unmatched": self.unmatched,
        }


@dataclass(slots=True)
class ComparisonReport:
    packages: list[ComparedPackage] = field(default_factory=list)
    shared: list[SharedPath] = field(default_factory=list)
    reference_warnings: list[ReferenceWarning] = field(default_factory=list)

    @property
    def blockers(self) -> list[SharedPath]:
        """Shared paths that a file-level merge cannot resolve."""
        return [entry for entry in self.shared if entry.inseparable]

    @property
    def mergeable(self) -> bool:
        """Whether combining these packages can give a predictable result."""
        return not self.blockers and not self.reference_warnings

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.shared:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return counts

    def as_payload(self) -> dict[str, object]:
        return {
            "packages": [package.as_payload() for package in self.packages],
            "sharedCount": len(self.shared),
            "blockerCount": len(self.blockers),
            "referenceWarnings": [
                warning.as_payload() for warning in self.reference_warnings
            ],
            "mergeable": self.mergeable,
            "countsByKind": self.counts_by_kind(),
            "shared": [entry.as_payload() for entry in self.shared],
        }


def compare_mod_packages(paths: list[Path]) -> ComparisonReport:
    """Report what ``paths`` have in common and whether they can be merged."""
    packages = _validated_packages(paths)

    # Which packages contain each path, compared case insensitively because
    # both the VPK format and Windows treat paths that way.
    holders: dict[str, list[str]] = defaultdict(list)
    original_case: dict[str, str] = {}
    entries_by_package: dict[Path, list[str]] = {}

    # Models and the materials each package ships, used for the reference check.
    models_by_package: dict[str, list[tuple[str, VpkEntry]]] = defaultdict(list)
    materials_by_package: dict[str, set[str]] = defaultdict(set)

    for package_path in packages:
        seen: set[str] = set()
        for entry in list_vpk(package_path):
            normalized = normalize_internal_path(entry.path)
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            original_case.setdefault(key, normalized)
            holders[key].append(package_path.name)
            kind = classify_extension(normalized)
            if kind == "model":
                models_by_package[package_path.name].append((normalized, entry))
            elif kind == "material":
                materials_by_package[package_path.name].add(key)
        entries_by_package[package_path] = sorted(seen)

    report = ComparisonReport()
    for package_path in packages:
        keys = entries_by_package[package_path]
        report.packages.append(
            ComparedPackage(
                path=package_path,
                entry_count=len(keys),
                size_bytes=package_path.stat().st_size,
                unique_count=sum(1 for key in keys if len(holders[key]) == 1),
            )
        )

    for key in sorted(holders):
        filenames = holders[key]
        if len(filenames) < 2:
            continue
        path = original_case[key]
        kind = classify_extension(path)
        report.shared.append(
            SharedPath(
                path=path,
                kind=kind,
                filenames=sorted(filenames, key=str.casefold),
                inseparable=kind in INSEPARABLE_KINDS,
            )
        )

    # Show the blocking collisions first: they decide whether a merge is
    # worth attempting at all.
    report.shared.sort(key=lambda entry: (not entry.inseparable, entry.path.casefold()))
    report.reference_warnings = _find_reference_warnings(
        packages, models_by_package, materials_by_package, original_case
    )
    return report


def _suggest_renames(
    orphaned: list[str],
    referenced: set[str],
    original_case: dict[str, str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pair each unused material with the model slot of the same filename.

    Matching on filename is conservative on purpose. It maps ``body`` to
    ``body`` and leaves ``head`` unmatched when the model wants ``headv2``,
    because renaming across different names is a judgement about the author's
    intent that this code has no basis to make.
    """
    slots_by_name = {PurePosixPath(value).name: value for value in referenced}
    renames: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for value in orphaned:
        source = original_case.get(value, value)
        slot = slots_by_name.get(PurePosixPath(value).name)
        if slot:
            renames.append((source, original_case.get(slot, slot)))
        else:
            unmatched.append(source)
    return renames, unmatched


def _find_reference_warnings(
    packages: list[Path],
    models_by_package: dict[str, list[tuple[str, VpkEntry]]],
    materials_by_package: dict[str, set[str]],
    original_case: dict[str, str],
) -> list[ReferenceWarning]:
    """Spot packages whose materials another package's model never asks for.

    Only a replaced model can orphan another mod's materials, so packages that
    ship no model are never the cause. A supplier whose materials are
    referenced even once by a given model is left alone: partial overlap is
    normal and not worth a warning.

    Each model is checked on its own rather than pooling a package's models
    together. Authors often leave an unused spare in the package - a
    ``*_backup.vmdl_c`` next to the real one - and pooling lets that dead file
    vouch for materials the live model never touches, hiding the very problem
    this check exists to find.
    """
    by_name = {package.name: package for package in packages}
    warnings: list[ReferenceWarning] = []

    for model_package, models in models_by_package.items():
        package_path = by_name[model_package]
        for model_path, entry in models:
            try:
                data = read_vpk_entry(package_path, entry, max_bytes=MAX_MODEL_BYTES)
            except Exception:  # noqa: BLE001
                # An unreadable model tells us nothing either way, and the rest
                # of the comparison is still useful.
                continue
            referenced = {value.casefold() for value in references_materials(data)}
            if not referenced:
                continue

            for supplier, supplied in materials_by_package.items():
                if supplier == model_package or not supplied:
                    continue
                orphaned = sorted(supplied - referenced)
                if len(orphaned) != len(supplied):
                    continue
                renames, unmatched = _suggest_renames(
                    orphaned, referenced, original_case
                )
                warnings.append(
                    ReferenceWarning(
                        model_package=model_package,
                        model_path=model_path,
                        supplier_package=supplier,
                        unreferenced_count=len(orphaned),
                        examples=[original_case.get(value, value) for value in orphaned[:5]],
                        suggested_renames=renames,
                        unmatched=unmatched,
                    )
                )
    warnings.sort(key=lambda warning: (warning.supplier_package, warning.model_path))
    return warnings


def _validated_packages(paths: list[Path]) -> list[Path]:
    if len(paths) < MIN_PACKAGES:
        raise validation_error(f"Choose at least {MIN_PACKAGES} mod packages to compare")
    if len(paths) > MAX_PACKAGES:
        raise validation_error(f"A maximum of {MAX_PACKAGES} packages can be compared at once")
    resolved: list[Path] = []
    for package_path in paths:
        if package_path.suffix.casefold() not in {".vpk", ".pak"}:
            raise validation_error(
                "Mod packages must end in .vpk or .pak", path=str(package_path)
            )
        if not package_path.is_file():
            raise validation_error("Mod package does not exist", path=str(package_path))
        resolved.append(package_path)
    if len({package.resolve() for package in resolved}) != len(resolved):
        raise validation_error("Choose two different packages to compare")
    return resolved
