from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from ..external.process import probe_output
from ..external.steam import locate_deadlock
from ..models import (
    CheckStatus,
    DiagnosticReport,
    ResolvedTools,
    Settings,
    ToolCheck,
    utc_now,
)
from ..paths import AppPaths
from ..settings import optional_existing

ProgressCallback = Callable[[dict[str, object]], None]
TOTAL_STAGES = 7


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path.resolve()
    return None


def _file_version(path: Path | None) -> str | None:
    if not path or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buffer)
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        ctypes.windll.version.VerQueryValueW(
            buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)
        )

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
            ]

        info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        parts = (
            info.dwFileVersionMS >> 16,
            info.dwFileVersionMS & 0xFFFF,
            info.dwFileVersionLS >> 16,
            info.dwFileVersionLS & 0xFFFF,
        )
        return ".".join(str(value) for value in parts)
    except Exception:
        # File version metadata is optional and varies between Windows builds.
        return None


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    completed: int,
    message: str,
) -> None:
    if progress:
        progress(
            {
                "event": "diagnostics.progress",
                "stage": stage,
                "completed": completed,
                "total": TOTAL_STAGES,
                "message": message,
            }
        )


def _check(
    identifier: str,
    label: str,
    path: Path | None,
    *,
    is_directory: bool = False,
    version: str | None = None,
) -> ToolCheck:
    found = bool(path and (path.is_dir() if is_directory else path.is_file()))
    return ToolCheck(
        id=identifier,
        label=label,
        status=CheckStatus.FOUND if found else CheckStatus.MISSING,
        path=str(path) if path and path.exists() else None,
        version=version,
        detail=(
            "Found and accessible."
            if found
            else "Not found in the selected tools or system path."
        ),
    )


def run_diagnostics(
    paths: AppPaths,
    settings: Settings,
    progress: ProgressCallback | None = None,
) -> DiagnosticReport:
    """Locate external tools and report the capabilities available to the app."""
    _emit(progress, "starting", 0, "Locating the selected CSDK folder…")
    desktop = Path.home() / "Desktop"
    csdk = optional_existing(settings.csdk_root_override) or _first_existing(
        [
            paths.tools / "CSDK12",
            paths.tools / "Reduced_CSDK_12",
            paths.tools / "Reduced CSDK 12",
            desktop / "Reduced_CSDK_12",
            desktop / "Reduced CSDK 12",
        ]
    )
    if csdk and csdk.is_file():
        csdk = csdk.parent
    _emit(progress, "csdkRoot", 1, "Inspecting the CSDK layout…")

    csdk_config = csdk / "csdkcfg.exe" if csdk else None
    resource_compiler = _first_existing(
        [
            csdk / "game/bin_cs2/win64/resourcecompiler.exe"
            if csdk
            else Path("__missing__"),
            csdk / "game/bin/win64/resourcecompiler.exe"
            if csdk
            else Path("__missing__"),
            csdk / "game/bin_tools/win64/resourcecompiler.exe"
            if csdk
            else Path("__missing__"),
        ]
    )
    vpk_packager = optional_existing(
        settings.vpk_packager_override
    ) or _first_existing(
        [
            csdk / "game/bin/win64/vpk.exe" if csdk else Path("__missing__"),
            csdk / "game/bin/win64/CSDKCfgVPK.exe"
            if csdk
            else Path("__missing__"),
        ]
    )
    _emit(
        progress,
        "csdkTools",
        2,
        "Checking CSDK compiler, packager, and addon folders…",
    )

    source_viewer = optional_existing(
        settings.source2_viewer_override
    ) or _first_existing(
        [
            paths.tools / "Source2Viewer/Source2Viewer.exe",
            paths.tools / "ValveResourceFormat/Source2Viewer.exe",
            desktop / "Source2Viewer.exe",
        ]
    )
    source_viewer_cli = optional_existing(
        settings.source2_viewer_cli_override
    ) or _first_existing(
        [
            paths.tools / "Source2Viewer/Source2Viewer-CLI.exe",
            paths.tools / "ValveResourceFormat/Source2Viewer-CLI.exe",
            (
                source_viewer
                if source_viewer and "cli" in source_viewer.stem.lower()
                else Path("__missing__")
            ),
            (
                source_viewer.with_name("Source2Viewer-CLI.exe")
                if source_viewer
                else Path("__missing__")
            ),
            desktop / "Source2Viewer-CLI.exe",
        ]
    )
    _emit(
        progress,
        "source2Viewer",
        3,
        "Checking Source 2 Viewer and its CLI companion…",
    )

    ffmpeg = optional_existing(settings.ffmpeg_override) or _first_existing(
        [
            paths.tools / "ffmpeg/ffmpeg.exe",
            Path(shutil.which("ffmpeg") or "__missing__"),
        ]
    )
    ffprobe = optional_existing(settings.ffprobe_override) or _first_existing(
        [
            paths.tools / "ffmpeg/ffprobe.exe",
            ffmpeg.parent / "ffprobe.exe" if ffmpeg else Path("__missing__"),
            Path(shutil.which("ffprobe") or "__missing__"),
        ]
    )
    ffmpeg_version = probe_output(ffmpeg, ["-version"]) if ffmpeg else None
    ffprobe_version = probe_output(ffprobe, ["-version"]) if ffprobe else None
    _emit(progress, "mediaTools", 4, "Checking FFmpeg and FFprobe…")

    deadlock = optional_existing(settings.deadlock_root_override) or locate_deadlock()
    archive = deadlock / "game/citadel/pak01_dir.vpk" if deadlock else None
    _emit(
        progress,
        "deadlock",
        5,
        "Checking the Steam installation and Deadlock archive…",
    )

    lame = _first_existing(
        [
            resource_compiler.parent / "lame_enc.dll"
            if resource_compiler
            else Path("__missing__"),
            csdk / "game/bin/win64/lame_enc.dll" if csdk else Path("__missing__"),
            csdk / "game/bin_tools/win64/lame_enc.dll"
            if csdk
            else Path("__missing__"),
        ]
    )
    _emit(progress, "encoder", 6, "Checking the CSDK audio encoder…")

    resolved = ResolvedTools(
        csdk_root=str(csdk) if csdk else None,
        csdk_config=(
            str(csdk_config) if csdk_config and csdk_config.is_file() else None
        ),
        resource_compiler=str(resource_compiler) if resource_compiler else None,
        vpk_packager=str(vpk_packager) if vpk_packager else None,
        source2_viewer=str(source_viewer) if source_viewer else None,
        source2_viewer_cli=str(source_viewer_cli) if source_viewer_cli else None,
        ffmpeg=str(ffmpeg) if ffmpeg else None,
        ffprobe=str(ffprobe) if ffprobe else None,
        deadlock_root=str(deadlock) if deadlock else None,
        deadlock_archive=str(archive) if archive and archive.is_file() else None,
        lame_encoder=str(lame) if lame else None,
    )
    checks = [
        _check("csdkRoot", "CSDK 12 root", csdk, is_directory=True),
        _check("csdkConfig", "csdkcfg.exe", csdk_config),
        _check("resourceCompiler", "CSDK resource compiler", resource_compiler),
        _check("vpkUtility", "CSDK VPK packaging utility", vpk_packager),
        _check(
            "contentAddons",
            "CSDK content/citadel_addons",
            csdk / "content/citadel_addons" if csdk else None,
            is_directory=True,
        ),
        _check(
            "gameAddons",
            "CSDK game/citadel_addons",
            csdk / "game/citadel_addons" if csdk else None,
            is_directory=True,
        ),
        _check(
            "source2Viewer",
            "Source 2 Viewer",
            source_viewer,
            version=_file_version(source_viewer),
        ),
        ToolCheck(
            id="source2ViewerCli",
            label="Source 2 Viewer CLI",
            status=(
                CheckStatus.FOUND
                if source_viewer_cli
                else CheckStatus.CAPABILITY_UNAVAILABLE
            ),
            path=(
                str(source_viewer_cli or source_viewer)
                if source_viewer_cli or source_viewer
                else None
            ),
            version=_file_version(source_viewer_cli or source_viewer),
            detail=(
                "Selective headless export is available."
                if source_viewer_cli
                else (
                    "The GUI was found, but selective preview requires "
                    "Source2Viewer-CLI.exe."
                    if source_viewer
                    else "Source2Viewer-CLI.exe was not found."
                )
            ),
        ),
        _check("ffmpeg", "FFmpeg", ffmpeg, version=ffmpeg_version),
        _check("ffprobe", "FFprobe", ffprobe, version=ffprobe_version),
        _check(
            "deadlock",
            "Deadlock installation",
            deadlock,
            is_directory=True,
        ),
        _check("archive", "Deadlock game/citadel/pak01_dir.vpk", archive),
        _check("lame", "CSDK lame_enc.dll", lame),
    ]

    can_index = bool(archive and archive.is_file())
    can_preview = can_index and bool(source_viewer_cli)
    can_process = bool(ffmpeg and ffprobe)
    can_compile = bool(
        csdk
        and resource_compiler
        and (csdk / "content/citadel_addons").is_dir()
        and (csdk / "game/citadel_addons").is_dir()
    )
    can_package = bool(vpk_packager)
    report = DiagnosticReport(
        checked_at=utc_now(),
        portable_paths=paths.public(),
        checks=checks,
        resolved=resolved,
        can_index=can_index,
        can_preview_original=can_preview,
        can_process_audio=can_process,
        can_compile=can_compile,
        can_package_headlessly=can_package,
        can_build=can_process and can_compile and can_package,
    )
    _emit(progress, "complete", 7, "Diagnostics scan complete.")
    return report
