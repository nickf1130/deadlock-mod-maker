from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .errors import StudioError
from .paths import normalize_internal_path

VPK_SIGNATURE = 0x55AA1234


@dataclass(frozen=True, slots=True)
class VpkEntry:
    path: str
    crc32: int
    archive_index: int
    offset: int
    length: int
    preload_bytes: int
    preload_data: bytes


def _read_cstring(stream: BinaryIO, limit: int) -> str:
    data = bytearray()
    while len(data) <= limit:
        value = stream.read(1)
        if not value:
            raise StudioError("VPK_INVALID", "Unexpected end of VPK directory tree")
        if value == b"\0":
            return data.decode("utf-8", errors="strict")
        data.extend(value)
    raise StudioError("VPK_INVALID", "VPK directory string exceeds the declared tree size")


def list_vpk(path: Path) -> list[VpkEntry]:
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise StudioError("VPK_INVALID", "VPK header is truncated")
        signature, version, tree_size = struct.unpack("<III", header)
        if signature != VPK_SIGNATURE or version not in (1, 2):
            raise StudioError("VPK_INVALID", "Unsupported or invalid VPK header", {"version": version})
        header_size = 12
        if version == 2:
            section_sizes = stream.read(16)
            if len(section_sizes) != 16:
                raise StudioError("VPK_INVALID", "VPK v2 header is truncated")
            header_size = 28
        tree_end = header_size + tree_size
        entries: list[VpkEntry] = []
        while stream.tell() < tree_end:
            extension = _read_cstring(stream, tree_size)
            if not extension:
                break
            while stream.tell() < tree_end:
                directory = _read_cstring(stream, tree_size)
                if not directory:
                    break
                while stream.tell() < tree_end:
                    filename = _read_cstring(stream, tree_size)
                    if not filename:
                        break
                    data = stream.read(18)
                    if len(data) != 18:
                        raise StudioError("VPK_INVALID", "VPK entry is truncated")
                    crc, preload, archive, offset, length, terminator = struct.unpack("<IHHIIH", data)
                    if terminator != 0xFFFF:
                        raise StudioError("VPK_INVALID", "VPK entry terminator is invalid")
                    preload_data = stream.read(preload)
                    if len(preload_data) != preload:
                        raise StudioError("VPK_INVALID", "VPK entry preload data is truncated")
                    directory_value = "" if directory == " " else directory
                    extension_value = "" if extension == " " else f".{extension}"
                    raw_path = f"{directory_value}/{filename}{extension_value}".lstrip("/")
                    entries.append(
                        VpkEntry(
                            path=normalize_internal_path(raw_path),
                            crc32=crc,
                            archive_index=archive,
                            offset=offset,
                            length=length,
                            preload_bytes=preload,
                            preload_data=preload_data,
                        )
                    )
        if stream.tell() > tree_end:
            raise StudioError("VPK_INVALID", "VPK directory tree exceeds its declared size")
        return entries


def read_vpk_entry(path: Path, entry: VpkEntry, *, max_bytes: int = 8_000_000) -> bytes:
    total_bytes = entry.preload_bytes + entry.length
    if total_bytes > max_bytes:
        raise StudioError(
            "VPK_ENTRY_TOO_LARGE",
            "The requested VPK metadata entry exceeds the safe parser limit.",
            {"path": entry.path, "length": total_bytes},
        )
    payload = bytearray(entry.preload_data)
    if entry.archive_index == 0x7FFF:
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise StudioError("VPK_INVALID", "VPK header is truncated")
            signature, version, tree_size = struct.unpack("<III", header)
            if signature != VPK_SIGNATURE or version not in (1, 2):
                raise StudioError("VPK_INVALID", "Unsupported or invalid VPK header")
            header_size = 28 if version == 2 else 12
            stream.seek(header_size + tree_size + entry.offset)
            payload.extend(stream.read(entry.length))
    else:
        stem = path.stem
        archive_stem = (
            f"{stem[:-4]}_{entry.archive_index:03d}"
            if stem.casefold().endswith("_dir")
            else f"{stem}_{entry.archive_index:03d}"
        )
        archive_path = path.with_name(f"{archive_stem}{path.suffix}")
        if not archive_path.is_file():
            raise StudioError(
                "VPK_ARCHIVE_MISSING",
                "A numbered VPK archive required by the directory index is missing.",
                {"path": str(archive_path), "entry": entry.path},
            )
        with archive_path.open("rb") as stream:
            stream.seek(entry.offset)
            payload.extend(stream.read(entry.length))
    if len(payload) != total_bytes:
        raise StudioError(
            "VPK_ENTRY_TRUNCATED",
            "The VPK entry payload is shorter than declared.",
            {"path": entry.path},
        )
    return bytes(payload)


def copy_vpk_entry(path: Path, entry: VpkEntry, destination: BinaryIO) -> int:
    """Copy one complete logical file, including any inline preload bytes."""
    destination.write(entry.preload_data)
    remaining = entry.length
    if entry.archive_index == 0x7FFF:
        with path.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise StudioError("VPK_INVALID", "VPK header is truncated")
            signature, version, tree_size = struct.unpack("<III", header)
            if signature != VPK_SIGNATURE or version not in (1, 2):
                raise StudioError("VPK_INVALID", "Unsupported or invalid VPK header")
            header_size = 28 if version == 2 else 12
            stream.seek(header_size + tree_size + entry.offset)
            _copy_exact(stream, destination, remaining, entry.path)
    else:
        stem = path.stem
        archive_stem = (
            f"{stem[:-4]}_{entry.archive_index:03d}"
            if stem.casefold().endswith("_dir")
            else f"{stem}_{entry.archive_index:03d}"
        )
        archive_path = path.with_name(f"{archive_stem}{path.suffix}")
        if not archive_path.is_file():
            raise StudioError(
                "VPK_ARCHIVE_MISSING",
                "A numbered VPK archive required by the directory index is missing.",
                {"path": str(archive_path), "entry": entry.path},
            )
        with archive_path.open("rb") as stream:
            stream.seek(entry.offset)
            _copy_exact(stream, destination, remaining, entry.path)
    return entry.preload_bytes + entry.length


def _copy_exact(source: BinaryIO, destination: BinaryIO, length: int, entry_path: str) -> None:
    remaining = length
    while remaining:
        chunk = source.read(min(1024 * 1024, remaining))
        if not chunk:
            raise StudioError(
                "VPK_ENTRY_TRUNCATED",
                "The VPK entry payload is shorter than declared.",
                {"path": entry_path},
            )
        destination.write(chunk)
        remaining -= len(chunk)
