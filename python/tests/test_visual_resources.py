from __future__ import annotations

from pathlib import Path

from PIL import Image

from deadlock_sound_studio.indexing import index_archive
from deadlock_sound_studio.models import (
    VisualResourceAsset,
    VisualResourceKind,
    utc_now,
)
from deadlock_sound_studio.projects import ProjectService, detect_conflicts
from deadlock_sound_studio.visuals import inspect_visual_source, write_vtex_descriptor

from conftest import write_vpk


def make_visual(
    internal_path: str = "materials/ui/test.vtex_c",
    *,
    identifier: str = "visual",
    kind: VisualResourceKind = VisualResourceKind.TEXTURE,
) -> VisualResourceAsset:
    return VisualResourceAsset(
        id=identifier,
        internal_path=internal_path,
        compiled_path=internal_path,
        filename=Path(internal_path).name,
        kind=kind,
        source_archive="pak01_dir.vpk",
        archive_fingerprint="archive",
        asset_fingerprint="1234",
        stored_size=42,
        last_indexed_at=utc_now(),
    )


def test_archive_index_includes_textures_and_materials(database, tmp_path: Path):
    archive = write_vpk(
        tmp_path / "pak01_dir.vpk",
        {
            "sounds/ui/click.vsnd_c": b"sound",
            "materials/ui/panel.vtex_c": b"texture",
            "materials/ui/panel.vmat_c": b"material",
        },
    )

    result = index_archive(database, archive)

    assert result.indexed == 1
    assert result.visual_indexed == 2
    assert [asset.kind for asset in database.search_visual_assets()] == [
        VisualResourceKind.MATERIAL,
        VisualResourceKind.TEXTURE,
    ]


def test_texture_inspection_builds_preview_and_validation_metadata(paths, tmp_path: Path):
    source = tmp_path / "hero_normal.png"
    Image.new("RGBA", (300, 128), (128, 128, 255, 128)).save(source)

    metadata = inspect_visual_source(paths, source, VisualResourceKind.TEXTURE)

    assert (metadata.width, metadata.height) == (300, 128)
    assert metadata.has_alpha is True
    assert metadata.probable_normal_map is True
    assert metadata.color_space == "linear"
    assert metadata.preview_path and Path(metadata.preview_path).is_file()
    assert any("Non-power-of-two" in warning for warning in metadata.warnings)


def test_material_inspection_finds_resource_dependencies(paths, tmp_path: Path):
    source = tmp_path / "panel.vmat"
    source.write_text(
        'Layer0\n{\n  shader "generic.vfx"\n'
        '  g_tColor "resource:materials/ui/panel_color.vtex"\n}\n',
        encoding="utf-8",
    )

    metadata = inspect_visual_source(paths, source, VisualResourceKind.MATERIAL)

    assert metadata.format == "VMAT"
    assert metadata.dependencies == ["materials/ui/panel_color.vtex"]
    assert "generic.vfx" in (metadata.text_preview or "")


def test_project_persists_visual_replacement(paths, database, tmp_path: Path):
    asset = make_visual()
    database.upsert_visual_assets([asset])
    service = ProjectService(paths, database)
    project = service.create("Visual Project")
    source = tmp_path / "replacement.png"
    Image.new("RGB", (64, 64), (20, 40, 80)).save(source)

    project = service.confirm_visual_replacement(project.id, asset.id, source)

    assert len(project.visual_assets) == 1
    item = project.visual_assets[0]
    assert item.target.id == asset.id
    assert (paths.project(project.id) / item.source_relative_path).is_file()
    assert service.list()[0].replacement_count == 1


def test_visual_and_sound_targets_share_conflict_detection():
    visual = make_visual()
    first = type("Item", (), {"id": "one", "enabled": True, "target": visual})()
    second = type("Item", (), {"id": "two", "enabled": True, "target": visual})()

    conflicts = detect_conflicts([first, second])  # type: ignore[list-item]

    assert len(conflicts) == 1
    assert conflicts[0].item_ids == ["one", "two"]


def test_vtex_descriptor_enables_mips_and_preserves_color_intent(tmp_path: Path):
    destination = tmp_path / "panel.vtex"

    write_vtex_descriptor(
        destination,
        "materials/ui/panel_source.png",
        has_alpha=True,
        color_space="srgb",
        normal_map=False,
    )

    text = destination.read_text(encoding="utf-8")
    assert '"m_fileName" "string" "materials/ui/panel_source.png"' in text
    assert '"m_outputFormat" "string" "DXT5"' in text
    assert '"m_mipAlgorithm" "CDmeImageProcessor"' in text
