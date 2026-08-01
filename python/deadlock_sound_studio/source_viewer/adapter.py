from __future__ import annotations

import shutil
from pathlib import Path

from ..errors import StudioError, capability_error
from ..external.process import CancellationToken, run_process
from ..models import SoundAsset, VisualResourceAsset, VisualResourceKind
from ..paths import AppPaths


def can_decompile(executable: Path | None) -> bool:
    """Return whether the selected executable is the automatable CLI build."""
    return bool(
        executable
        and executable.is_file()
        and "cli" in executable.stem.lower()
    )


def export_sound_preview(
    executable: Path | None,
    paths: AppPaths,
    asset: SoundAsset,
    *,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Export one compiled sound from the game archive to the preview cache."""
    return export_package_sound(
        executable,
        paths,
        asset.source_archive,
        asset.internal_path,
        cache_root=paths.cache / "original-previews" / asset.archive_fingerprint / asset.id,
        cancellation=cancellation,
    )


def export_package_sound(
    executable: Path | None,
    paths: AppPaths,
    package: str | Path,
    internal_path: str,
    *,
    cache_root: Path,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Export one compiled sound out of any VPK.

    The game archive is just the most common package to point this at; a mod's
    own .vpk works exactly the same way, which is what lets an installed sound
    mod be auditioned without launching the game.

    ``cache_root`` is supplied by the caller because only the caller knows what
    makes a preview stale. For the game archive that is the archive
    fingerprint; for a mod file it is the file's own modification time.
    """
    if not can_decompile(executable) or not executable:
        raise capability_error(
            "Selective original-sound preview requires Source2Viewer-CLI.exe. "
            "The GUI executable cannot be automated safely."
        )
    existing = next(
        (
            path
            for path in cache_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".wav", ".mp3"}
        ),
        None,
    )
    if existing:
        return existing
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True)
    run_process(
        executable,
        [
            "-i",
            str(package),
            "-o",
            str(cache_root),
            "-d",
            "--vpk_extensions",
            "vsnd_c",
            "--vpk_filepath",
            internal_path,
        ],
        timeout_seconds=5 * 60,
        cancellation=cancellation,
    )
    candidates = [
        path
        for path in cache_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".wav", ".mp3"}
    ]
    if len(candidates) != 1:
        raise StudioError(
            "PREVIEW_EXPORT_FAILED",
            "Source 2 Viewer did not export exactly one previewable audio file.",
            {
                "produced": [
                    str(path.relative_to(cache_root)) for path in candidates
                ]
            },
        )
    return candidates[0]


def export_visual_preview(
    executable: Path | None,
    paths: AppPaths,
    asset: VisualResourceAsset,
    *,
    cancellation: CancellationToken | None = None,
) -> Path:
    """Export one compiled texture or material to the portable preview cache."""
    if not can_decompile(executable) or not executable:
        raise capability_error(
            "Original visual preview requires Source2Viewer-CLI.exe."
        )
    cache_root = (
        paths.cache / "original-visuals" / asset.archive_fingerprint / asset.id
    )
    extensions = {".vmat", ".txt"}
    if asset.kind == VisualResourceKind.TEXTURE:
        extensions = {".png", ".tga", ".jpg", ".jpeg"}
    existing = next(
        (
            path
            for path in cache_root.rglob("*")
            if path.is_file() and path.suffix.lower() in extensions
        ),
        None,
    )
    if existing:
        return existing
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True)
    resource_extension = "vmat_c"
    if asset.kind == VisualResourceKind.TEXTURE:
        resource_extension = "vtex_c"
    run_process(
        executable,
        [
            "-i",
            asset.source_archive,
            "-o",
            str(cache_root),
            "-d",
            "--vpk_extensions",
            resource_extension,
            "--vpk_filepath",
            asset.internal_path,
        ],
        timeout_seconds=5 * 60,
        cancellation=cancellation,
    )
    candidates = [
        path
        for path in cache_root.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    ]
    if not candidates:
        produced = [
            str(path.relative_to(cache_root))
            for path in cache_root.rglob("*")
            if path.is_file()
        ]
        raise StudioError(
            "PREVIEW_EXPORT_FAILED",
            "Source 2 Viewer did not export a previewable visual resource.",
            {"produced": produced},
        )
    return candidates[0]
