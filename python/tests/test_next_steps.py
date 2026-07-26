from __future__ import annotations

import csv
from pathlib import Path

from deadlock_sound_studio.build import (
    create_compatibility_copy,
    latest_compiled,
    write_item_logs,
)
from deadlock_sound_studio.models import (
    LoopSettings,
    ItemBuildResult,
    ItemStatus,
    ProcessingSettings,
    Settings,
    utc_now,
)
from deadlock_sound_studio.projects import ProjectService
from deadlock_sound_studio.protocol.router import BackendRouter
from deadlock_sound_studio.settings import save_settings

from conftest import make_asset, write_vpk, write_wav


def test_catalog_replacement_removes_assets_deleted_by_game_update(database):
    first = make_asset("sounds/ui/first.vsnd_c", id="first")
    removed = make_asset("sounds/ui/removed.vsnd_c", id="removed")
    database.upsert_assets([first, removed])
    database.upsert_assets([first], replace_catalog=True)
    assert database.count_assets() == 1
    assert database.get_asset("removed") is None


def test_sound_search_scopes_are_applied_before_the_result_limit(database):
    general = make_asset("sounds/ui/general.vsnd_c", id="general")
    hero = make_asset(
        "sounds/vo/hero_voice.vsnd_c",
        id="hero",
        hero_id="hero_01",
        hero_name="Hero One",
    )
    database.upsert_assets([general, hero])

    assert [asset.id for asset in database.search_assets(scope="all")] == [
        "general",
        "hero",
    ]
    assert [asset.id for asset in database.search_assets(scope="heroes")] == ["hero"]
    assert [asset.id for asset in database.search_assets(scope="general")] == [
        "general"
    ]


def test_catalog_snapshots_preserve_incremental_index_history(database):
    first = make_asset(
        "sounds/ui/first.vsnd_c",
        id="first",
        archive_fingerprint="archive-a",
        asset_fingerprint="1111",
    )
    initial = database.record_catalog_snapshot(
        [first], archive_fingerprint="archive-a", indexed_at=utc_now()
    )
    database.upsert_assets([first], replace_catalog=True)
    changed = make_asset(
        "sounds/ui/first.vsnd_c",
        id="first",
        archive_fingerprint="archive-b",
        asset_fingerprint="2222",
    )
    added = make_asset(
        "sounds/ui/second.vsnd_c",
        id="second",
        archive_fingerprint="archive-b",
        asset_fingerprint="3333",
    )
    delta = database.record_catalog_snapshot(
        [changed, added], archive_fingerprint="archive-b", indexed_at=utc_now()
    )
    database.upsert_assets([changed, added], replace_catalog=True)

    assert initial["added"] == 1
    assert delta["added"] == 1
    assert delta["changed"] == 1
    assert delta["removed"] == 0
    assert [
        entry["archiveFingerprint"] for entry in database.index_history()
    ] == ["archive-b", "archive-a"]


def test_project_target_remap_requires_an_explicit_asset_choice(
    paths, database, tmp_path: Path
):
    original = make_asset("sounds/ui/old.vsnd_c", id="old")
    relocated = make_asset(
        "sounds/ui/new.vsnd_c",
        id="new",
        archive_fingerprint="new-archive",
    )
    database.upsert_assets([original, relocated])
    service = ProjectService(paths, database)
    project = service.create("Remap Project")
    source = write_wav(tmp_path / "source.wav")
    project = service.confirm_replacement(
        project.id,
        original.id,
        source,
        ProcessingSettings(),
        LoopSettings(),
    )

    project = service.remap_target(
        project.id, project.target_assets[0].id, relocated.id
    )

    assert project.target_assets[0].target.id == relocated.id
    assert project.game_fingerprint == "new-archive"
    assert "explicit compatibility review" in project.target_assets[
        0
    ].validation_messages[-1]


def test_bootstrap_builds_first_run_index(paths):
    deadlock = paths.root / "fake-deadlock"
    archive = deadlock / "game/citadel/pak01_dir.vpk"
    write_vpk(archive, {"sounds/ui/first_run.vsnd_c": b"compiled"})
    save_settings(
        paths,
        Settings(deadlock_root_override=str(deadlock), setup_completed=True),
    )
    events: list[dict[str, object]] = []
    router = BackendRouter(paths, events.append)
    try:
        result = router.bootstrap({})
    finally:
        router.close()
    assert result["soundCount"] == 1
    assert result["autoIndex"]["attempted"] is True
    assert result["autoIndex"]["indexed"] == 1
    assert [
        event["stage"] for event in events if event["event"] == "index.progress"
    ] == ["readingArchive", "complete"]


def test_bootstrap_waits_for_setup_before_first_index(paths):
    deadlock = paths.root / "fake-deadlock"
    archive = deadlock / "game/citadel/pak01_dir.vpk"
    write_vpk(archive, {"sounds/ui/not_yet.vsnd_c": b"compiled"})
    save_settings(
        paths,
        Settings(deadlock_root_override=str(deadlock), setup_completed=False),
    )
    events: list[dict[str, object]] = []
    router = BackendRouter(paths, events.append)
    try:
        result = router.bootstrap({})
    finally:
        router.close()
    assert result["soundCount"] == 0
    assert result["autoIndex"]["attempted"] is False
    assert not [event for event in events if event["event"] == "index.progress"]


def test_batch_confirm_recomputes_preview_and_adds_only_selected_rows(
    paths, tmp_path: Path
):
    router = BackendRouter(paths, lambda _event: None)
    try:
        first = make_asset("sounds/ui/first.vsnd_c", id="first")
        second = make_asset("sounds/ui/second.vsnd_c", id="second")
        router.database.upsert_assets([first, second])
        project = ProjectService(paths, router.database).create("Batch Project")
        write_wav(tmp_path / "first.wav")
        write_wav(tmp_path / "second.wav")
        mapping = tmp_path / "mapping.csv"
        with mapping.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=["original_path", "replacement_file"]
            )
            writer.writeheader()
            writer.writerow(
                {
                    "original_path": first.internal_path,
                    "replacement_file": "first.wav",
                }
            )
            writer.writerow(
                {
                    "original_path": second.internal_path,
                    "replacement_file": "second.wav",
                }
            )
        result = router.confirm_batch(
            {
                "projectId": project.id,
                "path": str(mapping),
                "kind": "file",
                "rowNumbers": [3],
                "processing": ProcessingSettings().model_dump(by_alias=True),
                "looping": LoopSettings().model_dump(by_alias=True),
            }
        )
        rolled_back = router.rollback_batch(
            {
                "projectId": project.id,
                "transactionId": result["rollbackToken"],
            }
        )
    finally:
        router.close()
    assert result["added"] == 1
    assert result["failed"] == []
    assert result["rollbackToken"]
    assert [item["target"]["id"] for item in result["project"]["targetAssets"]] == [
        "second"
    ]
    assert rolled_back["removed"] == 1
    assert rolled_back["project"]["targetAssets"] == []


def test_queue_source_replacement_and_settings_copy(
    paths, database, tmp_path: Path
):
    first = make_asset("sounds/ui/first.vsnd_c", id="first")
    second = make_asset("sounds/ui/second.vsnd_c", id="second")
    database.upsert_assets([first, second])
    service = ProjectService(paths, database)
    project = service.create("Editable Project")
    original = write_wav(tmp_path / "original.wav", rate=44_100)
    replacement = write_wav(tmp_path / "replacement.wav", rate=48_000)
    project = service.confirm_replacement(
        project.id, first.id, original, ProcessingSettings(gain_db=6), LoopSettings()
    )
    project = service.confirm_replacement(
        project.id, second.id, original, ProcessingSettings(), LoopSettings()
    )
    first_item, second_item = project.target_assets
    project = service.replace_source(project.id, second_item.id, replacement)
    assert project.target_assets[1].source_filename == "replacement.wav"
    assert project.target_assets[1].source_metadata.sample_rate == 48_000
    project = service.duplicate_settings(project.id, first_item.id, second_item.id)
    assert project.target_assets[1].processing.gain_db == 6


def test_compatibility_copy_keeps_descriptive_export(
    paths, database
):
    projects = ProjectService(paths, database)
    project = projects.create("Compatibility Pack")
    export = paths.exports / project.name / "build-0001"
    export.mkdir(parents=True)
    canonical = export / f"{project.name}.vpk"
    canonical.write_bytes(b"validated-vpk")
    compatibility = Path(
        create_compatibility_copy(paths, projects, project.id, "build-0001")
    )
    assert canonical.read_bytes() == b"validated-vpk"
    assert compatibility.name == "pak01_dir.vpk"
    assert compatibility.read_bytes() == canonical.read_bytes()
    assert "pak01_dir.vpk" in (export / "checksums.txt").read_text(encoding="utf-8")


def test_failed_item_retry_reuses_latest_nonempty_compiled_output(paths):
    project_root = paths.project("retry-project")
    older = (
        project_root
        / "compiled-game/build-0001/sounds/ui/reusable.vsnd_c"
    )
    older.parent.mkdir(parents=True)
    older.write_bytes(b"verified")
    empty = (
        project_root
        / "compiled-game/build-0002/sounds/ui/reusable.vsnd_c"
    )
    empty.parent.mkdir(parents=True)
    empty.write_bytes(b"")

    reusable = latest_compiled(
        project_root, "sounds/ui/reusable.vsnd_c", "build-0003"
    )
    log_path = write_item_logs(
        project_root,
        "build-0003",
        [
            ItemBuildResult(
                item_id="item",
                target_path="sounds/ui/reusable.vsnd_c",
                status=ItemStatus.READY_FOR_PACKAGING,
                source_relative_path="source-files/source.wav",
                reused_compiled_output=True,
            )
        ],
    )

    assert reusable == older
    assert '"reusedCompiledOutput": true' in log_path.read_text(encoding="utf-8")
