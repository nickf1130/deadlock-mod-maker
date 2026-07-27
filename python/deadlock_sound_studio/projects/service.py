from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from ..audio import inspect_audio, validate_audio_source
from ..database import Database
from ..errors import StudioError, validation_error
from ..models import (
    BatchImportTransaction,
    Conflict,
    ConflictKind,
    ItemStatus,
    LoopSettings,
    PackageMode,
    ProcessingSettings,
    ProjectManifest,
    ProjectSummary,
    ReplacementItem,
    VisualReplacementItem,
    VisualResourceKind,
    utc_now,
)
from ..paths import AppPaths, normalize_addon_name, normalize_internal_path
from ..visuals import inspect_visual_source, validate_visual_source

DISPOSABLE_BUILD_DIRECTORIES = (
    ".build-cache",
    "processed-audio",
    "previews",
    "generated-content",
    "compiled-game",
    "staging",
    "build-output",
    "logs",
)


def clear_project_build_artifacts(
    project_root: Path,
    backup_project_root: Path | None = None,
) -> None:
    """Remove generated build data while preserving project sources and failures."""
    resolved_project_root = project_root.resolve(strict=True)
    for directory_name in DISPOSABLE_BUILD_DIRECTORIES:
        directory = resolved_project_root / directory_name
        if directory.is_dir():
            shutil.rmtree(directory)
    for optional_directory_name in (
        "source-files",
        "visual-source-files",
        "failures",
    ):
        optional_directory = resolved_project_root / optional_directory_name
        try:
            optional_directory.rmdir()
        except OSError:
            pass

    if not backup_project_root or not backup_project_root.is_dir():
        return
    for build_backup in backup_project_root.glob("build-*"):
        if build_backup.is_dir():
            shutil.rmtree(build_backup)


def detect_conflicts(
    items: list[ReplacementItem | VisualReplacementItem],
) -> list[Conflict]:
    enabled = [item for item in items if item.enabled]
    grouped: dict[str, list[ReplacementItem | VisualReplacementItem]] = {}
    conflicts: list[Conflict] = []
    for item in enabled:
        try:
            target = normalize_internal_path(item.target.compiled_path)
        except StudioError as error:
            conflicts.append(
                Conflict(
                    kind=ConflictKind.INVALID_TARGET,
                    item_ids=[item.id],
                    target_path=item.target.compiled_path,
                    message=str(error),
                )
            )
            continue
        grouped.setdefault(target.casefold(), []).append(item)
    for collision in grouped.values():
        if len(collision) < 2:
            continue
        paths = {item.target.compiled_path for item in collision}
        kind = (
            ConflictKind.DUPLICATE_TARGET
            if len(paths) == 1
            else ConflictKind.CASE_INSENSITIVE_COLLISION
        )
        conflicts.append(
            Conflict(
                kind=kind,
                item_ids=[item.id for item in collision],
                target_path=collision[0].target.compiled_path,
                message="Multiple enabled replacements resolve to the same compiled path.",
            )
        )
    return conflicts


class ProjectService:
    """Owns project manifests and their on-disk source files."""

    def __init__(self, paths: AppPaths, database: Database):
        self.paths = paths
        self.database = database

    def create(
        self, display_name: str, description: str = "", author: str = ""
    ) -> ProjectManifest:
        name = normalize_addon_name(display_name)
        # The database enforces unique addon names. Checking first turns a raw
        # sqlite IntegrityError into something the user can act on, and avoids
        # leaving an empty project folder behind when the insert fails.
        if any(row["name"] == name for row in self.database.project_rows()):
            raise StudioError(
                "PROJECT_NAME_TAKEN",
                f'A project named "{name}" already exists. Choose a different name.',
                {"name": name},
            )
        project_id = str(uuid.uuid4())
        root = self.paths.project(project_id)
        root.mkdir(parents=True)
        now = utc_now()
        manifest = ProjectManifest(
            id=project_id,
            name=name,
            display_name=display_name.strip(),
            description=description,
            author=author,
            created_at=now,
            updated_at=now,
            package_mode=PackageMode.SINGLE_VPK,
        )
        self.save(manifest, backup=False)
        return manifest

    def list(self) -> list[ProjectSummary]:
        summaries: list[ProjectSummary] = []
        for row in self.database.project_rows():
            path = Path(row["manifest_path"])
            if not path.is_file():
                continue
            manifest = ProjectManifest.model_validate_json(path.read_text(encoding="utf-8"))
            last_build_success = None
            if manifest.build_history:
                last_build_success = manifest.build_history[-1].success
            summaries.append(
                ProjectSummary(
                    id=manifest.id,
                    name=manifest.name,
                    display_name=manifest.display_name,
                    updated_at=manifest.updated_at,
                    replacement_count=len(manifest.target_assets) + len(manifest.visual_assets),
                    enabled_count=sum(item.enabled for item in manifest.target_assets)
                    + sum(item.enabled for item in manifest.visual_assets),
                    last_build_success=last_build_success,
                    game_fingerprint=manifest.game_fingerprint,
                )
            )
        return summaries

    def clear_exported_build_artifacts(self) -> None:
        """Migrate successful projects away from the duplicated legacy layout."""
        for row in self.database.project_rows():
            manifest_path = Path(row["manifest_path"])
            if not manifest_path.is_file():
                continue
            manifest = ProjectManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            self._clear_legacy_export_diagnostics(manifest)
            if not manifest.build_history:
                continue
            if not manifest.build_history[-1].success:
                continue
            try:
                clear_project_build_artifacts(
                    manifest_path.parent,
                    self.paths.backups / manifest.id,
                )
            except OSError:
                logging.exception(
                    "Could not clear legacy build artifacts for project %s",
                    manifest.id,
                )

    def _clear_legacy_export_diagnostics(
        self,
        manifest: ProjectManifest,
    ) -> None:
        """Remove reports that older releases placed beside user-facing exports."""
        for build in manifest.build_history:
            export_directory = self.paths.exports / manifest.name / build.version
            for filename in ("checksums.txt", "build-report.json"):
                legacy_file = export_directory / filename
                try:
                    legacy_file.unlink(missing_ok=True)
                except OSError:
                    logging.exception(
                        "Could not remove legacy export report %s",
                        legacy_file,
                    )

    def load(self, project_id: str) -> ProjectManifest:
        manifest_path = self.paths.project(project_id) / "project.json"
        if not manifest_path.is_file():
            raise StudioError("PROJECT_NOT_FOUND", "Project does not exist.")
        return ProjectManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    def save(self, manifest: ProjectManifest, *, backup: bool = True) -> None:
        root = self.paths.project(manifest.id)
        manifest_path = root / "project.json"
        if backup and manifest_path.is_file():
            backup_root = self.paths.backups / manifest.id
            backup_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_path, backup_root / "project.previous.json")
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(manifest.model_dump(by_alias=True), indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(manifest_path)
        self.database.register_project(
            manifest.id,
            manifest.name,
            manifest.display_name,
            manifest_path,
            manifest.created_at,
            manifest.updated_at,
        )

    def delete(self, project_id: str) -> Path:
        manifest = self.load(project_id)
        source = self.paths.project(manifest.id).resolve(strict=True)
        projects_root = self.paths.projects.resolve(strict=True)
        try:
            source.relative_to(projects_root)
        except ValueError as error:
            raise StudioError(
                "UNSAFE_PROJECT_PATH",
                "The project folder is outside the application workspace.",
            ) from error

        deleted_root = self.paths.backups / "deleted-projects"
        deleted_root.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().replace(":", "-").replace("+", "_")
        destination = deleted_root / f"{manifest.id}-{timestamp}"
        shutil.move(str(source), str(destination))
        self.database.delete_project(manifest.id)
        try:
            self.paths.projects.rmdir()
        except OSError:
            pass
        return destination

    def confirm_replacement(
        self,
        project_id: str,
        asset_id: str,
        source_path: Path,
        processing: ProcessingSettings,
        looping: LoopSettings,
        ffprobe: Path | None = None,
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        asset = self.database.get_asset(asset_id)
        if not asset:
            raise StudioError("ASSET_NOT_FOUND", "The indexed target sound no longer exists.")
        source = validate_audio_source(source_path)
        metadata = inspect_audio(source, ffprobe)
        if looping.enabled:
            from ..csdk.encoding import validate_loop

            duration_seconds = None
            if metadata.duration_ms:
                duration_seconds = metadata.duration_ms / 1000
            validate_loop(
                looping,
                duration_seconds,
            )
        item_id = str(uuid.uuid4())
        destination_name = f"{item_id}_{source.name}"
        destination = self.paths.project(project_id) / "source-files" / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        warnings = list(metadata.warnings)
        if asset.channels and metadata.channels and asset.channels != metadata.channels:
            warnings.append(
                f"Replacement has {metadata.channels} channel(s); original has {asset.channels}."
            )
        manifest.target_assets.append(
            ReplacementItem(
                id=item_id,
                order=len(manifest.target_assets),
                target=asset,
                source_filename=source.name,
                source_relative_path=f"source-files/{destination_name}",
                source_metadata=metadata,
                processing=processing,
                looping=looping,
                validation_messages=warnings,
            )
        )
        manifest.game_fingerprint = asset.archive_fingerprint
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def update_replacement(
        self, project_id: str, item_id: str, changes: dict[str, object]
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        index = self._item_index(manifest, item_id)
        current = manifest.target_assets[index].model_dump()
        allowed = {"enabled", "processing", "looping"}
        unknown = set(changes) - allowed
        if unknown:
            raise validation_error("Unsupported replacement fields", fields=sorted(unknown))
        current.update(changes)
        manifest.target_assets[index] = ReplacementItem.model_validate(current)
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def confirm_visual_replacement(
        self,
        project_id: str,
        asset_id: str,
        source_path: Path,
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        asset = self.database.get_visual_asset(asset_id)
        if not asset:
            raise StudioError(
                "ASSET_NOT_FOUND", "The indexed visual target no longer exists."
            )
        source = validate_visual_source(source_path, asset.kind)
        metadata = inspect_visual_source(self.paths, source, asset.kind)
        if asset.kind == VisualResourceKind.TEXTURE and any(
            marker in asset.filename.casefold()
            for marker in ("_normal", "_norm", "_nrm")
        ):
            metadata.probable_normal_map = True
            metadata.color_space = "linear"
            if not any("Normal-map target" in message for message in metadata.warnings):
                metadata.warnings.append(
                    "Normal-map target detected; linear color and BC5 compression will be used."
                )
        if asset.kind == VisualResourceKind.MATERIAL:
            for dependency in metadata.dependencies:
                compiled_dependency = (
                    dependency
                    if dependency.casefold().endswith("_c")
                    else f"{dependency}_c"
                )
                if not self.database.get_visual_asset_by_path(compiled_dependency):
                    metadata.warnings.append(
                        f"Referenced resource is not present in the indexed archive: {dependency}"
                    )
        item_id = str(uuid.uuid4())
        destination_name = f"{item_id}_{source.name}"
        destination = (
            self.paths.project(project_id) / "visual-source-files" / destination_name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        manifest.visual_assets.append(
            VisualReplacementItem(
                id=item_id,
                order=len(manifest.visual_assets),
                target=asset,
                source_filename=source.name,
                source_relative_path=f"visual-source-files/{destination_name}",
                source_metadata=metadata,
                validation_messages=list(metadata.warnings),
            )
        )
        manifest.game_fingerprint = asset.archive_fingerprint
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def update_visual_replacement(
        self, project_id: str, item_id: str, *, enabled: bool
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        item = next((value for value in manifest.visual_assets if value.id == item_id), None)
        if not item:
            raise StudioError("ITEM_NOT_FOUND", "Visual replacement does not exist.")
        item.enabled = enabled
        item.status = ItemStatus.CONFIRMED
        item.last_error = None
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def remove_visual_replacement(
        self, project_id: str, item_id: str
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        original = len(manifest.visual_assets)
        manifest.visual_assets = [
            item for item in manifest.visual_assets if item.id != item_id
        ]
        if len(manifest.visual_assets) == original:
            raise StudioError("ITEM_NOT_FOUND", "Visual replacement does not exist.")
        for index, item in enumerate(manifest.visual_assets):
            item.order = index
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def replace_source(
        self,
        project_id: str,
        item_id: str,
        source_path: Path,
        ffprobe: Path | None = None,
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        index = self._item_index(manifest, item_id)
        item = manifest.target_assets[index]
        source = validate_audio_source(source_path)
        metadata = inspect_audio(source, ffprobe)
        if item.looping.enabled:
            from ..csdk.encoding import validate_loop

            duration_seconds = None
            if metadata.duration_ms:
                duration_seconds = metadata.duration_ms / 1000
            validate_loop(
                item.looping,
                duration_seconds,
            )
        destination_name = f"{item.id}_{uuid.uuid4().hex[:8]}_{source.name}"
        destination = self.paths.project(project_id) / "source-files" / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        warnings = list(metadata.warnings)
        if (
            item.target.channels
            and metadata.channels
            and item.target.channels != metadata.channels
        ):
            warnings.append(
                f"Replacement has {metadata.channels} channel(s); original has {item.target.channels}."
            )
        item.source_filename = source.name
        item.source_relative_path = f"source-files/{destination_name}"
        item.source_metadata = metadata
        item.processed_relative_path = None
        item.status = ItemStatus.CONFIRMED
        item.validation_messages = warnings
        item.last_error = None
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def duplicate_settings(
        self,
        project_id: str,
        source_item_id: str,
        target_item_id: str,
    ) -> ProjectManifest:
        if source_item_id == target_item_id:
            raise validation_error("Choose two different queue items.")
        manifest = self.load(project_id)
        source = manifest.target_assets[self._item_index(manifest, source_item_id)]
        target = manifest.target_assets[self._item_index(manifest, target_item_id)]
        target.processing = ProcessingSettings.model_validate(source.processing.model_dump())
        target.looping = LoopSettings.model_validate(source.looping.model_dump())
        target.processed_relative_path = None
        target.status = ItemStatus.CONFIRMED
        target.last_error = None
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def remap_target(
        self, project_id: str, item_id: str, asset_id: str
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        index = self._item_index(manifest, item_id)
        asset = self.database.get_asset(asset_id)
        if not asset:
            raise StudioError(
                "ASSET_NOT_FOUND", "The selected remap target is not in the current catalog."
            )
        item = manifest.target_assets[index]
        previous_path = item.target.internal_path
        item.target = asset
        conflicts = [
            conflict
            for conflict in detect_conflicts(manifest.target_assets)
            if item.id in conflict.item_ids
        ]
        if conflicts:
            raise validation_error(
                "The selected remap target conflicts with another enabled replacement.",
                conflicts=[
                    conflict.model_dump(by_alias=True) for conflict in conflicts
                ],
            )
        item.processed_relative_path = None
        item.status = ItemStatus.CONFIRMED
        item.last_error = None
        item.validation_messages = [
            message
            for message in item.validation_messages
            if not message.startswith("Target remapped from ")
        ]
        item.validation_messages.append(
            f"Target remapped from {previous_path} after explicit compatibility review."
        )
        manifest.game_fingerprint = asset.archive_fingerprint
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def record_batch_import(
        self, project_id: str, item_ids: list[str]
    ) -> tuple[ProjectManifest, str]:
        manifest = self.load(project_id)
        known = {item.id for item in manifest.target_assets}
        if not item_ids or any(item_id not in known for item_id in item_ids):
            raise validation_error("Batch transaction contains unknown replacement items.")
        transaction = BatchImportTransaction(
            id=str(uuid.uuid4()),
            created_at=utc_now(),
            item_ids=item_ids,
        )
        manifest.batch_import_history.append(transaction)
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest, transaction.id

    def rollback_batch_import(
        self, project_id: str, transaction_id: str
    ) -> tuple[ProjectManifest, int]:
        manifest = self.load(project_id)
        transaction = next(
            (
                candidate
                for candidate in manifest.batch_import_history
                if candidate.id == transaction_id
            ),
            None,
        )
        if not transaction:
            raise StudioError("BATCH_TRANSACTION_NOT_FOUND", "Batch import transaction was not found.")
        if transaction.rolled_back_at:
            raise validation_error("This batch import has already been rolled back.")
        item_ids = set(transaction.item_ids)
        before = len(manifest.target_assets)
        manifest.target_assets = [
            item for item in manifest.target_assets if item.id not in item_ids
        ]
        removed = before - len(manifest.target_assets)
        for order, item in enumerate(manifest.target_assets):
            item.order = order
        transaction.rolled_back_at = utc_now()
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest, removed

    def remove_replacement(self, project_id: str, item_id: str) -> ProjectManifest:
        manifest = self.load(project_id)
        before = len(manifest.target_assets)
        manifest.target_assets = [item for item in manifest.target_assets if item.id != item_id]
        if len(manifest.target_assets) == before:
            raise StudioError("ITEM_NOT_FOUND", "Replacement does not exist.")
        for order, item in enumerate(manifest.target_assets):
            item.order = order
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    def reorder_replacement(
        self, project_id: str, item_id: str, new_index: int
    ) -> ProjectManifest:
        manifest = self.load(project_id)
        old_index = self._item_index(manifest, item_id)
        item = manifest.target_assets.pop(old_index)
        manifest.target_assets.insert(min(max(new_index, 0), len(manifest.target_assets)), item)
        for order, replacement in enumerate(manifest.target_assets):
            replacement.order = order
        manifest.updated_at = utc_now()
        self.save(manifest)
        return manifest

    @staticmethod
    def _item_index(manifest: ProjectManifest, item_id: str) -> int:
        index = next(
            (
                position
                for position, item in enumerate(manifest.target_assets)
                if item.id == item_id
            ),
            None,
        )
        if index is None:
            raise StudioError("ITEM_NOT_FOUND", "Replacement does not exist.")
        return index
