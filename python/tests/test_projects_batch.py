from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from deadlock_sound_studio.batch import preview_folder, preview_mapping_file
from deadlock_sound_studio.models import (
    LoopSettings,
    ProcessingSettings,
    ReplacementItem,
)
from deadlock_sound_studio.projects import ProjectService, detect_conflicts

from conftest import make_asset, write_wav


def replacement(identifier: str, path: str, *, enabled: bool = True) -> ReplacementItem:
    return ReplacementItem(
        id=identifier,
        order=0,
        enabled=enabled,
        target=make_asset(path, id=f"asset-{identifier}"),
        source_filename="source.wav",
        source_relative_path="source-files/source.wav",
    )


def test_duplicate_and_case_insensitive_target_detection():
    conflicts = detect_conflicts(
        [
            replacement("one", "sounds/ui/Accept.vsnd_c"),
            replacement("two", "sounds/ui/accept.vsnd_c"),
            replacement("disabled", "sounds/ui/accept.vsnd_c", enabled=False),
        ]
    )
    assert len(conflicts) == 1
    assert conflicts[0].item_ids == ["one", "two"]
    assert conflicts[0].kind.value == "caseInsensitiveCollision"


def test_individual_replacement_confirmation_copies_source_unchanged(
    paths, database, tmp_path: Path
):
    asset = make_asset()
    database.upsert_assets([asset])
    source = write_wav(tmp_path / "chosen.wav")
    original = source.read_bytes()
    service = ProjectService(paths, database)
    project = service.create("Example Pack")
    updated = service.confirm_replacement(
        project.id,
        asset.id,
        source,
        ProcessingSettings(),
        LoopSettings(),
    )
    assert source.read_bytes() == original
    item = updated.target_assets[0]
    copied = paths.project(project.id) / item.source_relative_path
    assert copied.read_bytes() == original
    assert item.target.internal_path == asset.internal_path


def test_project_deletion_moves_project_to_recovery_backup(paths, database):
    service = ProjectService(paths, database)
    project = service.create("Recoverable Mod")
    original = paths.project(project.id)

    backup = service.delete(project.id)

    assert not original.exists()
    assert backup.parent == paths.backups / "deleted-projects"
    assert (backup / "project.json").is_file()
    assert database.project_rows() == []


def test_csv_import_keeps_valid_rows_when_another_row_fails(
    database, tmp_path: Path
):
    asset = make_asset()
    database.upsert_assets([asset])
    write_wav(tmp_path / "good.wav")
    mapping = tmp_path / "mapping.csv"
    with mapping.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["original_path", "replacement_file"])
        writer.writeheader()
        writer.writerow(
            {"original_path": asset.internal_path, "replacement_file": "good.wav"}
        )
        writer.writerow(
            {"original_path": "sounds/missing.vsnd_c", "replacement_file": "missing.mp3"}
        )
    rows = preview_mapping_file(database, mapping)
    assert rows[0].status == "matched"
    assert rows[1].status == "invalid"
    assert len(rows[1].messages) == 2


def test_csv_import_parses_optional_per_row_processing_columns(
    database, tmp_path: Path
):
    asset = make_asset()
    database.upsert_assets([asset])
    write_wav(tmp_path / "custom.wav")
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "original_path,replacement_file,gain_db,normalize,loop_enabled,loop_start,loop_end\n"
        f"{asset.internal_path},custom.wav,4.5,false,true,0.01,0.08\n",
        encoding="utf-8",
    )

    row = preview_mapping_file(database, mapping)[0]

    assert row.status == "matched"
    assert row.uses_row_settings is True
    assert row.processing.gain_db == 4.5
    assert row.processing.normalize is False
    assert row.looping.enabled is True
    assert row.looping.start_seconds == 0.01
    assert row.looping.end_seconds == 0.08


def test_csv_relative_paths_cannot_escape_mapping_folder(database, tmp_path: Path):
    asset = make_asset()
    database.upsert_assets([asset])
    mapping_root = tmp_path / "mapping"
    mapping_root.mkdir()
    write_wav(tmp_path / "outside.wav")
    mapping = mapping_root / "mapping.csv"
    mapping.write_text(
        "original_path,replacement_file\n"
        f"{asset.internal_path},../outside.wav\n",
        encoding="utf-8",
    )
    row = preview_mapping_file(database, mapping)[0]
    assert row.status == "invalid"
    assert any("escapes" in message for message in row.messages)


def test_xlsx_import(database, tmp_path: Path):
    asset = make_asset()
    database.upsert_assets([asset])
    write_wav(tmp_path / "replacement.wav")
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["original_path", "replacement_file"])
    sheet.append([asset.internal_path, "replacement.wav"])
    mapping = tmp_path / "mapping.xlsx"
    workbook.save(mapping)
    rows = preview_mapping_file(database, mapping)
    assert rows[0].status == "matched"


def test_folder_matching_reports_ambiguous_names(database, tmp_path: Path):
    database.upsert_assets(
        [
            make_asset("sounds/a/ping.vsnd_c", id="one"),
            make_asset("sounds/b/ping.vsnd_c", id="two"),
        ]
    )
    folder = tmp_path / "audio"
    write_wav(folder / "ping.wav")
    row = preview_folder(database, folder)[0]
    assert row.status == "ambiguous"
    assert row.asset_id is None
