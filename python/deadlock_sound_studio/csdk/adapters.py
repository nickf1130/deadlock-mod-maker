from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from ..errors import StudioError, capability_error
from ..external.process import CancellationToken, run_process
from ..models import ProcessRecord
from ..paths import normalize_internal_path


def expected_compiled_output(
    csdk_root: Path | None,
    addon_name: str,
    compiled_target: str,
) -> Path:
    if not csdk_root:
        raise capability_error("CSDK root is missing.")
    return (
        csdk_root
        / "game"
        / "citadel_addons"
        / addon_name
        / Path(normalize_internal_path(compiled_target))
    )


def compile_resource(
    executable: Path | None,
    csdk_root: Path | None,
    source: Path,
    addon_name: str,
    compiled_target: str,
    *,
    cancellation: CancellationToken | None = None,
) -> tuple[Path, ProcessRecord]:
    """Compile one source file and reject missing or stale CSDK output."""
    if not executable or not csdk_root:
        raise capability_error("The CSDK resource compiler is unavailable.")
    expected = expected_compiled_output(
        csdk_root, addon_name, compiled_target
    )
    before_mtime = None
    if expected.exists():
        before_mtime = expected.stat().st_mtime_ns
    started_ns = time.time_ns()
    record = run_process(
        executable,
        ["-i", str(source), "-f", "-nop4"],
        timeout_seconds=10 * 60,
        cancellation=cancellation,
        expected_files=[expected],
        cwd=executable.parent,
    )
    if not expected.is_file() or expected.stat().st_size == 0:
        raise StudioError(
            "COMPILED_OUTPUT_MISSING",
            "Resource Compiler exited without producing the expected compiled resource.",
            {"expected": str(expected)},
        )
    if expected.stat().st_mtime_ns < started_ns - 2_000_000_000:
        raise StudioError(
            "COMPILED_OUTPUT_STALE",
            "The expected compiled output was not written during this build.",
            {"expected": str(expected), "previousMtime": before_mtime},
        )
    return expected, record


def synchronize_csdk_workspace(
    csdk_root: Path | None,
    project_id: str,
    addon_name: str,
    generated_content: Path,
) -> tuple[Path, Path]:
    """Replace generated sources only inside an addon owned by this project."""
    if not csdk_root:
        raise capability_error("CSDK root is missing.")
    content = csdk_root / "content/citadel_addons" / addon_name
    game = csdk_root / "game/citadel_addons" / addon_name
    marker_name = ".deadlock-sound-studio.json"
    for workspace in (content, game):
        marker = workspace / marker_name
        if not workspace.exists():
            continue
        if not marker.is_file():
            raise StudioError(
                "CSDK_WORKSPACE_CONFLICT",
                f"Refusing to modify an unowned CSDK addon: {workspace}",
            )
        owner = json.loads(marker.read_text(encoding="utf-8"))
        if owner.get("projectId") != project_id:
            raise StudioError(
                "CSDK_WORKSPACE_CONFLICT",
                f"CSDK addon belongs to another project: {workspace}",
            )

    for workspace in (content, game):
        marker = workspace / marker_name
        workspace.mkdir(parents=True, exist_ok=True)
        for generated_item in workspace.iterdir():
            if generated_item.name == marker_name:
                continue
            if generated_item.is_dir():
                shutil.rmtree(generated_item)
            else:
                generated_item.unlink()
        marker.write_text(
            json.dumps(
                {"projectId": project_id, "addonName": addon_name}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
    for source in generated_content.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(generated_content)
        destination = content / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return content, game


def package_vpk(
    executable: Path | None,
    staging: Path,
    output: Path,
    *,
    cancellation: CancellationToken | None = None,
) -> ProcessRecord:
    """Package a staging directory with the selected CSDK VPK utility."""
    if not executable:
        raise capability_error(
            "No headless VPK packager was found. The staging directory is ready "
            "for the guided CSDK fallback."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    if executable.name.casefold() == "csdkcfgvpk.exe":
        record = run_process(
            executable,
            [str(staging), str(output)],
            timeout_seconds=10 * 60,
            cancellation=cancellation,
            expected_files=[output],
            accept_stable_output=output,
        )
    else:
        generated = staging.parent / f"{staging.name}.vpk"
        if generated.exists():
            generated.unlink()
        record = run_process(
            executable,
            [str(staging)],
            timeout_seconds=10 * 60,
            cancellation=cancellation,
            expected_files=[generated],
        )
        if generated.is_file():
            generated.replace(output)
    if not output.is_file() or output.stat().st_size == 0:
        raise StudioError(
            "VPK_CREATE_FAILED", "The VPK packager produced no usable output."
        )
    return record
