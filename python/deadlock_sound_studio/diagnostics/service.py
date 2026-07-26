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


def _paths_below(root: Path | None, relative_paths: list[str]) -> list[Path]:
    """Build candidate paths only when their shared root is available."""
    if root is None:
        return []
    return [root / relative_path for relative_path in relative_paths]


def _system_command(name: str) -> list[Path]:
    """Return a PATH-discovered command as a candidate when it exists."""
    command = shutil.which(name)
    if command is None:
        return []
    return [Path(command)]


def _path_text(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


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
    found = False
    if path is not None:
        if is_directory:
            found = path.is_dir()
        else:
            found = path.is_file()

    status = CheckStatus.MISSING
    resolved_path = None
    detail = "Not found in the selected tools or system path."
    if found:
        status = CheckStatus.FOUND
        resolved_path = str(path)
        detail = "Found and accessible."

    return ToolCheck(
        id=identifier,
        label=label,
        status=status,
        path=resolved_path,
        version=version,
        detail=detail,
    )


def run_diagnostics(
    paths: AppPaths,
    settings: Settings,
    progress: ProgressCallback | None = None,
) -> DiagnosticReport:
    """Locate external tools and report the capabilities available to the app."""
    _emit(progress, "starting", 0, "Locating the selected CSDK folder…")
    csdk = optional_existing(settings.csdk_root_override) or _first_existing(
        [
            paths.tools / "CSDK12",
            paths.tools / "Reduced_CSDK_12",
            paths.tools / "Reduced CSDK 12",
        ]
    )
    if csdk and csdk.is_file():
        csdk = csdk.parent
    _emit(progress, "csdkRoot", 1, "Inspecting the CSDK layout…")

    csdk_config = None
    if csdk is not None:
        csdk_config = csdk / "csdkcfg.exe"

    resource_compiler = _first_existing(
        _paths_below(
            csdk,
            [
                "game/bin_cs2/win64/resourcecompiler.exe",
                "game/bin/win64/resourcecompiler.exe",
                "game/bin_tools/win64/resourcecompiler.exe",
            ],
        )
    )
    vpk_packager = optional_existing(
        settings.vpk_packager_override
    ) or _first_existing(
        _paths_below(
            csdk,
            [
                "game/bin/win64/vpk.exe",
                "game/bin/win64/CSDKCfgVPK.exe",
            ],
        )
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
        ]
    )
    source_viewer_cli_candidates = [
        paths.tools / "Source2Viewer/Source2Viewer-CLI.exe",
        paths.tools / "ValveResourceFormat/Source2Viewer-CLI.exe",
    ]
    if source_viewer is not None:
        if "cli" in source_viewer.stem.lower():
            source_viewer_cli_candidates.append(source_viewer)
        source_viewer_cli_candidates.append(
            source_viewer.with_name("Source2Viewer-CLI.exe")
        )

    source_viewer_cli = optional_existing(
        settings.source2_viewer_cli_override
    ) or _first_existing(source_viewer_cli_candidates)
    _emit(
        progress,
        "source2Viewer",
        3,
        "Checking Source 2 Viewer and its CLI companion…",
    )

    ffmpeg = optional_existing(settings.ffmpeg_override) or _first_existing(
        [paths.tools / "ffmpeg/ffmpeg.exe"] + _system_command("ffmpeg")
    )
    ffmpeg_directory = None
    if ffmpeg is not None:
        ffmpeg_directory = ffmpeg.parent
    ffprobe = optional_existing(settings.ffprobe_override) or _first_existing(
        [paths.tools / "ffmpeg/ffprobe.exe"]
        + _paths_below(ffmpeg_directory, ["ffprobe.exe"])
        + _system_command("ffprobe")
    )
    ffmpeg_version = None
    if ffmpeg is not None:
        ffmpeg_version = probe_output(ffmpeg, ["-version"])
    ffprobe_version = None
    if ffprobe is not None:
        ffprobe_version = probe_output(ffprobe, ["-version"])
    _emit(progress, "mediaTools", 4, "Checking FFmpeg and FFprobe…")

    deadlock = optional_existing(settings.deadlock_root_override) or locate_deadlock()
    archive = None
    if deadlock is not None:
        archive = deadlock / "game/citadel/pak01_dir.vpk"
    _emit(
        progress,
        "deadlock",
        5,
        "Checking the Steam installation and Deadlock archive…",
    )

    compiler_directory = None
    if resource_compiler is not None:
        compiler_directory = resource_compiler.parent
    lame = _first_existing(
        _paths_below(
            compiler_directory,
            ["lame_enc.dll"],
        )
        + _paths_below(
            csdk,
            [
                "game/bin/win64/lame_enc.dll",
                "game/bin_tools/win64/lame_enc.dll",
            ],
        )
    )
    _emit(progress, "encoder", 6, "Checking the CSDK audio encoder…")

    csdk_config_text = None
    if csdk_config is not None and csdk_config.is_file():
        csdk_config_text = str(csdk_config)
    archive_text = None
    if archive is not None and archive.is_file():
        archive_text = str(archive)

    resolved = ResolvedTools(
        csdk_root=_path_text(csdk),
        csdk_config=csdk_config_text,
        resource_compiler=_path_text(resource_compiler),
        vpk_packager=_path_text(vpk_packager),
        source2_viewer=_path_text(source_viewer),
        source2_viewer_cli=_path_text(source_viewer_cli),
        ffmpeg=_path_text(ffmpeg),
        ffprobe=_path_text(ffprobe),
        deadlock_root=_path_text(deadlock),
        deadlock_archive=archive_text,
        lame_encoder=_path_text(lame),
    )
    content_addons = None
    game_addons = None
    if csdk is not None:
        content_addons = csdk / "content/citadel_addons"
        game_addons = csdk / "game/citadel_addons"

    source_viewer_cli_status = CheckStatus.CAPABILITY_UNAVAILABLE
    source_viewer_cli_path = None
    source_viewer_cli_detail = "Source2Viewer-CLI.exe was not found."
    if source_viewer_cli is not None:
        source_viewer_cli_status = CheckStatus.FOUND
        source_viewer_cli_path = str(source_viewer_cli)
        source_viewer_cli_detail = "Selective headless export is available."
    elif source_viewer is not None:
        source_viewer_cli_path = str(source_viewer)
        source_viewer_cli_detail = (
            "The GUI was found, but selective preview requires "
            "Source2Viewer-CLI.exe."
        )

    checks = [
        _check("csdkRoot", "CSDK 12 root", csdk, is_directory=True),
        _check("csdkConfig", "csdkcfg.exe", csdk_config),
        _check("resourceCompiler", "CSDK resource compiler", resource_compiler),
        _check("vpkUtility", "CSDK VPK packaging utility", vpk_packager),
        _check(
            "contentAddons",
            "CSDK content/citadel_addons",
            content_addons,
            is_directory=True,
        ),
        _check(
            "gameAddons",
            "CSDK game/citadel_addons",
            game_addons,
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
            status=source_viewer_cli_status,
            path=source_viewer_cli_path,
            version=_file_version(source_viewer_cli or source_viewer),
            detail=source_viewer_cli_detail,
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
