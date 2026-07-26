from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from deadlock_sound_studio.database import Database
from deadlock_sound_studio.models import SoundAsset, SoundCategory, utc_now
from deadlock_sound_studio.paths import AppPaths
from deadlock_sound_studio.vpk import VPK_SIGNATURE


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths.from_root(tmp_path / "studio")


@pytest.fixture
def database(paths: AppPaths):
    value = Database(paths)
    yield value
    value.close()


def make_asset(
    internal_path: str = "sounds/ui/menu_accept.vsnd_c", **changes
) -> SoundAsset:
    values = {
        "id": changes.pop("id", internal_path.casefold()),
        "internal_path": internal_path,
        "compiled_path": internal_path,
        "filename": Path(internal_path).name,
        "extension": ".vsnd_c",
        "category": SoundCategory.UI,
        "source_archive": "pak01_dir.vpk",
        "archive_fingerprint": "archive",
        "last_indexed_at": utc_now(),
    }
    values.update(changes)
    return SoundAsset(**values)


def write_wav(path: Path, *, duration_seconds: float = 0.1, rate: int = 44_100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\0\0" * round(duration_seconds * rate))
    return path


def write_vpk(path: Path, entries: dict[str, bytes]) -> Path:
    tree = bytearray()
    grouped: dict[str, dict[str, list[tuple[str, bytes]]]] = {}
    for internal, payload in entries.items():
        parsed = Path(internal)
        extension = parsed.suffix.lstrip(".") or " "
        directory = parsed.parent.as_posix() if parsed.parent.as_posix() != "." else " "
        grouped.setdefault(extension, {}).setdefault(directory, []).append((parsed.stem, payload))
    offset = 0
    data = bytearray()
    for extension, directories in grouped.items():
        tree.extend(extension.encode() + b"\0")
        for directory, files in directories.items():
            tree.extend(directory.encode() + b"\0")
            for filename, payload in files:
                tree.extend(filename.encode() + b"\0")
                tree.extend(struct.pack("<IHHIIH", 0, 0, 0x7FFF, offset, len(payload), 0xFFFF))
                data.extend(payload)
                offset += len(payload)
            tree.extend(b"\0")
        tree.extend(b"\0")
    tree.extend(b"\0")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<III", VPK_SIGNATURE, 1, len(tree)) + tree + data)
    return path
