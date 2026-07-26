from __future__ import annotations

import os
import json
import shutil
import uuid
from pathlib import Path

import pytest
from PIL import Image

from deadlock_sound_studio.csdk.adapters import compile_resource
from deadlock_sound_studio.build import BuildJob
from deadlock_sound_studio.database import Database
from deadlock_sound_studio.diagnostics import run_diagnostics
from deadlock_sound_studio.external.process import CancellationToken
from deadlock_sound_studio.models import LoopSettings, ProcessingSettings, Settings
from deadlock_sound_studio.paths import AppPaths
from deadlock_sound_studio.projects import ProjectService
from deadlock_sound_studio.external.process import run_process
from deadlock_sound_studio.visuals import write_vtex_descriptor
from deadlock_sound_studio.vpk import list_vpk

from conftest import make_asset, write_wav

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("DSS_RUN_INTEGRATION") != "1",
    reason="Set DSS_RUN_INTEGRATION=1 to probe locally supplied tools.",
)
def test_real_resource_compiler_exposes_help():
    root = Path(os.environ["DSS_CSDK_ROOT"]).resolve(strict=True)
    compiler = root / "game/bin/win64/resourcecompiler.exe"
    record = run_process(compiler, ["-help"], timeout_seconds=20)
    assert record.exit_code == 0
    assert "-i" in record.stdout


@pytest.mark.skipif(
    os.environ.get("DSS_RUN_INTEGRATION") != "1",
    reason="Set DSS_RUN_INTEGRATION=1 to probe locally supplied tools.",
)
def test_deadlock_archive_is_present():
    root = Path(os.environ["DSS_DEADLOCK_ROOT"]).resolve(strict=True)
    archive = root / "game/citadel/pak01_dir.vpk"
    assert archive.is_file()
    assert archive.stat().st_size > 0


@pytest.mark.skipif(
    os.environ.get("DSS_RUN_INTEGRATION") != "1",
    reason="Set DSS_RUN_INTEGRATION=1 to probe locally supplied tools.",
)
def test_real_texture_descriptor_compiles_to_vtex_c():
    root = Path(os.environ["DSS_CSDK_ROOT"]).resolve(strict=True)
    compiler = root / "game/bin_cs2/win64/resourcecompiler.exe"
    addon = f"dmm_visual_test_{uuid.uuid4().hex[:12]}"
    content = root / "content/citadel_addons" / addon
    game = root / "game/citadel_addons" / addon
    try:
        source = content / "materials/integration/texture_source.png"
        source.parent.mkdir(parents=True)
        Image.new("RGBA", (16, 16), (20, 80, 160, 180)).save(source)
        descriptor = content / "materials/integration/texture.vtex"
        write_vtex_descriptor(
            descriptor,
            "materials/integration/texture_source.png",
            has_alpha=True,
            color_space="srgb",
            normal_map=False,
        )

        output, record = compile_resource(
            compiler,
            root,
            descriptor,
            addon,
            "materials/integration/texture.vtex_c",
        )

        assert record.exit_code == 0
        assert output.is_file()
        assert output.stat().st_size > 0
    finally:
        for target, parent in (
            (content, root / "content/citadel_addons"),
            (game, root / "game/citadel_addons"),
        ):
            if target.exists():
                target.resolve().relative_to(parent.resolve(strict=True))
                shutil.rmtree(target)


@pytest.mark.skipif(
    os.environ.get("DSS_RUN_INTEGRATION") != "1",
    reason="Set DSS_RUN_INTEGRATION=1 to probe locally supplied tools.",
)
def test_real_material_source_compiles_to_vmat_c():
    root = Path(os.environ["DSS_CSDK_ROOT"]).resolve(strict=True)
    compiler = root / "game/bin_cs2/win64/resourcecompiler.exe"
    addon = f"dmm_material_test_{uuid.uuid4().hex[:12]}"
    content = root / "content/citadel_addons" / addon
    game = root / "game/citadel_addons" / addon
    try:
        source = content / "materials/integration/material.vmat"
        source.parent.mkdir(parents=True)
        source.write_text(
            '"Layer0"\n{\n'
            '\t"shader"\t"sky.vfx"\n'
            '\t"g_flBrightnessExposureBias"\t"0"\n'
            '\t"SkyTexture"\t"materials/editor/sky_default_grey.png"\n'
            '}\n',
            encoding="utf-8",
        )

        output, record = compile_resource(
            compiler,
            root,
            source,
            addon,
            "materials/integration/material.vmat_c",
        )

        assert record.exit_code == 0
        assert output.is_file()
        assert output.stat().st_size > 0
    finally:
        for target, parent in (
            (content, root / "content/citadel_addons"),
            (game, root / "game/citadel_addons"),
        ):
            if target.exists():
                target.resolve().relative_to(parent.resolve(strict=True))
                shutil.rmtree(target)


@pytest.mark.skipif(
    os.environ.get("DSS_RUN_INTEGRATION") != "1",
    reason="Set DSS_RUN_INTEGRATION=1 to probe locally supplied tools.",
)
@pytest.mark.parametrize("replacement_count", [1, 2])
def test_real_sound_build_creates_one_validated_vpk(
    tmp_path: Path, replacement_count: int
):
    csdk = Path(os.environ["DSS_CSDK_ROOT"]).resolve(strict=True)
    ffmpeg = Path(os.environ["DSS_FFMPEG"]).resolve(strict=True)
    ffprobe = Path(os.environ["DSS_FFPROBE"]).resolve(strict=True)
    paths = AppPaths.from_root(tmp_path / "app")
    database = Database(paths)
    projects = ProjectService(paths, database)
    project = None
    addon_name = None
    try:
        project = projects.create(f"Verification Build {replacement_count}")
        addon_name = (
            f"dss_{project.name[:40]}_{project.id[:8].replace('-', '')}"
        )
        source = write_wav(tmp_path / "replacement.wav")
        expected: list[str] = []
        for index in range(replacement_count):
            target = (
                f"sounds/dmm_verification_{project.id[:8]}/"
                f"sound_{index}.vsnd_c"
            )
            asset = make_asset(target, id=f"asset-{index}")
            database.upsert_assets([asset])
            projects.confirm_replacement(
                project.id,
                asset.id,
                source,
                ProcessingSettings(),
                LoopSettings(),
                ffprobe,
            )
            expected.append(target)

        diagnostics = run_diagnostics(
            paths,
            Settings(
                csdk_root_override=str(csdk),
                ffmpeg_override=str(ffmpeg),
                ffprobe_override=str(ffprobe),
            ),
        )
        result = BuildJob(
            paths, projects, diagnostics, lambda _event: None
        ).run(project.id, "real-build", CancellationToken())

        assert result.success, result.message
        assert result.vpk_path
        assert [entry.path for entry in list_vpk(Path(result.vpk_path))] == sorted(
            expected
        )
    finally:
        database.close()
        if project and addon_name:
            for parent in (
                csdk / "content/citadel_addons",
                csdk / "game/citadel_addons",
            ):
                target = parent / addon_name
                marker = target / ".deadlock-sound-studio.json"
                if not marker.is_file():
                    continue
                owner = json.loads(marker.read_text(encoding="utf-8"))
                if owner.get("projectId") != project.id:
                    continue
                target.resolve(strict=True).relative_to(
                    parent.resolve(strict=True)
                )
                shutil.rmtree(target)
