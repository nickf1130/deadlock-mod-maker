from __future__ import annotations

import json
import logging
import shutil
import zipfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from ..audio import process_audio
from ..csdk.adapters import (
    compile_resource,
    package_vpk,
    synchronize_csdk_workspace,
)
from ..csdk.encoding import EncodingEntry, generate_encoding, validate_loop
from ..errors import StudioError
from ..external.process import CancellationToken
from ..models import (
    BuildHistoryEntry,
    BuildResult,
    DiagnosticReport,
    ItemBuildResult,
    ItemStatus,
    ProcessRecord,
    VisualReplacementItem,
    VisualResourceKind,
    utc_now,
)
from ..paths import AppPaths, normalize_internal_path, source_path_for_compiled
from ..projects import (
    ProjectService,
    clear_project_build_artifacts,
    detect_conflicts,
)
from ..visuals import write_vtex_descriptor
from ..vpk import list_vpk

ProgressCallback = Callable[[dict[str, object]], None]


def create_zip(
    paths: AppPaths,
    projects: ProjectService,
    project_id: str,
    version: str,
) -> str:
    manifest = projects.load(project_id)
    export_directory = paths.exports / manifest.name / version
    vpk = export_directory / f"{manifest.name}.vpk"
    if not vpk.is_file():
        raise StudioError("EXPORT_NOT_FOUND", "The requested export does not exist.")
    output = export_directory / f"{manifest.name}-{version}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in (
            vpk.name,
            "README.txt",
        ):
            path = export_directory / filename
            if path.is_file():
                archive.write(path, filename)
    return str(output)


def create_compatibility_copy(
    paths: AppPaths,
    projects: ProjectService,
    project_id: str,
    version: str,
) -> str:
    manifest = projects.load(project_id)
    export_directory = paths.exports / manifest.name / version
    canonical = export_directory / f"{manifest.name}.vpk"
    if not canonical.is_file():
        raise StudioError("EXPORT_NOT_FOUND", "The requested export does not exist.")
    compatibility = export_directory / "pak01_dir.vpk"
    shutil.copy2(canonical, compatibility)
    return str(compatibility)


def latest_compiled(
    project_root: Path, target_path: str, current_version: str
) -> Path | None:
    build_cache = project_root / ".build-cache"
    if build_cache.is_dir():
        for version_root in sorted(build_cache.glob("build-*"), reverse=True):
            if version_root.name == current_version:
                continue
            candidate = version_root / "staging" / Path(target_path)
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate

    # Projects built by releases before 1.0 stored the same compiled file in a
    # second tree. Read that old layout for one retry, but never write it again.
    legacy_compiled_root = project_root / "compiled-game"
    if not legacy_compiled_root.is_dir():
        return None
    for version_root in sorted(legacy_compiled_root.glob("build-*"), reverse=True):
        if version_root.name == current_version:
            continue
        candidate = version_root / Path(target_path)
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def write_failure_report(
    project_root: Path,
    version: str,
    item_results: list[ItemBuildResult],
) -> Path:
    output = project_root / "failures" / f"{version}-items.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            [result.model_dump(by_alias=True) for result in item_results],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


class BuildJob:
    """State and progress callback for one complete project build."""
    def __init__(
        self,
        paths: AppPaths,
        projects: ProjectService,
        diagnostics: DiagnosticReport,
        progress: ProgressCallback,
    ):
        self.paths = paths
        self.projects = projects
        self.diagnostics = diagnostics
        self.progress = progress

    def run(
        self,
        project_id: str,
        job_id: str,
        cancellation: CancellationToken,
        *,
        retry_failed_only: bool = False,
    ) -> BuildResult:
        started = utc_now()
        manifest = self.projects.load(project_id)
        version = f"build-{len(manifest.build_history) + 1:04d}"
        all_items = manifest.target_assets + manifest.visual_assets
        conflicts = detect_conflicts(all_items)
        if conflicts:
            return BuildResult(
                success=False,
                version=version,
                stage="conflicts",
                message="Resolve path conflicts before building.",
                conflicts=conflicts,
            )
        enabled = [item for item in all_items if item.enabled]
        if not enabled:
            return BuildResult(
                success=False,
                version=version,
                stage="validation",
                message="The project has no enabled replacements.",
            )
        if retry_failed_only:
            work_items = [item for item in enabled if item.status == ItemStatus.FAILED]
            if not work_items:
                return BuildResult(
                    success=False,
                    version=version,
                    stage="retry",
                    message="No failed replacement items are available to retry.",
                )
        else:
            work_items = list(enabled)
        resolved = self.diagnostics.resolved
        sound_work_items = [
            item for item in work_items if not isinstance(item, VisualReplacementItem)
        ]
        if sound_work_items and not self.diagnostics.can_process_audio:
            return BuildResult(
                success=False,
                version=version,
                stage="capability",
                message="FFmpeg and FFprobe are required for enabled sound replacements.",
            )
        ffmpeg = None
        if resolved.ffmpeg:
            ffmpeg = Path(resolved.ffmpeg)
        ffprobe = None
        if resolved.ffprobe:
            ffprobe = Path(resolved.ffprobe)
        csdk_root = None
        if resolved.csdk_root:
            csdk_root = Path(resolved.csdk_root)
        compiler = None
        if resolved.resource_compiler:
            compiler = Path(resolved.resource_compiler)
        packager = None
        if resolved.vpk_packager:
            packager = Path(resolved.vpk_packager)
        root = self.paths.project(project_id)
        build_cache = root / ".build-cache" / version
        processed_root = build_cache / "processed-audio"
        generated_root = build_cache / "generated-content"
        staging = build_cache / "staging"
        export_directory = self.paths.exports / manifest.name / version
        export_vpk = export_directory / f"{manifest.name}.vpk"
        for directory in (generated_root, staging):
            directory.mkdir(parents=True, exist_ok=True)
        addon_name = f"dss_{manifest.name[:40]}_{manifest.id[:8].replace('-', '')}"
        item_results: list[ItemBuildResult] = []
        item_process_records: dict[str, list[ProcessRecord]] = defaultdict(list)
        generated_sources: dict[str, Path] = {}
        loop_groups: dict[Path, list[EncodingEntry]] = defaultdict(list)
        if retry_failed_only:
            work_ids = {item.id for item in work_items}
            for item in enabled:
                if item.id in work_ids:
                    continue
                normalized_target = normalize_internal_path(item.target.compiled_path)
                prior_compiled = latest_compiled(root, normalized_target, version)
                if not prior_compiled:
                    work_items.append(item)
                    work_ids.add(item.id)
                    continue
                staged_copy = staging / Path(normalized_target)
                staged_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(prior_compiled, staged_copy)
                item.status = ItemStatus.READY_FOR_PACKAGING
                item.last_error = None
                item_results.append(
                    ItemBuildResult(
                        item_id=item.id,
                        target_path=normalized_target,
                        status=ItemStatus.READY_FOR_PACKAGING,
                        source_relative_path=item.source_relative_path,
                        compiled_relative_path=str(
                            staged_copy.relative_to(root)
                        ).replace("\\", "/"),
                        reused_compiled_output=True,
                    )
                )
        total = len(work_items)
        current_item_id: str | None = None
        try:
            for index, item in enumerate(work_items, start=1):
                current_item_id = item.id
                cancellation.raise_if_cancelled()
                source = root / item.source_relative_path
                if isinstance(item, VisualReplacementItem):
                    self._progress(
                        job_id,
                        "prepareVisual",
                        index - 1,
                        total,
                        item.target.internal_path,
                    )
                    normalized_target = normalize_internal_path(
                        item.target.compiled_path
                    )
                    if item.target.kind == VisualResourceKind.MATERIAL:
                        source_internal = normalized_target[: -len("_c")]
                        generated = generated_root / Path(source_internal)
                        generated.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, generated)
                    else:
                        descriptor_internal = normalized_target[: -len("_c")]
                        descriptor = generated_root / Path(descriptor_internal)
                        image_internal = (
                            str(Path(descriptor_internal).with_suffix(""))
                            .replace("\\", "/")
                            + f"_source{source.suffix.lower()}"
                        )
                        image_target = generated_root / Path(image_internal)
                        image_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, image_target)
                        write_vtex_descriptor(
                            descriptor,
                            image_internal,
                            has_alpha=bool(item.source_metadata.has_alpha),
                            color_space=item.source_metadata.color_space or "srgb",
                            normal_map=item.source_metadata.probable_normal_map,
                        )
                        generated = descriptor
                    generated_sources[item.id] = generated
                    item.status = ItemStatus.GENERATING_SOURCE
                    current_item_id = None
                    continue
                self._progress(job_id, "processAudio", index - 1, total, item.target.internal_path)
                processed = processed_root / f"{item.id}.wav"
                item.status = ItemStatus.PROCESSING_AUDIO
                metadata = process_audio(
                    source,
                    processed,
                    item.processing,
                    ffmpeg,
                    ffprobe,
                    cancellation=cancellation,
                    record_sink=item_process_records[item.id],
                )
                duration_seconds = None
                if metadata.duration_ms:
                    duration_seconds = metadata.duration_ms / 1000
                validate_loop(
                    item.looping,
                    duration_seconds,
                )
                item.processed_relative_path = str(processed.relative_to(root)).replace("\\", "/")
                source_internal = source_path_for_compiled(item.target.compiled_path)
                generated = generated_root / Path(source_internal)
                generated.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(processed, generated)
                generated_sources[item.id] = generated
                if item.looping.enabled:
                    loop_groups[generated.parent].append(
                        EncodingEntry(filename=generated.name, loop=item.looping)
                    )
                item.status = ItemStatus.GENERATING_SOURCE
                current_item_id = None
            for directory, entries in loop_groups.items():
                encoding = directory / "encoding.txt"
                encoding.write_text(generate_encoding(entries), encoding="utf-8", newline="\n")
            self._progress(job_id, "synchronize", 0, total, None)
            content_root, _ = synchronize_csdk_workspace(
                csdk_root,
                project_id,
                addon_name,
                generated_root,
            )
            for index, item in enumerate(work_items, start=1):
                current_item_id = item.id
                cancellation.raise_if_cancelled()
                self._progress(job_id, "compile", index - 1, total, item.target.internal_path)
                relative_source = generated_sources[item.id].relative_to(generated_root)
                csdk_source = content_root / relative_source
                item.status = ItemStatus.COMPILING
                compiled, record = compile_resource(
                    compiler,
                    csdk_root,
                    csdk_source,
                    addon_name,
                    item.target.compiled_path,
                    cancellation=cancellation,
                )
                item_process_records[item.id].append(record)
                normalized_target = normalize_internal_path(item.target.compiled_path)
                staged_copy = staging / Path(normalized_target)
                staged_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(compiled, staged_copy)
                if staged_copy.stat().st_size == 0:
                    raise StudioError(
                        "STAGING_FAILED", f"Staged output is empty: {normalized_target}"
                    )
                item.status = ItemStatus.READY_FOR_PACKAGING
                item_results.append(
                    ItemBuildResult(
                        item_id=item.id,
                        target_path=normalized_target,
                        status=ItemStatus.READY_FOR_PACKAGING,
                        source_relative_path=item.source_relative_path,
                        compiled_relative_path=str(
                            staged_copy.relative_to(root)
                        ).replace("\\", "/"),
                        process_records=item_process_records[item.id],
                    )
                )
                current_item_id = None
            self._progress(job_id, "package", total, total, None)
            package_vpk(
                packager,
                staging,
                export_vpk,
                cancellation=cancellation,
            )
            entries = list_vpk(export_vpk)
            actual = [entry.path.casefold() for entry in entries]
            expected = [
                normalize_internal_path(item.target.compiled_path).casefold()
                for item in enabled
            ]
            missing = sorted(path for path in expected if actual.count(path) != 1)
            unexpected = sorted(path for path in actual if path not in set(expected))
            if missing or unexpected or len(actual) != len(expected):
                raise StudioError(
                    "VPK_VALIDATION_FAILED",
                    "The generated VPK contents do not exactly match the project manifest.",
                    {"missingOrDuplicated": missing, "unexpected": unexpected},
                )
            (export_directory / "README.txt").write_text(
                "Exported with Deadlock Mod Maker.\n\n"
                f"Import {export_vpk.name} with Deadlock Mod Manager. -> https://deadlockmods.app/\n"
                "Deadlock Mod Maker is not associated with Deadlock Mod Manager.\n",
                encoding="utf-8",
            )
            for item in enabled:
                item.status = ItemStatus.PACKAGED
                if not isinstance(item, VisualReplacementItem):
                    item.processed_relative_path = None
            for result in item_results:
                result.status = ItemStatus.PACKAGED
            manifest.build_history.append(
                BuildHistoryEntry(
                    version=version,
                    started_at=started,
                    finished_at=utc_now(),
                    success=True,
                    output_relative_path=str(export_vpk.relative_to(self.paths.root)).replace("\\", "/"),
                )
            )
            manifest.updated_at = utc_now()
            self.projects.save(manifest)
            cleanup_warnings: list[str] = []
            try:
                clear_project_build_artifacts(
                    root,
                    self.paths.backups / project_id,
                )
                if self.paths.cache.is_dir():
                    shutil.rmtree(self.paths.cache)
            except OSError as error:
                logging.exception("Could not clear build caches after export")
                cleanup_warnings.append(
                    f"The export succeeded, but temporary files could not be cleared: {error}"
                )
            self._progress(job_id, "complete", total, total, None)
            return BuildResult(
                success=True,
                version=version,
                stage="complete",
                message=f"Validated {len(expected)} compiled resources in one VPK.",
                item_results=item_results,
                vpk_path=str(export_vpk),
                export_directory=str(export_directory),
                warnings=cleanup_warnings,
            )
        except StudioError as error:
            record_payload = None
            if isinstance(error.details, dict):
                record_payload = error.details.get("record")
            if record_payload and current_item_id:
                try:
                    item_process_records[current_item_id].append(
                        ProcessRecord.model_validate(record_payload)
                    )
                except Exception:
                    pass
            completed_ids = {result.item_id for result in item_results}
            for item in enabled:
                if item.id in completed_ids:
                    item.status = ItemStatus.READY_FOR_PACKAGING
                    continue
                item.status = ItemStatus.FAILED
                if item.id == current_item_id:
                    item.last_error = str(error)
                else:
                    item.last_error = (
                        "Not completed because the build stopped on another item."
                    )
                item_results.append(
                    ItemBuildResult(
                        item_id=item.id,
                        target_path=normalize_internal_path(item.target.compiled_path),
                        status=ItemStatus.FAILED,
                        source_relative_path=item.source_relative_path,
                        error=item.last_error,
                        process_records=item_process_records[item.id],
                    )
                )
            manifest.build_history.append(
                BuildHistoryEntry(
                    version=version,
                    started_at=started,
                    finished_at=utc_now(),
                    success=False,
                    warnings=[str(error)],
                )
            )
            manifest.updated_at = utc_now()
            self.projects.save(manifest)
            item_log_path = write_failure_report(root, version, item_results)
            for transient_directory in (processed_root, generated_root):
                shutil.rmtree(transient_directory, ignore_errors=True)
            if export_vpk.is_file():
                export_vpk.unlink()
            if export_directory.is_dir() and not any(export_directory.iterdir()):
                export_directory.rmdir()
            guided_fallback_directory = None
            if error.code == "CAPABILITY_UNAVAILABLE" and staging.exists():
                guided_fallback_directory = str(staging)
            warnings = []
            if error.details:
                warnings.append(json.dumps(error.details))
            return BuildResult(
                success=False,
                version=version,
                stage=error.code,
                message=error.message,
                item_results=item_results,
                item_log_path=str(item_log_path),
                guided_fallback_directory=guided_fallback_directory,
                warnings=warnings,
            )

    def _progress(
        self,
        job_id: str,
        stage: str,
        completed: int,
        total: int,
        current_item: str | None,
    ) -> None:
        self.progress(
            {
                "event": "build.progress",
                "jobId": job_id,
                "stage": stage,
                "completed": completed,
                "total": total,
                "currentItem": current_item,
            }
        )
