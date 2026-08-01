"""Packages a mod manager has lost track of, and getting rid of them safely."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import write_vpk
from deadlock_sound_studio.errors import StudioError
from deadlock_sound_studio.mods import find_addon_conflicts, move_packages_to_backup
from deadlock_sound_studio.mods.conflicts import MOD_MANAGER_STATE_FILE


def write_manager_state(addons: Path, mods: dict[str, dict]) -> None:
    (addons / MOD_MANAGER_STATE_FILE).write_text(
        json.dumps({"mods": mods}), encoding="utf-8"
    )


def test_packages_the_manager_does_not_claim_are_reported(tmp_path: Path):
    """The real shape of the problem: switching a mod off renames its file, and
    the copy the game actually loads can be left behind under the old name. The
    manager then shows the mod as off while it is still very much on."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "pak01_dir.vpk", {"sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "554012_pak69_dir.vpk", {"sounds/b.vsnd_c": b"b"})
    write_vpk(addons / "pak69_dir.vpk", {"sounds/b.vsnd_c": b"b"})
    write_manager_state(
        addons,
        {
            "650634": {"enabled": True, "currentVpks": ["pak01_dir.vpk"]},
            "554012": {"enabled": False, "disabledVpks": ["554012_pak69_dir.vpk"]},
        },
    )

    report = find_addon_conflicts(addons)

    assert report.uses_mod_manager is True
    assert [package.path.name for package in report.untracked] == ["pak69_dir.vpk"]
    # A tracked-but-disabled package is not an orphan; the manager put it there.
    assert {package.path.name for package in report.packages if package.tracked} == {
        "pak01_dir.vpk",
        "554012_pak69_dir.vpk",
    }


def test_nothing_is_untracked_without_a_mod_manager(tmp_path: Path):
    """A hand-managed folder has no manager to lose track of anything, so
    flagging every package would be pure noise."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "pak01_dir.vpk", {"sounds/a.vsnd_c": b"a"})

    report = find_addon_conflicts(addons)

    assert report.uses_mod_manager is False
    assert report.untracked == []


def test_removal_moves_packages_instead_of_deleting_them(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    package = write_vpk(addons / "pak69_dir.vpk", {"sounds/b.vsnd_c": b"b"})
    backups = tmp_path / "backups"

    result = move_packages_to_backup([package], backups)

    assert not package.exists()
    assert len(result.moved) == 1
    moved = result.moved[0].backup_path
    assert moved.is_file()
    # Backups live outside the game folder, so Source 2 cannot mount them.
    assert backups in moved.parents


def test_removal_validates_everything_before_moving_anything(tmp_path: Path):
    """A cleanup that moved two of three files and then failed would leave the
    player worse off than not starting, with no obvious way to tell."""
    addons = tmp_path / "addons"
    addons.mkdir()
    good = write_vpk(addons / "pak69_dir.vpk", {"sounds/b.vsnd_c": b"b"})
    missing = addons / "pak70_dir.vpk"

    with pytest.raises(StudioError):
        move_packages_to_backup([good, missing], tmp_path / "backups")

    assert good.is_file()


def test_removal_refuses_files_that_are_not_packages(tmp_path: Path):
    readme = tmp_path / "readme.txt"
    readme.write_text("hello", encoding="utf-8")

    with pytest.raises(StudioError):
        move_packages_to_backup([readme], tmp_path / "backups")

    assert readme.is_file()


def test_two_packages_with_the_same_name_both_survive(tmp_path: Path):
    """Different mods ship identically named packages, and both may need
    removing in one go."""
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = write_vpk(first_dir / "pak69_dir.vpk", {"sounds/a.vsnd_c": b"a"})
    second = write_vpk(second_dir / "pak69_dir.vpk", {"sounds/b.vsnd_c": b"b"})

    result = move_packages_to_backup([first, second], tmp_path / "backups")

    backups = [item.backup_path for item in result.moved]
    assert len({path.name for path in backups}) == 2
    assert all(path.is_file() for path in backups)
