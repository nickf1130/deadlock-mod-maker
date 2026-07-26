from __future__ import annotations

import struct
import zipfile
from pathlib import Path
from typing import Any

import pytest

from conftest import write_vpk
from deadlock_sound_studio.packages import combine_packages, inspect_packages
from deadlock_sound_studio.models import Settings
from deadlock_sound_studio.paths import AppPaths
from deadlock_sound_studio import requirements
from deadlock_sound_studio.vpk import VPK_SIGNATURE, list_vpk, read_vpk_entry


def test_inspect_and_combine_packages_with_lower_input_winning(tmp_path: Path):
    first = write_vpk(
        tmp_path / "first.vpk",
        {
            "sounds/common.vsnd_c": b"first-version",
            "sounds/only_first.vsnd_c": b"first",
        },
    )
    second = write_vpk(
        tmp_path / "second.pak",
        {
            "sounds/common.vsnd_c": b"second-version",
            "materials/only_second.vmat_c": b"second",
        },
    )

    inventories = inspect_packages([first, second])
    assert [value["entryCount"] for value in inventories] == [2, 2]
    assert inventories[1]["filename"] == "second.pak"
    assert {
        entry["path"] for entry in inventories[0]["entries"]
    } == {"sounds/common.vsnd_c", "sounds/only_first.vsnd_c"}

    events: list[dict[str, object]] = []
    output = tmp_path / "combined.vpk"
    result = combine_packages([first, second], output, events.append)

    assert result["entryCount"] == 3
    assert result["conflictCount"] == 1
    assert result["conflicts"] == [
        {
            "path": "sounds/common.vsnd_c",
            "replacedPackage": "first.vpk",
            "winnerPackage": "second.pak",
        }
    ]
    assert len(result["sha256"]) == 64
    combined_entries = {entry.path: entry for entry in list_vpk(output)}
    assert set(combined_entries) == {
        "materials/only_second.vmat_c",
        "sounds/common.vsnd_c",
        "sounds/only_first.vsnd_c",
    }
    assert (
        read_vpk_entry(output, combined_entries["sounds/common.vsnd_c"])
        == b"second-version"
    )
    assert events[-1]["stage"] == "complete"


def test_combiner_refuses_to_overwrite_an_input(tmp_path: Path):
    first = write_vpk(tmp_path / "first.vpk", {"one.txt": b"one"})
    second = write_vpk(tmp_path / "second.vpk", {"two.txt": b"two"})
    with pytest.raises(Exception, match="cannot overwrite"):
        combine_packages([first, second], first)


def test_combiner_preserves_preload_and_archive_payload_bytes(tmp_path: Path):
    tree = bytearray()
    tree.extend(b"txt\0 \0preloaded\0")
    tree.extend(struct.pack("<IHHIIH", 0, 3, 0x7FFF, 0, 4, 0xFFFF))
    tree.extend(b"pre")
    tree.extend(b"\0\0\0")
    first = tmp_path / "preload.vpk"
    first.write_bytes(struct.pack("<III", VPK_SIGNATURE, 1, len(tree)) + tree + b"data")
    second = write_vpk(tmp_path / "other.vpk", {"other.txt": b"other"})

    output = tmp_path / "combined.vpk"
    combine_packages([first, second], output)
    entries = {entry.path: entry for entry in list_vpk(output)}

    assert read_vpk_entry(output, entries["preloaded.txt"]) == b"predata"


def test_requirement_zip_extraction_rejects_parent_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside.exe", b"unsafe")

    with pytest.raises(Exception, match="unsafe path"):
        requirements._extract_zip(archive, tmp_path / "extract")
    assert not (tmp_path / "outside.exe").exists()


def test_requirement_zip_extraction_preserves_tool_files(tmp_path: Path):
    archive = tmp_path / "tools.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("release/bin/ffmpeg.exe", b"ffmpeg")
        output.writestr("release/bin/ffprobe.exe", b"ffprobe")
        output.writestr("release/bin/avcodec.dll", b"dll")

    destination = tmp_path / "extract"
    requirements._extract_zip(archive, destination)

    assert (destination / "release/bin/ffmpeg.exe").read_bytes() == b"ffmpeg"
    assert (destination / "release/bin/ffprobe.exe").read_bytes() == b"ffprobe"
    assert (destination / "release/bin/avcodec.dll").read_bytes() == b"dll"


def test_requirement_installer_places_and_verifies_all_downloadable_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = AppPaths.from_root(tmp_path / "app")
    events: list[dict[str, object]] = []
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: empty_home)
    assets = {
        "Source2Viewer.exe": {
            "name": "Source2Viewer.exe",
            "browser_download_url": "https://example.invalid/Source2Viewer.exe",
        },
        "cli-windows-x64.zip": {
            "name": "cli-windows-x64.zip",
            "browser_download_url": "https://example.invalid/cli.zip",
        },
        "ffmpeg-master-latest-win64-gpl-shared.zip": {
            "name": "ffmpeg-master-latest-win64-gpl-shared.zip",
            "browser_download_url": "https://example.invalid/ffmpeg.zip",
        },
    }

    monkeypatch.setattr(requirements, "_release_assets", lambda _url: assets)
    monkeypatch.setattr("platform.machine", lambda: "AMD64")

    def fake_download(
        asset: dict[str, object],
        destination: Path,
        _completed: int,
        _total: int,
        _progress,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        name = str(asset["name"])
        if name == "Source2Viewer.exe":
            destination.write_bytes(b"viewer")
        elif name == "cli-windows-x64.zip":
            with zipfile.ZipFile(destination, "w") as output:
                output.writestr("cli/Source2Viewer-CLI.exe", b"cli")
                output.writestr("cli/ValveResourceFormat.dll", b"dll")
        else:
            with zipfile.ZipFile(destination, "w") as output:
                output.writestr("ffmpeg/bin/ffmpeg.exe", b"ffmpeg")
                output.writestr("ffmpeg/bin/ffprobe.exe", b"ffprobe")
                output.writestr("ffmpeg/bin/avcodec.dll", b"dll")
        return destination

    monkeypatch.setattr(requirements, "_download_asset", fake_download)
    result: dict[str, Any] = requirements.install_missing_requirements(
        paths, Settings(), events.append
    )

    assert result["installed"] == [
        "Source 2 Viewer",
        "Source 2 Viewer CLI",
        "FFmpeg and FFprobe",
    ]
    assert (paths.tools / "Source2Viewer/Source2Viewer.exe").is_file()
    assert (paths.tools / "Source2Viewer/Source2Viewer-CLI.exe").is_file()
    assert (paths.tools / "Source2Viewer/ValveResourceFormat.dll").is_file()
    assert (paths.tools / "ffmpeg/ffmpeg.exe").is_file()
    assert (paths.tools / "ffmpeg/ffprobe.exe").is_file()
    assert (paths.tools / "ffmpeg/avcodec.dll").is_file()
    assert events[-1]["stage"] == "complete"
