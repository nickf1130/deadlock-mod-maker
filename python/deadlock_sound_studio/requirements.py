from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path

from .diagnostics import run_diagnostics
from .errors import StudioError
from .models import Settings
from .paths import AppPaths
from .settings import save_settings

SOURCE2_RELEASE_API = (
    "https://api.github.com/repos/ValveResourceFormat/"
    "ValveResourceFormat/releases/latest"
)
FFMPEG_RELEASE_API = (
    "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
)
USER_AGENT = "Deadlock-Mod-Maker/1.0.0"
MAX_EXTRACTED_BYTES = 2_000_000_000
MAX_ARCHIVE_FILES = 20_000
MAX_DOWNLOAD_BYTES = 750_000_000
MAX_RELEASE_METADATA_BYTES = 5_000_000

ProgressCallback = Callable[[dict[str, object]], None]


def install_missing_requirements(
    paths: AppPaths,
    settings: Settings,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    """Download missing portable tools from their publishers on Windows."""
    if os.name != "nt":
        raise StudioError(
            "REQUIREMENTS_PLATFORM_UNSUPPORTED",
            "Automatic requirement installation is currently available "
            "on Windows only.",
        )
    report = run_diagnostics(paths, settings)
    statuses = {check.id: check.status.value for check in report.checks}
    needs_gui = statuses.get("source2Viewer") != "found"
    needs_cli = statuses.get("source2ViewerCli") != "found"
    needs_ffmpeg = (
        statuses.get("ffmpeg") != "found"
        or statuses.get("ffprobe") != "found"
    )
    tasks = [
        name
        for name, needed in (
            ("Source 2 Viewer", needs_gui),
            ("Source 2 Viewer CLI", needs_cli),
            ("FFmpeg and FFprobe", needs_ffmpeg),
        )
        if needed
    ]
    if not tasks:
        return {
            "diagnostics": report.model_dump(by_alias=True),
            "settings": settings.model_dump(by_alias=True),
            "installed": [],
            "skipped": [
                "All downloadable requirements were already available."
            ],
        }

    work_root = paths.cache / "requirements" / uuid.uuid4().hex
    download_root = work_root / "downloads"
    source_staging = work_root / "Source2Viewer"
    ffmpeg_staging = work_root / "ffmpeg"
    download_root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    completed = 0
    total = len(tasks) + 1
    try:
        source_assets: dict[str, dict[str, object]] = {}
        if needs_gui or needs_cli:
            existing_source_tools = paths.tools / "Source2Viewer"
            if existing_source_tools.is_dir():
                shutil.copytree(
                    existing_source_tools,
                    source_staging,
                    dirs_exist_ok=True,
                )
            _emit(
                progress,
                "resolving",
                completed,
                total,
                "Finding the latest Source 2 Viewer release…",
            )
            source_assets = _release_assets(SOURCE2_RELEASE_API)
            if needs_gui:
                asset = _required_asset(source_assets, "Source2Viewer.exe")
                downloaded = _download_asset(
                    asset,
                    download_root / "Source2Viewer.exe",
                    completed,
                    total,
                    progress,
                )
                source_staging.mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    downloaded, source_staging / "Source2Viewer.exe"
                )
                completed += 1
                installed.append("Source 2 Viewer")
                _emit(
                    progress,
                    "installed",
                    completed,
                    total,
                    "Installed Source 2 Viewer.",
                )
            if needs_cli:
                architecture = (
                    "arm64"
                    if platform.machine().casefold() in {"arm64", "aarch64"}
                    else "x64"
                )
                asset = _required_asset(
                    source_assets, f"cli-windows-{architecture}.zip"
                )
                downloaded = _download_asset(
                    asset,
                    download_root / str(asset["name"]),
                    completed,
                    total,
                    progress,
                )
                source_staging.mkdir(parents=True, exist_ok=True)
                _extract_zip(downloaded, source_staging)
                cli = _find_named(source_staging, "Source2Viewer-CLI.exe")
                if cli.parent != source_staging:
                    _copy_directory_contents(cli.parent, source_staging)
                completed += 1
                installed.append("Source 2 Viewer CLI")
                _emit(
                    progress,
                    "installed",
                    completed,
                    total,
                    "Installed Source 2 Viewer CLI.",
                )

        if needs_ffmpeg:
            _emit(
                progress,
                "resolving",
                completed,
                total,
                "Finding the latest FFmpeg Windows build…",
            )
            assets = _release_assets(FFMPEG_RELEASE_API)
            architecture = (
                "winarm64"
                if platform.machine().casefold() in {"arm64", "aarch64"}
                else "win64"
            )
            asset_name = (
                f"ffmpeg-master-latest-{architecture}-gpl-shared.zip"
            )
            asset = _required_asset(assets, asset_name)
            downloaded = _download_asset(
                asset,
                download_root / asset_name,
                completed,
                total,
                progress,
            )
            extracted = work_root / "ffmpeg-extracted"
            _extract_zip(downloaded, extracted)
            ffmpeg = _find_named(extracted, "ffmpeg.exe")
            ffprobe = ffmpeg.with_name("ffprobe.exe")
            if not ffprobe.is_file():
                raise StudioError(
                    "REQUIREMENTS_INVALID_ARCHIVE",
                    "The FFmpeg archive did not contain ffprobe.exe "
                    "beside ffmpeg.exe.",
                )
            ffmpeg_staging.mkdir(parents=True, exist_ok=True)
            _copy_directory_contents(ffmpeg.parent, ffmpeg_staging)
            completed += 1
            installed.append("FFmpeg and FFprobe")
            _emit(
                progress,
                "installed",
                completed,
                total,
                "Installed FFmpeg and FFprobe.",
            )

        if source_staging.exists():
            _replace_owned_directory(
                source_staging, paths.tools / "Source2Viewer"
            )
        if ffmpeg_staging.exists():
            _replace_owned_directory(
                ffmpeg_staging, paths.tools / "ffmpeg"
            )

        next_settings = settings.model_copy(
            update={
                "source2_viewer_override": (
                    str(paths.tools / "Source2Viewer" / "Source2Viewer.exe")
                    if needs_gui
                    else settings.source2_viewer_override
                ),
                "source2_viewer_cli_override": (
                    str(
                        paths.tools
                        / "Source2Viewer"
                        / "Source2Viewer-CLI.exe"
                    )
                    if needs_cli
                    else settings.source2_viewer_cli_override
                ),
                "ffmpeg_override": (
                    str(paths.tools / "ffmpeg" / "ffmpeg.exe")
                    if needs_ffmpeg
                    else settings.ffmpeg_override
                ),
                "ffprobe_override": (
                    str(paths.tools / "ffmpeg" / "ffprobe.exe")
                    if needs_ffmpeg
                    else settings.ffprobe_override
                ),
            }
        )
        save_settings(paths, next_settings)
        _emit(
            progress,
            "verifying",
            completed,
            total,
            "Verifying installed tools…",
        )
        verified = run_diagnostics(paths, next_settings)
        failed = [
            check.label
            for check in verified.checks
            if check.id
            in {"source2Viewer", "source2ViewerCli", "ffmpeg", "ffprobe"}
            and check.status.value != "found"
        ]
        if failed:
            raise StudioError(
                "REQUIREMENTS_VERIFY_FAILED",
                "Downloaded tools did not pass diagnostics.",
                {"failed": failed},
            )
        _emit(
            progress,
            "complete",
            total,
            total,
            "Downloadable requirements are ready.",
        )
        return {
            "diagnostics": verified.model_dump(by_alias=True),
            "settings": next_settings.model_dump(by_alias=True),
            "installed": installed,
            "skipped": [],
        }
    except StudioError:
        raise
    except (
        OSError,
        urllib.error.URLError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
    ) as error:
        raise StudioError(
            "REQUIREMENTS_INSTALL_FAILED",
            f"Could not install the required tools: {error}",
        ) from error
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
        for empty_directory in (work_root.parent, paths.cache):
            try:
                empty_directory.rmdir()
            except OSError:
                pass


def _release_assets(api_url: str) -> dict[str, dict[str, object]]:
    payload = json.loads(_read_url(api_url).decode("utf-8"))
    return {
        str(asset["name"]): asset
        for asset in payload.get("assets", [])
        if isinstance(asset, dict)
        and asset.get("name")
        and asset.get("browser_download_url")
    }


def _required_asset(
    assets: dict[str, dict[str, object]], name: str
) -> dict[str, object]:
    asset = assets.get(name)
    if not asset:
        raise StudioError(
            "REQUIREMENTS_ASSET_MISSING",
            f"The publisher's latest release does not contain {name}.",
        )
    return asset


def _download_asset(
    asset: dict[str, object],
    destination: Path,
    completed: int,
    total: int,
    progress: ProgressCallback | None,
) -> Path:
    url = str(asset["browser_download_url"])
    name = str(asset["name"])
    expected_digest = str(asset.get("digest") or "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(
            request, timeout=60
        ) as response, destination.open("wb") as output:
            total_bytes = int(
                response.headers.get("Content-Length")
                or asset.get("size")
                or 0
            )
            if total_bytes > MAX_DOWNLOAD_BYTES:
                raise StudioError(
                    "REQUIREMENTS_DOWNLOAD_TOO_LARGE",
                    f"The publisher reported an unexpectedly large "
                    f"download for {name}.",
                )
            downloaded = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                downloaded += len(block)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise StudioError(
                        "REQUIREMENTS_DOWNLOAD_TOO_LARGE",
                        f"The {name} download exceeded the safety limit.",
                    )
                _emit(
                    progress,
                    "downloading",
                    completed,
                    total,
                    f"Downloading {name}…",
                    downloaded_bytes=downloaded,
                    total_bytes=total_bytes,
                )
    except urllib.error.URLError as error:
        raise StudioError(
            "REQUIREMENTS_DOWNLOAD_FAILED",
            f"Could not download {name}: {error.reason}",
            {"url": url},
        ) from error
    actual = digest.hexdigest()
    if (
        expected_digest.startswith("sha256:")
        and actual.casefold() != expected_digest[7:].casefold()
    ):
        destination.unlink(missing_ok=True)
        raise StudioError(
            "REQUIREMENTS_CHECKSUM_FAILED",
            f"The downloaded {name} did not match the publisher's "
            "SHA-256 digest.",
        )
    return destination


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MAX_RELEASE_METADATA_BYTES + 1)
            if len(payload) > MAX_RELEASE_METADATA_BYTES:
                raise StudioError(
                    "REQUIREMENTS_RELEASE_LOOKUP_FAILED",
                    "Publisher release metadata exceeded the safety limit.",
                )
            return payload
    except urllib.error.URLError as error:
        raise StudioError(
            "REQUIREMENTS_RELEASE_LOOKUP_FAILED",
            "Could not read the publisher's release information: "
            f"{error.reason}",
            {"url": url},
        ) from error


def _extract_zip(archive: Path, destination: Path) -> None:
    """Extract an archive after checking its size, count, and every path."""
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        if len(infos) > MAX_ARCHIVE_FILES:
            raise StudioError(
                "REQUIREMENTS_INVALID_ARCHIVE",
                "The downloaded archive contains too many files.",
            )
        if sum(info.file_size for info in infos) > MAX_EXTRACTED_BYTES:
            raise StudioError(
                "REQUIREMENTS_INVALID_ARCHIVE",
                "The downloaded archive is too large when extracted.",
            )
        for info in infos:
            target = (destination / info.filename).resolve()
            try:
                target.relative_to(resolved_destination)
            except ValueError as error:
                raise StudioError(
                    "REQUIREMENTS_INVALID_ARCHIVE",
                    "The downloaded archive contains an unsafe path.",
                ) from error
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as input_stream, target.open(
                "wb"
            ) as output_stream:
                shutil.copyfileobj(
                    input_stream, output_stream, length=1024 * 1024
                )


def _find_named(root: Path, filename: str) -> Path:
    matches = [path for path in root.rglob(filename) if path.is_file()]
    if not matches:
        raise StudioError(
            "REQUIREMENTS_INVALID_ARCHIVE",
            f"The downloaded archive did not contain {filename}.",
        )
    return matches[0]


def _copy_directory_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.resolve() == target.resolve():
            continue
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _replace_owned_directory(source: Path, destination: Path) -> None:
    """Swap an app-owned tool directory and restore it if the swap fails."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.installing"
    )
    backup = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.previous"
    )
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(source, temporary)
    moved_previous = False
    try:
        if destination.exists():
            os.replace(destination, backup)
            moved_previous = True
        os.replace(temporary, destination)
    except Exception:
        if moved_previous and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    completed: int,
    total: int,
    message: str,
    *,
    downloaded_bytes: int = 0,
    total_bytes: int = 0,
) -> None:
    if progress:
        progress(
            {
                "event": "requirements.progress",
                "stage": stage,
                "completed": completed,
                "total": total,
                "message": message,
                "downloadedBytes": downloaded_bytes,
                "totalBytes": total_bytes,
            }
        )
