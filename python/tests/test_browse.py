"""Folder browsing for the sound and visual catalogs.

The game ships ~79,000 sounds in ~740 folders, so a flat listing has to
truncate. Browsing by folder does not: the caller takes the skeleton once, then
asks for one folder's files at a time, and a folder is its own limit.
"""

from __future__ import annotations

from pathlib import Path

from conftest import make_asset
from deadlock_sound_studio.database import Database
from deadlock_sound_studio.database.store import folder_of
from deadlock_sound_studio.models import (
    VisualResourceAsset,
    VisualResourceKind,
    utc_now,
)
from deadlock_sound_studio.protocol.router import BackendRouter

TREE = [
    "sounds/vo/hero_one/attack.vsnd_c",
    "sounds/vo/hero_one/death.vsnd_c",
    "sounds/vo/hero_one/lines/taunt.vsnd_c",
    "sounds/vo/hero_two/attack.vsnd_c",
    "sounds/ui/accept.vsnd_c",
    "loose.vsnd_c",
]


def make_visual(internal_path: str, kind: VisualResourceKind) -> VisualResourceAsset:
    return VisualResourceAsset(
        id=internal_path.casefold(),
        internal_path=internal_path,
        compiled_path=internal_path,
        filename=Path(internal_path).name,
        kind=kind,
        source_archive="pak01_dir.vpk",
        archive_fingerprint="archive",
        asset_fingerprint="abc",
        stored_size=10,
        last_indexed_at=utc_now(),
    )


def test_folder_of_handles_roots_and_nesting():
    assert folder_of("sounds/vo/hero_one/attack.vsnd_c") == "sounds/vo/hero_one"
    assert folder_of("loose.vsnd_c") == ""


def test_folder_skeleton_counts_only_direct_files(database: Database):
    database.upsert_assets([make_asset(path) for path in TREE])

    folders = database.list_sound_folders()

    # "sounds/vo" holds no file of its own, so it is absent: the caller rebuilds
    # intermediate folders from the path segments.
    assert folders == [
        {"folder": "", "fileCount": 1},
        {"folder": "sounds/ui", "fileCount": 1},
        {"folder": "sounds/vo/hero_one", "fileCount": 2},
        {"folder": "sounds/vo/hero_one/lines", "fileCount": 1},
        {"folder": "sounds/vo/hero_two", "fileCount": 1},
    ]


def test_browsing_a_folder_excludes_subfolders(database: Database):
    database.upsert_assets([make_asset(path) for path in TREE])

    listing = database.sound_assets_in_folder("sounds/vo/hero_one")

    # lines/taunt.vsnd_c lives one level deeper and must not appear here.
    assert [asset.internal_path for asset in listing] == [
        "sounds/vo/hero_one/attack.vsnd_c",
        "sounds/vo/hero_one/death.vsnd_c",
    ]


def test_browsing_a_parent_folder_that_holds_nothing(database: Database):
    database.upsert_assets([make_asset(path) for path in TREE])

    assert database.sound_assets_in_folder("sounds/vo") == []


def test_browsing_the_root_returns_only_loose_files(database: Database):
    database.upsert_assets([make_asset(path) for path in TREE])

    listing = database.sound_assets_in_folder("")

    assert [asset.internal_path for asset in listing] == ["loose.vsnd_c"]


def test_underscores_in_a_folder_name_do_not_match_a_sibling(database: Database):
    """``_`` is a LIKE wildcard and game paths are full of underscores. A LIKE
    query for ``hero_one/%`` also matches ``heroXone/``, quietly listing another
    folder's files. The range comparison used instead cannot do that."""
    database.upsert_assets(
        [
            make_asset("sounds/vo/hero_one/attack.vsnd_c"),
            make_asset("sounds/vo/heroXone/leaked.vsnd_c"),
        ]
    )

    listing = database.sound_assets_in_folder("sounds/vo/hero_one")

    assert [asset.internal_path for asset in listing] == [
        "sounds/vo/hero_one/attack.vsnd_c"
    ]


def test_browsing_respects_the_same_filters_as_search(database: Database):
    """Counts on the tree have to describe the same set the search box would
    return, or the tree says one thing and the results another."""
    database.upsert_assets(
        [
            make_asset("sounds/vo/hero_one/attack.vsnd_c", hero_name="Abrams"),
            make_asset("sounds/vo/hero_one/generic.vsnd_c"),
        ]
    )

    assert database.list_sound_folders(scope="heroes") == [
        {"folder": "sounds/vo/hero_one", "fileCount": 1}
    ]
    listing = database.sound_assets_in_folder("sounds/vo/hero_one", scope="heroes")
    assert [asset.internal_path for asset in listing] == [
        "sounds/vo/hero_one/attack.vsnd_c"
    ]


def test_browse_methods_are_reachable_over_the_protocol(paths):
    """The allowlist in apps/electron/python-worker.ts has to name exactly what
    the router registers; a method missing from either side is invisible until
    someone clicks the thing. Dispatch the real names."""
    router = BackendRouter(paths, lambda _event: None)
    try:
        router.database.upsert_assets([make_asset(path) for path in TREE])

        folders = router.dispatch("sounds.folders", {})
        assert {"folder": "sounds/vo/hero_one", "fileCount": 2} in folders

        listing = router.dispatch("sounds.browse", {"folder": "sounds/vo/hero_one"})
        assert [entry["internalPath"] for entry in listing] == [
            "sounds/vo/hero_one/attack.vsnd_c",
            "sounds/vo/hero_one/death.vsnd_c",
        ]

        assert router.dispatch("visuals.folders", {}) == []
        assert router.dispatch("visuals.browse", {"folder": "models"}) == []
    finally:
        router.close()


def test_visual_browsing_splits_by_kind(database: Database):
    database.upsert_visual_assets(
        [
            make_visual("models/hero/body_color.vtex_c", VisualResourceKind.TEXTURE),
            make_visual("models/hero/body.vmat_c", VisualResourceKind.MATERIAL),
            make_visual("models/hero/deep/nested.vtex_c", VisualResourceKind.TEXTURE),
        ]
    )

    assert database.list_visual_folders("texture") == [
        {"folder": "models/hero", "fileCount": 1},
        {"folder": "models/hero/deep", "fileCount": 1},
    ]
    listing = database.visual_assets_in_folder("models/hero", "material")
    assert [asset.internal_path for asset in listing] == ["models/hero/body.vmat_c"]
