from __future__ import annotations

import logging
from pathlib import Path

import pytest

from deadlock_sound_studio.diagnostics import run_diagnostics
from deadlock_sound_studio.models import CheckStatus, Settings
from deadlock_sound_studio.paths import (
    AppPaths,
    ensure_within,
    normalize_addon_name,
    normalize_internal_path,
    source_path_for_compiled,
)
from deadlock_sound_studio.protocol.worker import ErrorFileHandler
from deadlock_sound_studio.settings import load_settings, save_settings


def test_portable_paths_only_create_required_data_root(tmp_path: Path):
    paths = AppPaths.from_root(tmp_path / "portable")
    assert paths.root == (tmp_path / "portable").resolve()
    assert paths.data.is_dir()
    assert not paths.tools.exists()
    assert not paths.cache.exists()
    assert not paths.projects.exists()
    assert not paths.exports.exists()
    assert not paths.logs.exists()
    assert not paths.backups.exists()


def test_worker_log_is_created_only_after_an_error(paths: AppPaths):
    output = paths.logs / "python-worker.log"
    handler = ErrorFileHandler(output, delay=True)
    handler.setLevel(logging.ERROR)
    logger = logging.getLogger("test-error-only-file-log")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info("Normal startup message")
        assert not output.exists()
        logger.error("Unexpected backend failure")
        assert "Unexpected backend failure" in output.read_text(encoding="utf-8")
    finally:
        handler.close()
        logger.handlers = []


def test_tutorial_completion_is_saved_with_portable_settings(paths: AppPaths):
    assert not load_settings(paths).tutorial_completed
    save_settings(paths, Settings(setup_completed=True, tutorial_completed=True))
    saved = load_settings(paths)
    assert saved.setup_completed
    assert saved.tutorial_completed


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("My Sound-Pack", "my_sound_pack"),
        ("clean_name", "clean_name"),
        ("Two   Spaces", "two_spaces"),
    ],
)
def test_addon_name_normalization(value: str, expected: str):
    assert normalize_addon_name(value) == expected


@pytest.mark.parametrize("value", ["9starts_wrong", "../escape", "bad/name", "💥"])
def test_addon_name_rejects_unsupported_values(value: str):
    with pytest.raises(Exception):
        normalize_addon_name(value)


def test_vpk_internal_path_normalization_and_source_mapping():
    assert normalize_internal_path(r"sounds\ui\accept.vsnd_c") == "sounds/ui/accept.vsnd_c"
    assert source_path_for_compiled("sounds/ui/accept.vsnd_c") == "sounds/ui/accept.wav"
    with pytest.raises(Exception):
        normalize_internal_path("../sounds/escape.vsnd_c")
    with pytest.raises(Exception):
        normalize_internal_path("C:/sounds/escape.vsnd_c")


def test_approved_roots_reject_path_traversal(paths: AppPaths, tmp_path: Path):
    inside = paths.cache / "preview.wav"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"audio")
    outside = tmp_path / "private.wav"
    outside.write_bytes(b"private")
    assert ensure_within(inside, (paths.cache,)) == inside.resolve()
    with pytest.raises(Exception):
        ensure_within(outside, (paths.cache,))


def test_tool_discovery_finds_supplied_csdk_layout(paths: AppPaths, tmp_path: Path):
    csdk = tmp_path / "Reduced_CSDK_12"
    for target in (
        csdk / "content/citadel_addons",
        csdk / "game/citadel_addons",
        csdk / "game/bin/win64",
        csdk / "game/bin_cs2/win64",
    ):
        target.mkdir(parents=True, exist_ok=True)
    for target in (
        csdk / "csdkcfg.exe",
        csdk / "game/bin/win64/resourcecompiler.exe",
        csdk / "game/bin/win64/CSDKCfgVPK.exe",
        csdk / "game/bin/win64/lame_enc.dll",
        csdk / "game/bin_cs2/win64/resourcecompiler.exe",
        csdk / "game/bin_cs2/win64/lame_enc.dll",
    ):
        target.write_bytes(b"fake")
    report = run_diagnostics(paths, Settings(csdk_root_override=str(csdk)))
    statuses = {check.id: check.status for check in report.checks}
    assert statuses["csdkRoot"] == CheckStatus.FOUND
    assert statuses["resourceCompiler"] == CheckStatus.FOUND
    assert statuses["vpkUtility"] == CheckStatus.FOUND
    assert report.can_compile
    assert report.resolved.resource_compiler is not None
    assert "bin_cs2" in report.resolved.resource_compiler


def test_tool_discovery_does_not_assume_the_users_desktop(
    paths: AppPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    desktop = tmp_path / "Desktop"
    csdk = desktop / "Reduced_CSDK_12"
    csdk.mkdir(parents=True)
    viewer = desktop / "Source2Viewer.exe"
    viewer.write_bytes(b"fake")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    report = run_diagnostics(paths, Settings())

    assert report.resolved.csdk_root is None
    assert report.resolved.source2_viewer is None


def test_gui_source_viewer_does_not_claim_cli_capability(paths: AppPaths, tmp_path: Path):
    viewer = tmp_path / "Source2Viewer.exe"
    viewer.write_bytes(b"fake")
    report = run_diagnostics(paths, Settings(source2_viewer_override=str(viewer)))
    cli = next(check for check in report.checks if check.id == "source2ViewerCli")
    assert cli.status == CheckStatus.CAPABILITY_UNAVAILABLE
    assert not report.can_preview_original


def test_selected_source_viewer_discovers_cli_sibling_and_reports_scan_progress(
    paths: AppPaths, tmp_path: Path
):
    viewer = tmp_path / "Source2Viewer.exe"
    viewer.write_bytes(b"gui")
    cli = tmp_path / "Source2Viewer-CLI.exe"
    cli.write_bytes(b"cli")
    events: list[dict[str, object]] = []

    report = run_diagnostics(
        paths,
        Settings(source2_viewer_override=str(viewer)),
        events.append,
    )

    assert report.resolved.source2_viewer == str(viewer)
    assert report.resolved.source2_viewer_cli == str(cli)
    cli_check = next(check for check in report.checks if check.id == "source2ViewerCli")
    assert cli_check.status == CheckStatus.FOUND
    assert [event["completed"] for event in events] == list(range(8))
    assert events[-1]["stage"] == "complete"


def test_source_viewer_cli_can_be_selected_from_a_separate_folder(
    paths: AppPaths, tmp_path: Path
):
    viewer = tmp_path / "viewer" / "Source2Viewer.exe"
    viewer.parent.mkdir()
    viewer.write_bytes(b"gui")
    cli = tmp_path / "cli" / "Source2Viewer-CLI.exe"
    cli.parent.mkdir()
    cli.write_bytes(b"cli")

    report = run_diagnostics(
        paths,
        Settings(
            source2_viewer_override=str(viewer),
            source2_viewer_cli_override=str(cli),
        )
    )

    assert report.resolved.source2_viewer == str(viewer)
    assert report.resolved.source2_viewer_cli == str(cli)
    cli_check = next(check for check in report.checks if check.id == "source2ViewerCli")
    assert cli_check.status == CheckStatus.FOUND


def test_selected_ffmpeg_pair_enables_audio_processing(paths: AppPaths, tmp_path: Path):
    binary_root = tmp_path / "ffmpeg" / "bin"
    binary_root.mkdir(parents=True)
    ffmpeg = binary_root / "ffmpeg.exe"
    ffprobe = binary_root / "ffprobe.exe"
    ffmpeg.write_bytes(b"fake")
    ffprobe.write_bytes(b"fake")

    report = run_diagnostics(
        paths,
        Settings(ffmpeg_override=str(ffmpeg), ffprobe_override=str(ffprobe))
    )

    statuses = {check.id: check.status for check in report.checks}
    assert statuses["ffmpeg"] == CheckStatus.FOUND
    assert statuses["ffprobe"] == CheckStatus.FOUND
    assert report.can_process_audio


def test_tool_discovery_prefers_silent_native_vpk_utility(paths: AppPaths, tmp_path: Path):
    csdk = tmp_path / "CSDK12"
    binary_root = csdk / "game/bin/win64"
    binary_root.mkdir(parents=True)
    (binary_root / "vpk.exe").write_bytes(b"silent")
    (binary_root / "CSDKCfgVPK.exe").write_bytes(b"supervised")

    report = run_diagnostics(paths, Settings(csdk_root_override=str(csdk)))

    assert report.resolved.vpk_packager is not None
    assert Path(report.resolved.vpk_packager).name == "vpk.exe"
