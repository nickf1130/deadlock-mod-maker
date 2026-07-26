from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import deadlock_sound_studio.build.service as build_module
from conftest import make_asset, write_vpk, write_wav
from deadlock_sound_studio.audio import inspect_audio
from deadlock_sound_studio.build import BuildJob
from deadlock_sound_studio.csdk.adapters import expected_compiled_output
from deadlock_sound_studio.diagnostics import run_diagnostics
from deadlock_sound_studio.external.process import CancellationToken
from deadlock_sound_studio.models import (
    LoopSettings,
    ProcessRecord,
    ProcessingSettings,
    Settings,
    utc_now,
)
from deadlock_sound_studio.projects import ProjectService
from deadlock_sound_studio.vpk import list_vpk


def _record(executable: Path, produced: Path) -> ProcessRecord:
    return ProcessRecord(
        executable_path=str(executable),
        sanitized_arguments=[],
        started_at=utc_now(),
        duration_ms=1,
        exit_code=0,
        stdout="",
        stderr="",
        produced_files=[str(produced)],
    )


@pytest.mark.parametrize("replacement_count", [1, 2])
def test_build_packages_every_replacement_in_one_validated_vpk(
    paths,
    database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_count: int,
):
    csdk = tmp_path / "csdk"
    for directory in (
        csdk / "content/citadel_addons",
        csdk / "game/citadel_addons",
        csdk / "game/bin_cs2/win64",
    ):
        directory.mkdir(parents=True)
    compiler = csdk / "game/bin_cs2/win64/resourcecompiler.exe"
    packager = tmp_path / "vpk.exe"
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    for executable in (compiler, packager, ffmpeg, ffprobe):
        executable.write_bytes(b"test executable placeholder")

    settings = Settings(
        csdk_root_override=str(csdk),
        vpk_packager_override=str(packager),
        ffmpeg_override=str(ffmpeg),
        ffprobe_override=str(ffprobe),
    )
    diagnostics = run_diagnostics(paths, settings)
    projects = ProjectService(paths, database)
    project = projects.create(f"Sound Build {replacement_count}")
    source = write_wav(tmp_path / "replacement.wav")
    expected_paths: list[str] = []
    for index in range(replacement_count):
        internal_path = f"sounds/ui/replacement_{index}.vsnd_c"
        asset = make_asset(internal_path, id=f"asset-{index}")
        database.upsert_assets([asset])
        project = projects.confirm_replacement(
            project.id,
            asset.id,
            source,
            ProcessingSettings(),
            LoopSettings(),
        )
        expected_paths.append(internal_path)

    def fake_process_audio(
        source_path,
        output,
        _processing,
        _ffmpeg,
        _ffprobe,
        **_kwargs,
    ):
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output)
        return inspect_audio(output)

    def fake_compile(
        executable,
        csdk_root,
        source_path,
        addon_name,
        compiled_target,
        **_kwargs,
    ):
        output = expected_compiled_output(
            csdk_root, addon_name, compiled_target
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output)
        return output, _record(executable, output)

    def fake_package(executable, staging, output, **_kwargs):
        entries = {
            path.relative_to(staging).as_posix(): path.read_bytes()
            for path in staging.rglob("*")
            if path.is_file()
        }
        write_vpk(output, entries)
        return _record(executable, output)

    monkeypatch.setattr(build_module, "process_audio", fake_process_audio)
    monkeypatch.setattr(build_module, "compile_resource", fake_compile)
    monkeypatch.setattr(build_module, "package_vpk", fake_package)

    result = BuildJob(
        paths, projects, diagnostics, lambda _event: None
    ).run(project.id, "test-job", CancellationToken())

    assert result.success
    assert result.vpk_path
    assert [entry.path for entry in list_vpk(Path(result.vpk_path))] == sorted(
        expected_paths
    )
