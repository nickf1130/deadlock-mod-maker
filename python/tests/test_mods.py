from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_asset, write_vpk
from deadlock_sound_studio.database import Database
from deadlock_sound_studio.errors import StudioError
from deadlock_sound_studio.mods import (
    find_addon_conflicts,
    inspect_mod_package,
    suggest_project_name,
)
from deadlock_sound_studio.models import (
    VisualResourceAsset,
    VisualResourceKind,
    utc_now,
)


def make_visual(internal_path: str) -> VisualResourceAsset:
    return VisualResourceAsset(
        id=internal_path.casefold(),
        internal_path=internal_path,
        compiled_path=internal_path,
        filename=Path(internal_path).name,
        kind=VisualResourceKind.TEXTURE,
        source_archive="pak01_dir.vpk",
        archive_fingerprint="archive",
        asset_fingerprint="abc",
        stored_size=10,
        last_indexed_at=utc_now(),
    )


# --- inspecting a downloaded mod -------------------------------------------


def test_inspect_reports_which_entries_still_match_the_game(
    tmp_path: Path, database: Database
):
    database.upsert_assets([make_asset("sounds/abrams/cast.vsnd_c", hero_name="Abrams")])
    database.upsert_visual_assets([make_visual("materials/abrams/skin.vtex_c")])

    package = write_vpk(
        tmp_path / "abrams_pack.vpk",
        {
            "sounds/abrams/cast.vsnd_c": b"replacement",
            "materials/abrams/skin.vtex_c": b"replacement",
            "sounds/abrams/removed_by_patch.vsnd_c": b"stale",
        },
    )

    report = inspect_mod_package(package, database)

    assert len(report.entries) == 3
    assert [entry.path for entry in report.matched] == [
        "materials/abrams/skin.vtex_c",
        "sounds/abrams/cast.vsnd_c",
    ]
    # The entry the game no longer ships is the actionable finding.
    assert [entry.path for entry in report.missing] == [
        "sounds/abrams/removed_by_patch.vsnd_c"
    ]
    assert report.unchecked == []
    assert report.counts_by_kind() == {"sound": 2, "texture": 1}
    assert report.heroes == ["Abrams"]


def test_unindexed_kinds_are_unchecked_rather_than_missing(
    tmp_path: Path, database: Database
):
    """Panorama and model paths are absent from the catalog because the indexer
    skips them, not because the game dropped them. Calling those "missing"
    would report working mods as broken."""
    package = write_vpk(
        tmp_path / "hud.vpk",
        {
            "panorama/layout/citadel_hud_top_bar.vxml_c": b"ui",
            "models/hero/body.vmdl_c": b"model",
        },
    )

    report = inspect_mod_package(package, database)

    assert report.counts_by_kind() == {"other": 2}
    assert len(report.unchecked) == 2
    assert report.missing == []
    assert report.matched == []


def test_inspect_rejects_files_that_are_not_packages(tmp_path: Path, database: Database):
    not_a_package = tmp_path / "readme.txt"
    not_a_package.write_text("hello", encoding="utf-8")

    with pytest.raises(StudioError) as error:
        inspect_mod_package(not_a_package, database)
    assert error.value.code == "VALIDATION_FAILED"


def test_inspect_rejects_a_missing_file(tmp_path: Path, database: Database):
    with pytest.raises(StudioError):
        inspect_mod_package(tmp_path / "absent.vpk", database)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("abrams_voice_pack.vpk", "Abrams Voice Pack"),
        ("cool-skin.vpk", "Cool Skin"),
        ("mod.vpk", "Mod"),
    ],
)
def test_suggested_project_name_is_human_readable(filename: str, expected: str):
    assert suggest_project_name(Path(filename)) == expected


# --- conflicts between installed mods ---------------------------------------


def test_conflicts_report_packages_claiming_the_same_path(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "alpha.vpk", {"sounds/ui/click.vsnd_c": b"a", "sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "beta.vpk", {"sounds/ui/click.vsnd_c": b"b", "sounds/b.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert len(report.packages) == 2
    assert len(report.conflicts) == 1
    assert report.conflicts[0].path == "sounds/ui/click.vsnd_c"
    assert report.conflicts[0].filenames == ["alpha.vpk", "beta.vpk"]
    assert report.conflicting_filenames == ["alpha.vpk", "beta.vpk"]


def test_conflicts_compare_paths_case_insensitively(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "one.vpk", {"sounds/UI/Click.vsnd_c": b"a"})
    write_vpk(addons / "two.vpk", {"sounds/ui/click.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert len(report.conflicts) == 1


def test_no_conflicts_when_mods_touch_different_files(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "one.vpk", {"sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "two.vpk", {"sounds/b.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert report.conflicts == []
    assert report.conflicting_filenames == []


def test_unreadable_packages_are_reported_not_skipped(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "good.vpk", {"sounds/a.vsnd_c": b"a"})
    (addons / "corrupt.vpk").write_bytes(b"not a vpk at all")

    report = find_addon_conflicts(addons)

    assert len(report.packages) == 2
    assert len(report.unreadable) == 1
    assert report.unreadable[0].path.name == "corrupt.vpk"
    assert report.unreadable[0].error


def test_non_package_files_in_the_addons_folder_are_ignored(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "mod.vpk", {"sounds/a.vsnd_c": b"a"})
    (addons / "notes.txt").write_text("ignore me", encoding="utf-8")
    (addons / "nested").mkdir()

    report = find_addon_conflicts(addons)

    assert [package.path.name for package in report.packages] == ["mod.vpk"]


def test_missing_addons_folder_explains_itself(tmp_path: Path):
    with pytest.raises(StudioError) as error:
        find_addon_conflicts(tmp_path / "addons")
    assert error.value.code == "VALIDATION_FAILED"
    assert "does not exist" in error.value.message


def test_creating_a_project_with_a_taken_name_explains_itself(paths, database):
    """Suggested names come from mod filenames, so collisions are likely."""
    from deadlock_sound_studio.projects import ProjectService

    projects = ProjectService(paths, database)
    projects.create("Abrams Voice Pack")

    with pytest.raises(StudioError) as error:
        projects.create("abrams voice pack")

    assert error.value.code == "PROJECT_NAME_TAKEN"
    # The failed attempt must not leave an orphan folder behind.
    assert len(list(paths.projects.iterdir())) == 1
