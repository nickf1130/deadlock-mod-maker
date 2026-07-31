from __future__ import annotations

import os
import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import StudioError, validation_error
from .paths import normalize_internal_path
from .vpk import VPK_SIGNATURE, VpkEntry, copy_vpk_entry, list_vpk


@dataclass(frozen=True, slots=True)
class SelectedEntry:
    source: Path
    entry: VpkEntry
    # Where this entry is written in the combined package. Normally the path it
    # already had, but a rename rule can redirect it somewhere else.
    output_path: str

    @property
    def size(self) -> int:
        return self.entry.preload_bytes + self.entry.length


@dataclass(frozen=True, slots=True)
class RenameRule:
    """Write one package's file at a different path in the combined output.

    Needed because two mods can supply the same thing at different paths. A
    retexture may sit in ``models/x/vindicta/materials/`` while the model that
    should use it reads from ``models/x/hornet_v3/materials/``. Merging by
    identical path cannot express that; redirecting the entry can.

    Scoped to one package: the same internal path can exist in several inputs,
    and only the named one is redirected.
    """

    package: str
    source: str
    target: str

    @classmethod
    def from_payload(cls, value: dict[str, str]) -> RenameRule:
        return cls(
            package=str(value["package"]),
            source=normalize_internal_path(str(value["source"])),
            target=normalize_internal_path(str(value["target"])),
        )


ProgressCallback = Callable[[dict[str, object]], None]


def inspect_packages(paths: list[Path]) -> list[dict[str, object]]:
    _validate_inputs(paths)
    inventories: list[dict[str, object]] = []
    for package_path in paths:
        entries = list_vpk(package_path)
        inventories.append(
            {
                "path": str(package_path),
                "filename": package_path.name,
                "sizeBytes": package_path.stat().st_size,
                "entryCount": len(entries),
                "entries": [
                    {
                        "path": entry.path,
                        "sizeBytes": entry.preload_bytes + entry.length,
                        "crc32": f"{entry.crc32:08x}",
                        "archiveIndex": entry.archive_index,
                    }
                    for entry in entries
                ],
            }
        )
    return inventories


def combine_packages(
    paths: list[Path],
    output_path: Path,
    progress: ProgressCallback | None = None,
    renames: list[RenameRule] | None = None,
) -> dict[str, object]:
    _validate_inputs(paths, minimum=2)
    if output_path.suffix.casefold() not in {".vpk", ".pak"}:
        raise validation_error("Combined package output must end in .vpk or .pak")
    resolved_inputs = [value.resolve(strict=True) for value in paths]
    resolved_output = output_path.expanduser().resolve(strict=False)
    if resolved_output in resolved_inputs:
        raise validation_error("The combined output cannot overwrite an input package")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

    # Redirects, keyed by package filename then by the path inside it.
    rename_map: dict[str, dict[str, str]] = {}
    for rule in renames or []:
        rename_map.setdefault(rule.package.casefold(), {})[rule.source.casefold()] = rule.target
    _validate_renames(resolved_inputs, rename_map)

    winners: dict[str, SelectedEntry] = {}
    conflicts: list[dict[str, str]] = []
    total_inputs = len(resolved_inputs)
    for input_index, package_path in enumerate(resolved_inputs, start=1):
        _emit(
            progress,
            "reading",
            input_index - 1,
            total_inputs,
            f"Reading {package_path.name}…",
        )
        redirects = rename_map.get(package_path.name.casefold(), {})
        for entry in list_vpk(package_path):
            # A renamed entry takes part in precedence at its new path, which
            # is the whole point: it has to be able to win that slot.
            output = redirects.get(entry.path.casefold(), entry.path)
            key = output.casefold()
            previous = winners.get(key)
            if previous:
                conflicts.append(
                    {
                        "path": output,
                        "replacedPackage": previous.source.name,
                        "winnerPackage": package_path.name,
                    }
                )
            winners[key] = SelectedEntry(package_path, entry, output)
        _emit(
            progress,
            "reading",
            input_index,
            total_inputs,
            f"Read {package_path.name}.",
        )

    selected = sorted(winners.values(), key=lambda value: value.output_path.casefold())
    if not selected:
        raise StudioError("PACKAGE_EMPTY", "The selected packages contain no entries.")
    offsets: dict[str, int] = {}
    data_offset = 0
    for value in selected:
        if value.size > 0xFFFFFFFF or data_offset + value.size > 0xFFFFFFFF:
            raise StudioError(
                "PACKAGE_TOO_LARGE",
                "The merged single-file VPK exceeds the format's 32-bit data limit.",
            )
        offsets[value.output_path.casefold()] = data_offset
        data_offset += value.size

    tree = _build_tree(selected, offsets)
    temporary = resolved_output.with_name(f".{resolved_output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as output:
            output.write(struct.pack("<III", VPK_SIGNATURE, 1, len(tree)))
            output.write(tree)
            total_entries = len(selected)
            for index, value in enumerate(selected, start=1):
                _emit(
                    progress,
                    "writing",
                    index - 1,
                    total_entries,
                    f"Writing {value.output_path}…",
                )
                copied = copy_vpk_entry(value.source, value.entry, output)
                if copied != value.size:
                    raise StudioError(
                        "PACKAGE_WRITE_FAILED",
                        "A package entry did not produce the expected number of bytes.",
                        {"path": value.output_path},
                    )
                _emit(
                    progress,
                    "writing",
                    index,
                    total_entries,
                    f"Wrote {value.output_path}.",
                )
        verified = list_vpk(temporary)
        if len(verified) != len(selected):
            raise StudioError(
                "PACKAGE_VERIFY_FAILED",
                "The combined package failed its post-write directory verification.",
            )
        os.replace(temporary, resolved_output)
    finally:
        temporary.unlink(missing_ok=True)

    _emit(progress, "complete", len(selected), len(selected), "Combined package is ready.")
    return {
        "outputPath": str(resolved_output),
        "entryCount": len(selected),
        "inputCount": len(resolved_inputs),
        "conflictCount": len(conflicts),
        "conflicts": conflicts,
        "renamedCount": sum(
            1 for value in selected if value.output_path != value.entry.path
        ),
        "sizeBytes": resolved_output.stat().st_size,
    }


def _build_tree(selected: list[SelectedEntry], offsets: dict[str, int]) -> bytes:
    grouped: dict[str, dict[str, list[SelectedEntry]]] = {}
    for value in selected:
        parsed = PurePosixPath(value.output_path)
        extension = " "
        if parsed.suffix:
            extension = parsed.suffix[1:]
        directory = parsed.parent.as_posix()
        if directory == ".":
            directory = " "
        grouped.setdefault(extension, {}).setdefault(directory, []).append(value)

    tree = bytearray()
    for extension in sorted(grouped, key=str.casefold):
        tree.extend(extension.encode("utf-8") + b"\0")
        directories = grouped[extension]
        for directory in sorted(directories, key=str.casefold):
            tree.extend(directory.encode("utf-8") + b"\0")
            for value in sorted(
                directories[directory],
                key=lambda selected_entry: PurePosixPath(
                    selected_entry.output_path
                ).stem.casefold(),
            ):
                filename = PurePosixPath(value.output_path).stem
                tree.extend(filename.encode("utf-8") + b"\0")
                tree.extend(
                    struct.pack(
                        "<IHHIIH",
                        value.entry.crc32,
                        0,
                        0x7FFF,
                        offsets[value.output_path.casefold()],
                        value.size,
                        0xFFFF,
                    )
                )
            tree.extend(b"\0")
        tree.extend(b"\0")
    tree.extend(b"\0")
    return bytes(tree)


def _validate_renames(
    resolved_inputs: list[Path], rename_map: dict[str, dict[str, str]]
) -> None:
    """Reject rules that cannot apply, rather than silently doing nothing.

    A rule naming a package or path that is not there is almost always a typo,
    and the resulting package would look correct while missing the redirect.
    """
    available = {package.name.casefold(): package for package in resolved_inputs}
    for package_name, redirects in rename_map.items():
        package_path = available.get(package_name)
        if not package_path:
            raise validation_error(
                "A rename rule names a package that is not being combined",
                package=package_name,
            )
        contents = {entry.path.casefold() for entry in list_vpk(package_path)}
        for source, target in redirects.items():
            if source not in contents:
                raise validation_error(
                    "A rename rule names a file that is not in that package",
                    package=package_path.name,
                    path=source,
                )
            if not target or target.endswith("/"):
                raise validation_error(
                    "A rename rule has an empty destination path",
                    package=package_path.name,
                    path=source,
                )


def _validate_inputs(paths: list[Path], *, minimum: int = 1) -> None:
    if len(paths) < minimum:
        raise validation_error(f"Choose at least {minimum} package files")
    if len(paths) > 50:
        raise validation_error("A maximum of 50 packages can be combined at once")
    for package_path in paths:
        if package_path.suffix.casefold() not in {".vpk", ".pak"}:
            raise validation_error("Package files must end in .vpk or .pak", path=str(package_path))
        if not package_path.is_file():
            raise validation_error("Package file does not exist", path=str(package_path))


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    completed: int,
    total: int,
    message: str,
) -> None:
    if progress:
        progress(
            {
                "event": "packages.progress",
                "stage": stage,
                "completed": completed,
                "total": total,
                "message": message,
            }
        )
