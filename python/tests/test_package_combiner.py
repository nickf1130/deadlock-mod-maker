from __future__ import annotations

import struct
import zipfile
from pathlib import Path
from typing import Any

import pytest

from conftest import write_vpk
from deadlock_sound_studio.errors import StudioError
from deadlock_sound_studio.packages import RenameRule, combine_packages, inspect_packages
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


SOURCE2_ASSET_URL = (
    "https://github.com/ValveResourceFormat/ValveResourceFormat"
    "/releases/download/19.2/Source2Viewer.exe"
)


def test_trusted_asset_url_accepts_the_publisher_release_download():
    requirements._assert_trusted_asset_url(
        SOURCE2_ASSET_URL,
        requirements.SOURCE2_REPOSITORY,
        "Source2Viewer.exe",
    )


@pytest.mark.parametrize(
    "url",
    [
        # Plain HTTP, even on the right host.
        SOURCE2_ASSET_URL.replace("https://", "http://"),
        # A lookalike host, and a host smuggled into the userinfo field.
        SOURCE2_ASSET_URL.replace("github.com", "github.com.evil.invalid"),
        SOURCE2_ASSET_URL.replace("github.com", "github.com@evil.invalid"),
        # The right host, but another repository's release.
        SOURCE2_ASSET_URL.replace(
            "ValveResourceFormat/ValveResourceFormat", "attacker/payload"
        ),
        # The right release, but a different file than the one requested.
        SOURCE2_ASSET_URL.replace("Source2Viewer.exe", "payload.exe"),
    ],
)
def test_trusted_asset_url_rejects_urls_off_the_publisher_release(url: str):
    with pytest.raises(Exception, match="does not point at"):
        requirements._assert_trusted_asset_url(
            url, requirements.SOURCE2_REPOSITORY, "Source2Viewer.exe"
        )


@pytest.mark.parametrize(
    "digest",
    [None, "", "md5:abc", "sha256:not-a-digest", "sha256:" + "a" * 63],
)
def test_expected_sha256_refuses_assets_without_a_usable_digest(digest):
    with pytest.raises(Exception, match="SHA-256"):
        requirements._expected_sha256(
            {"digest": digest}, "Source2Viewer.exe"
        )


def test_expected_sha256_returns_the_published_digest():
    assert (
        requirements._expected_sha256(
            {"digest": "sha256:" + "A" * 64}, "Source2Viewer.exe"
        )
        == "a" * 64
    )


def test_download_asset_rejects_bad_metadata_before_any_network_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("the download must not start")

    monkeypatch.setattr(requirements.urllib.request, "urlopen", fail_if_called)
    destination = tmp_path / "Source2Viewer.exe"

    # An untrusted URL is refused even when a digest is present.
    with pytest.raises(Exception, match="does not point at"):
        requirements._download_asset(
            {
                "name": "Source2Viewer.exe",
                "browser_download_url": "https://evil.invalid/Source2Viewer.exe",
                "digest": "sha256:" + "a" * 64,
            },
            destination,
            0,
            1,
            None,
            requirements.SOURCE2_REPOSITORY,
        )

    # A trusted URL with no digest is refused rather than installed on trust.
    with pytest.raises(Exception, match="SHA-256"):
        requirements._download_asset(
            {
                "name": "Source2Viewer.exe",
                "browser_download_url": SOURCE2_ASSET_URL,
            },
            destination,
            0,
            1,
            None,
            requirements.SOURCE2_REPOSITORY,
        )

    assert not destination.exists()


def test_download_asset_discards_a_file_that_fails_its_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    payload = b"tampered-installer"

    class FakeResponse:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self) -> None:
            self._body = payload

        def read(self, _size: int) -> bytes:
            block, self._body = self._body, b""
            return block

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(
        requirements.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse()
    )
    destination = tmp_path / "Source2Viewer.exe"

    with pytest.raises(Exception, match="did not match"):
        requirements._download_asset(
            {
                "name": "Source2Viewer.exe",
                "browser_download_url": SOURCE2_ASSET_URL,
                # A valid digest that this payload does not hash to.
                "digest": "sha256:" + "b" * 64,
            },
            destination,
            0,
            1,
            None,
            requirements.SOURCE2_REPOSITORY,
        )

    assert not destination.exists()


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
            "browser_download_url": (
                "https://github.com/ValveResourceFormat/ValveResourceFormat"
                "/releases/download/19.2/Source2Viewer.exe"
            ),
        },
        "cli-windows-x64.zip": {
            "name": "cli-windows-x64.zip",
            "browser_download_url": (
                "https://github.com/ValveResourceFormat/ValveResourceFormat"
                "/releases/download/19.2/cli-windows-x64.zip"
            ),
        },
        "ffmpeg-master-latest-win64-gpl-shared.zip": {
            "name": "ffmpeg-master-latest-win64-gpl-shared.zip",
            "browser_download_url": (
                "https://github.com/BtbN/FFmpeg-Builds/releases/download"
                "/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
            ),
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
        _repository: str,
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


# --- rename on merge --------------------------------------------------------


def test_rename_writes_an_entry_at_a_different_path(tmp_path: Path):
    """Two mods can supply the same thing at different paths; a redirect lets
    the retexture land where the model that should use it actually reads."""
    model_mod = write_vpk(
        tmp_path / "model.vpk",
        {
            "models/hornet/hornet.vmdl_c": b"mesh",
            "models/hornet/materials/body.vmat_c": b"model-body",
        },
    )
    retexture = write_vpk(
        tmp_path / "skin.vpk",
        {"models/vindicta/materials/body.vmat_c": b"skin-body"},
    )

    output = tmp_path / "merged.vpk"
    result = combine_packages(
        [model_mod, retexture],
        output,
        None,
        [
            RenameRule(
                package="skin.vpk",
                source="models/vindicta/materials/body.vmat_c",
                target="models/hornet/materials/body.vmat_c",
            )
        ],
    )

    assert result["renamedCount"] == 1
    entries = {entry.path: entry for entry in list_vpk(output)}
    # The redirected file replaced the model mod's own material...
    assert set(entries) == {
        "models/hornet/hornet.vmdl_c",
        "models/hornet/materials/body.vmat_c",
    }
    assert read_vpk_entry(output, entries["models/hornet/materials/body.vmat_c"]) == b"skin-body"
    # ...and the original path is gone: a rename moves, it does not duplicate.
    assert "models/vindicta/materials/body.vmat_c" not in entries


def test_a_renamed_entry_takes_part_in_precedence(tmp_path: Path):
    """Order still decides: the redirect only wins because it comes last."""
    first = write_vpk(tmp_path / "first.vpk", {"target.vsnd_c": b"first"})
    second = write_vpk(tmp_path / "second.vpk", {"source.vsnd_c": b"second"})

    output = tmp_path / "merged.vpk"
    result = combine_packages(
        [first, second],
        output,
        None,
        [RenameRule(package="second.vpk", source="source.vsnd_c", target="target.vsnd_c")],
    )

    assert result["conflictCount"] == 1
    entries = {entry.path: entry for entry in list_vpk(output)}
    assert read_vpk_entry(output, entries["target.vsnd_c"]) == b"second"


def test_rename_rules_that_cannot_apply_are_rejected(tmp_path: Path):
    package = write_vpk(tmp_path / "a.vpk", {"real.vsnd_c": b"a"})
    other = write_vpk(tmp_path / "b.vpk", {"other.vsnd_c": b"b"})
    output = tmp_path / "merged.vpk"

    with pytest.raises(StudioError) as missing_file:
        combine_packages(
            [package, other],
            output,
            None,
            [RenameRule(package="a.vpk", source="absent.vsnd_c", target="x.vsnd_c")],
        )
    assert "not in that package" in missing_file.value.message

    with pytest.raises(StudioError) as missing_package:
        combine_packages(
            [package, other],
            output,
            None,
            [RenameRule(package="nope.vpk", source="real.vsnd_c", target="x.vsnd_c")],
        )
    assert "not being combined" in missing_package.value.message
