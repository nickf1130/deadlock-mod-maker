from __future__ import annotations

import os
import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import StudioError, validation_error
from .vpk import VPK_SIGNATURE, VpkEntry, copy_vpk_entry, list_vpk


@dataclass(frozen=True, slots=True)
class SelectedEntry:
    source: Path
    entry: VpkEntry

    @property
    def size(self) -> int:
        return self.entry.preload_bytes + self.entry.length


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
) -> dict[str, object]:
    _validate_inputs(paths, minimum=2)
    if output_path.suffix.casefold() not in {".vpk", ".pak"}:
        raise validation_error("Combined package output must end in .vpk or .pak")
    resolved_inputs = [value.resolve(strict=True) for value in paths]
    resolved_output = output_path.expanduser().resolve(strict=False)
    if resolved_output in resolved_inputs:
        raise validation_error("The combined output cannot overwrite an input package")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)

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
        for entry in list_vpk(package_path):
            key = entry.path.casefold()
            previous = winners.get(key)
            if previous:
                conflicts.append(
                    {
                        "path": entry.path,
                        "replacedPackage": previous.source.name,
                        "winnerPackage": package_path.name,
                    }
                )
            winners[key] = SelectedEntry(package_path, entry)
        _emit(
            progress,
            "reading",
            input_index,
            total_inputs,
            f"Read {package_path.name}.",
        )

    selected = sorted(winners.values(), key=lambda value: value.entry.path.casefold())
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
        offsets[value.entry.path.casefold()] = data_offset
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
                    f"Writing {value.entry.path}…",
                )
                copied = copy_vpk_entry(value.source, value.entry, output)
                if copied != value.size:
                    raise StudioError(
                        "PACKAGE_WRITE_FAILED",
                        "A package entry did not produce the expected number of bytes.",
                        {"path": value.entry.path},
                    )
                _emit(
                    progress,
                    "writing",
                    index,
                    total_entries,
                    f"Wrote {value.entry.path}.",
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
        "sizeBytes": resolved_output.stat().st_size,
    }


def _build_tree(selected: list[SelectedEntry], offsets: dict[str, int]) -> bytes:
    grouped: dict[str, dict[str, list[SelectedEntry]]] = {}
    for value in selected:
        parsed = PurePosixPath(value.entry.path)
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
                key=lambda selected_entry: PurePosixPath(selected_entry.entry.path).stem.casefold(),
            ):
                filename = PurePosixPath(value.entry.path).stem
                tree.extend(filename.encode("utf-8") + b"\0")
                tree.extend(
                    struct.pack(
                        "<IHHIIH",
                        value.entry.crc32,
                        0,
                        0x7FFF,
                        offsets[value.entry.path.casefold()],
                        value.size,
                        0xFFFF,
                    )
                )
            tree.extend(b"\0")
        tree.extend(b"\0")
    tree.extend(b"\0")
    return bytes(tree)


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
