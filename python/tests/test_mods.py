from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_asset, write_vpk
from deadlock_sound_studio.database import Database
from deadlock_sound_studio.errors import StudioError
from deadlock_sound_studio.mods import (
    compare_mod_packages,
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

    # Both kinds are named now, but still unverifiable: the indexer skips them.
    assert report.counts_by_kind() == {"ui": 1, "model": 1}
    assert len(report.unchecked) == 2
    assert report.missing == []
    assert report.matched == []


def test_panorama_files_share_one_ui_kind(tmp_path: Path, database: Database):
    """A HUD mod ships markup, styles and script together. Reporting three
    separate kinds tells the player nothing they can act on; "3 HUD files"
    does."""
    package = write_vpk(
        tmp_path / "better_hud.vpk",
        {
            "panorama/layout/hud/element_gun.vxml_c": b"markup",
            "panorama/styles/ability_hud_elements/element_gun.vcss_c": b"styles",
            "panorama/scripts/hud.vjs_c": b"script",
        },
    )

    report = inspect_mod_package(package, database)

    assert report.counts_by_kind() == {"ui": 3}


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
    assert report.conflicts[0].mod_ids == ["alpha.vpk", "beta.vpk"]


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
    assert report.mod_conflicts == []


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


# --- mod-manager aware conflicts -------------------------------------------


def write_dmm_state(addons: Path, mods: dict) -> None:
    (addons / ".dmm.json").write_text(
        json.dumps({"version": 1, "mods": mods}), encoding="utf-8"
    )


def test_disabled_mods_cannot_conflict(tmp_path: Path):
    """A mod switched off in the manager stays on disk but is never mounted."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "pak01_dir.vpk", {"panorama/styles/hud.vcss_c": b"a"})
    write_vpk(addons / "999_pak01_dir.vpk", {"panorama/styles/hud.vcss_c": b"b"})
    write_dmm_state(
        addons,
        {
            "111": {"enabled": True, "currentVpks": ["pak01_dir.vpk"], "disabledVpks": []},
            "999": {"enabled": False, "currentVpks": [], "disabledVpks": ["999_pak01_dir.vpk"]},
        },
    )

    report = find_addon_conflicts(addons)

    assert report.uses_mod_manager is True
    assert len(report.disabled_packages) == 1
    assert report.conflicts == []


def test_two_packages_from_one_mod_are_not_a_conflict(tmp_path: Path):
    """Mods often ship as several VPKs; overlap between them is the author's."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "pak03_dir.vpk", {"panorama/scripts/hud.vjs_c": b"a"})
    write_vpk(addons / "pak04_dir.vpk", {"panorama/scripts/hud.vjs_c": b"b"})
    write_dmm_state(
        addons,
        {
            "637275": {
                "enabled": True,
                "currentVpks": ["pak03_dir.vpk", "pak04_dir.vpk"],
                "disabledVpks": [],
            }
        },
    )

    report = find_addon_conflicts(addons)

    assert report.conflicts == []
    assert report.mod_conflicts == []


def test_files_the_game_does_not_load_are_kept_separate(tmp_path: Path):
    """Nearly every mod bundles a readme; those collide constantly and mean nothing."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "one.vpk", {"readme.txt": b"a", "sounds/hit.vsnd_c": b"a"})
    write_vpk(addons / "two.vpk", {"readme.txt": b"b", "sounds/hit.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert [conflict.path for conflict in report.conflicts] == ["sounds/hit.vsnd_c"]
    assert [conflict.path for conflict in report.other_overlaps] == ["readme.txt"]


def test_conflicts_are_grouped_by_the_mods_involved(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "a.vpk", {"sounds/one.vsnd_c": b"a", "sounds/two.vsnd_c": b"a"})
    write_vpk(addons / "b.vpk", {"sounds/one.vsnd_c": b"b", "sounds/two.vsnd_c": b"b"})
    write_vpk(addons / "c.vpk", {"sounds/three.vsnd_c": b"c"})

    report = find_addon_conflicts(addons)

    assert len(report.mod_conflicts) == 1
    pair = report.mod_conflicts[0]
    assert pair.mod_ids == ["a.vpk", "b.vpk"]
    assert pair.path_count == 2
    assert pair.example_paths == ["sounds/one.vsnd_c", "sounds/two.vsnd_c"]


def test_folder_without_a_manager_treats_each_package_as_its_own_mod(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "one.vpk", {"sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "two.vpk", {"sounds/a.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert report.uses_mod_manager is False
    assert report.conflicts[0].mod_ids == ["one.vpk", "two.vpk"]


def test_an_unparsable_manager_file_does_not_break_the_scan(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "one.vpk", {"sounds/a.vsnd_c": b"a"})
    (addons / ".dmm.json").write_text("{not json", encoding="utf-8")

    report = find_addon_conflicts(addons)

    assert report.uses_mod_manager is False
    assert len(report.packages) == 1


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


# --- comparing two mods -----------------------------------------------------


def test_comparison_flags_a_shared_model_as_unmergeable(tmp_path: Path):
    """A hero and their weapon share one .vmdl_c, so a model collision cannot
    be resolved by choosing files: the winner brings its whole mesh."""
    skin = write_vpk(
        tmp_path / "skin.vpk",
        {
            "models/heroes/vindicta/hornet.vmdl_c": b"skin-mesh",
            "models/heroes/vindicta/materials/body.vmat_c": b"skin-body",
        },
    )
    gun = write_vpk(
        tmp_path / "gun.vpk",
        {
            "models/heroes/vindicta/hornet.vmdl_c": b"gun-mesh",
            "models/heroes/vindicta/materials/gun.vmat_c": b"gun-mat",
        },
    )

    report = compare_mod_packages([skin, gun])

    assert report.mergeable is False
    assert [blocker.path for blocker in report.blockers] == [
        "models/heroes/vindicta/hornet.vmdl_c"
    ]
    assert report.blockers[0].kind == "model"
    # The blocking collision is listed first so it cannot be missed.
    assert report.shared[0].inseparable is True


def test_comparison_flags_a_shared_stylesheet_as_unmergeable(tmp_path: Path):
    """One Panorama stylesheet covers a whole screen region: element_gun.vcss_c
    holds the crosshair rules *and* the hit marker rules. A crosshair mod and a
    hit marker mod therefore collide on that single path, and the winner takes
    both - which is not something picking files can fix."""
    stylesheet = "panorama/styles/ability_hud_elements/element_gun.vcss_c"
    crosshair = write_vpk(tmp_path / "crosshair.vpk", {stylesheet: b"crosshair"})
    hitmarker = write_vpk(tmp_path / "hitmarker.vpk", {stylesheet: b"hitmarker"})

    report = compare_mod_packages([crosshair, hitmarker])

    assert report.mergeable is False
    assert [blocker.path for blocker in report.blockers] == [stylesheet]
    assert report.blockers[0].kind == "ui"


def test_comparison_allows_merging_when_only_materials_collide(tmp_path: Path):
    first = write_vpk(
        tmp_path / "a.vpk",
        {"models/x/materials/gun.vmat_c": b"a", "models/x/a.vtex_c": b"a"},
    )
    second = write_vpk(
        tmp_path / "b.vpk",
        {"models/x/materials/gun.vmat_c": b"b", "models/x/b.vtex_c": b"b"},
    )

    report = compare_mod_packages([first, second])

    assert report.mergeable is True
    assert report.counts_by_kind() == {"material": 1}
    assert [package.unique_count for package in report.packages] == [1, 1]


def test_comparison_reports_unique_paths_per_package(tmp_path: Path):
    first = write_vpk(tmp_path / "a.vpk", {"a.vsnd_c": b"a", "shared.vsnd_c": b"a"})
    second = write_vpk(tmp_path / "b.vpk", {"b.vsnd_c": b"b", "shared.vsnd_c": b"b"})

    report = compare_mod_packages([first, second])

    assert [package.entry_count for package in report.packages] == [2, 2]
    assert [package.unique_count for package in report.packages] == [1, 1]
    assert len(report.shared) == 1


def test_comparison_needs_two_different_packages(tmp_path: Path):
    only = write_vpk(tmp_path / "a.vpk", {"a.vsnd_c": b"a"})

    with pytest.raises(StudioError):
        compare_mod_packages([only])
    with pytest.raises(StudioError) as error:
        compare_mod_packages([only, only])
    assert "two different" in error.value.message


# --- reference-aware comparison ---------------------------------------------


def make_model(*material_paths: str) -> bytes:
    """A stand-in compiled model: references are null-terminated strings."""
    body = b"\x00".join(path.encode("ascii") for path in material_paths)
    return b"MDLHEADER\x00" + body + b"\x00\x00binary-payload"


def test_extracted_references_drop_the_compiled_suffix():
    from deadlock_sound_studio.mods.references import extract_references, references_materials

    data = make_model("models/x/materials/body.vmat", "models/x/body_color.vtex")
    assert extract_references(data) == [
        "models/x/body_color.vtex",
        "models/x/materials/body.vmat",
    ]
    # Materials are returned as the compiled path a VPK actually stores.
    assert references_materials(data) == ["models/x/materials/body.vmat_c"]


def test_bare_filenames_and_partial_strings_are_not_references():
    from deadlock_sound_studio.mods.references import extract_references

    # No directory separator, and a fragment of a longer path.
    assert extract_references(make_model("body.vmat", "s/x.vmat")) == ["s/x.vmat"]
    assert extract_references(b"no strings here at all") == []


def test_a_model_that_ignores_the_other_mods_materials_is_flagged(tmp_path: Path):
    """The case that a path comparison alone cannot see: no shared paths, yet
    the retexture never applies because the replaced model looks elsewhere."""
    skin = write_vpk(
        tmp_path / "retexture.vpk",
        {"models/hero/vindicta/materials/body.vmat_c": b"dark"},
    )
    gun = write_vpk(
        tmp_path / "model_mod.vpk",
        {
            "models/hero/hornet/hornet.vmdl_c": make_model(
                "models/hero/hornet/materials/body.vmat"
            ),
            "models/hero/hornet/materials/body.vmat_c": b"awp",
        },
    )

    report = compare_mod_packages([skin, gun])

    assert report.shared == []            # nothing collides
    assert report.mergeable is False      # but they still will not both apply
    assert len(report.reference_warnings) == 1
    warning = report.reference_warnings[0]
    assert warning.supplier_package == "retexture.vpk"
    assert warning.model_package == "model_mod.vpk"
    assert warning.unreferenced_count == 1


def test_no_warning_when_the_model_does_reference_them(tmp_path: Path):
    skin = write_vpk(
        tmp_path / "retexture.vpk",
        {"models/hero/shared/materials/body.vmat_c": b"dark"},
    )
    gun = write_vpk(
        tmp_path / "model_mod.vpk",
        {
            "models/hero/hornet/hornet.vmdl_c": make_model(
                "models/hero/shared/materials/body.vmat"
            )
        },
    )

    report = compare_mod_packages([skin, gun])

    assert report.reference_warnings == []
    assert report.mergeable is True


def test_an_unused_spare_model_cannot_vouch_for_the_live_one(tmp_path: Path):
    """Authors leave *_backup.vmdl_c files in packages. Pooling a package's
    models would let a dead file hide the problem, so each is checked alone."""
    skin = write_vpk(tmp_path / "retexture.vpk", {"models/old/materials/body.vmat_c": b"d"})
    gun = write_vpk(
        tmp_path / "model_mod.vpk",
        {
            "models/hero/hornet.vmdl_c": make_model("models/new/materials/body.vmat"),
            "models/hero/hornet_backup.vmdl_c": make_model("models/old/materials/body.vmat"),
        },
    )

    report = compare_mod_packages([skin, gun])

    assert len(report.reference_warnings) == 1
    assert report.reference_warnings[0].model_path == "models/hero/hornet.vmdl_c"


def test_suggested_renames_match_on_filename_only(tmp_path: Path):
    """Conservative on purpose: body maps to body, head is left alone when the
    model wants headv2, because that rename is a guess about intent."""
    skin = write_vpk(
        tmp_path / "skin.vpk",
        {
            "models/old/materials/body.vmat_c": b"d",
            "models/old/materials/head.vmat_c": b"d",
        },
    )
    model_mod = write_vpk(
        tmp_path / "model.vpk",
        {
            "models/new/hero.vmdl_c": make_model(
                "models/new/materials/body.vmat", "models/new/materials/headv2.vmat"
            )
        },
    )

    warning = compare_mod_packages([skin, model_mod]).reference_warnings[0]

    assert warning.suggested_renames == [
        ("models/old/materials/body.vmat_c", "models/new/materials/body.vmat_c")
    ]
    assert warning.unmatched == ["models/old/materials/head.vmat_c"]


def test_mod_names_are_read_from_the_manager_catalogue(tmp_path: Path):
    """The folder records carry ids only; titles live in the manager's own file."""
    from deadlock_sound_studio.mods.conflicts import read_mod_names

    catalogue = tmp_path / "state.json"
    catalogue.write_text(
        json.dumps(
            {
                "local-config": json.dumps(
                    {
                        "state": {
                            "localMods": [
                                {"remoteId": 650634, "id": "mod_abc", "name": "QOL Lock"},
                                {"id": "local-xyz", "name": "First Blood Sound"},
                                {"id": "no-name-mod"},
                            ]
                        }
                    }
                )
            }
        ),
        encoding="utf-8",
    )

    names = read_mod_names(catalogue)

    # Keyed by both ids, because folder records reference whichever applies.
    assert names["650634"] == "QOL Lock"
    assert names["mod_abc"] == "QOL Lock"
    assert names["local-xyz"] == "First Blood Sound"
    assert "no-name-mod" not in names


def test_a_missing_or_broken_catalogue_is_not_fatal(tmp_path: Path):
    from deadlock_sound_studio.mods.conflicts import read_mod_names

    assert read_mod_names(tmp_path / "absent.json") == {}
    broken = tmp_path / "state.json"
    broken.write_text("{not json", encoding="utf-8")
    assert read_mod_names(broken) == {}


# --- merging non-conflicting mods -------------------------------------------


def test_packages_sharing_no_loaded_file_are_offered_for_merging(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "a.vpk", {"sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "b.vpk", {"sounds/b.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert [package.path.name for package in report.mergeable] == ["a.vpk", "b.vpk"]


def test_same_mod_packages_that_overlap_are_not_mergeable(tmp_path: Path):
    """The mod-level conflict view hides same-author overlap because a player
    cannot act on it. Merging is per file, so that overlap would lose data and
    must still hold both packages back."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "pak03_dir.vpk", {"panorama/scripts/hud.vjs_c": b"a"})
    write_vpk(addons / "pak04_dir.vpk", {"panorama/scripts/hud.vjs_c": b"b"})
    write_vpk(addons / "pak05_dir.vpk", {"sounds/alone.vsnd_c": b"c"})
    write_dmm_state(
        addons,
        {
            "1": {
                "enabled": True,
                "currentVpks": ["pak03_dir.vpk", "pak04_dir.vpk"],
                "disabledVpks": [],
            },
            "2": {"enabled": True, "currentVpks": ["pak05_dir.vpk"], "disabledVpks": []},
        },
    )

    report = find_addon_conflicts(addons)

    assert report.conflicts == []  # same mod, so not a conflict...
    # ...but still unsafe to merge, so only the untouched package is offered.
    assert [package.path.name for package in report.mergeable] == ["pak05_dir.vpk"]


def test_a_shared_readme_does_not_block_merging(tmp_path: Path):
    """Nearly every mod bundles one; treating it as an overlap would rule out
    almost every package for no benefit."""
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "a.vpk", {"readme.txt": b"a", "sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "b.vpk", {"readme.txt": b"b", "sounds/b.vsnd_c": b"b"})

    report = find_addon_conflicts(addons)

    assert len(report.mergeable) == 2
    assert len(report.other_overlaps) == 1


def test_disabled_and_unreadable_packages_are_never_offered(tmp_path: Path):
    addons = tmp_path / "addons"
    addons.mkdir()
    write_vpk(addons / "live.vpk", {"sounds/a.vsnd_c": b"a"})
    write_vpk(addons / "off.vpk", {"sounds/b.vsnd_c": b"b"})
    (addons / "corrupt.vpk").write_bytes(b"not a vpk")
    write_dmm_state(
        addons,
        {
            "1": {"enabled": True, "currentVpks": ["live.vpk"], "disabledVpks": []},
            "2": {"enabled": False, "currentVpks": [], "disabledVpks": ["off.vpk"]},
        },
    )

    report = find_addon_conflicts(addons)

    assert [package.path.name for package in report.mergeable] == ["live.vpk"]
