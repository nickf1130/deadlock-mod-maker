from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from ..errors import StudioError
from ..models import ProcessRecord, utc_now

logger = logging.getLogger(__name__)


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise StudioError("CANCELLED", "Operation was cancelled")


def sanitize_arguments(arguments: Sequence[str]) -> list[str]:
    home = str(Path.home())
    return [argument.replace(home, "%USERPROFILE%") for argument in arguments]


def run_process(
    executable: Path,
    arguments: Sequence[str],
    *,
    timeout_seconds: float,
    cancellation: CancellationToken | None = None,
    cwd: Path | None = None,
    expected_files: Sequence[Path] = (),
    accept_stable_output: Path | None = None,
) -> ProcessRecord:
    if not executable.is_file():
        raise StudioError("TOOL_MISSING", f"Executable is missing: {executable}")
    started_at = utc_now()
    started = time.monotonic()
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NO_WINDOW
    working_directory = None
    if cwd:
        working_directory = str(cwd)
    safe_arguments = sanitize_arguments(arguments)
    logger.info("Starting %s with arguments %s", executable.name, safe_arguments)
    try:
        process = subprocess.Popen(
            [str(executable), *arguments],
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=creation_flags,
        )
    except OSError as error:
        logger.exception("Could not start external tool %s", executable.name)
        raise StudioError(
            "PROCESS_START_FAILED",
            f"Could not start {executable.name}.",
            {"error": str(error)},
        ) from error
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def drain(stream, chunks: list[str]) -> None:
        if stream is None:
            return
        while True:
            value = stream.read(8192)
            if not value:
                break
            chunks.append(value)

    stdout_thread = threading.Thread(
        target=drain, args=(process.stdout, stdout_chunks), daemon=True
    )
    stderr_thread = threading.Thread(
        target=drain, args=(process.stderr, stderr_chunks), daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    stable_size: int | None = None
    stable_since: float | None = None
    output_accepted = False
    while process.poll() is None:
        if cancellation and cancellation.cancelled:
            process.kill()
            process.wait()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            logger.info("Cancelled %s", executable.name)
            raise StudioError("CANCELLED", "Operation was cancelled")
        elapsed = time.monotonic() - started
        if accept_stable_output and accept_stable_output.is_file():
            size = accept_stable_output.stat().st_size
            if size > 0 and size == stable_size:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 1:
                    output_accepted = True
                    process.kill()
                    break
            else:
                stable_size = size
                stable_since = None
        if elapsed > timeout_seconds:
            process.kill()
            process.wait()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            stdout = "".join(stdout_chunks)
            stderr = "".join(stderr_chunks)
            logger.warning(
                "%s timed out after %.0f seconds",
                executable.name,
                timeout_seconds,
            )
            raise StudioError(
                "PROCESS_TIMEOUT",
                f"{executable.name} timed out after {timeout_seconds:.0f} seconds",
                {"stdout": stdout[-4000:], "stderr": stderr[-4000:]},
            )
        time.sleep(0.1)
    process.wait()
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    duration_ms = round((time.monotonic() - started) * 1000)
    produced = [str(path) for path in expected_files if path.is_file()]
    exit_code = process.returncode
    if output_accepted:
        exit_code = 0
    record = ProcessRecord(
        executable_path=str(executable),
        sanitized_arguments=safe_arguments,
        started_at=started_at,
        duration_ms=duration_ms,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        produced_files=produced,
    )
    if exit_code != 0:
        logger.warning(
            "%s failed with exit code %s after %s ms",
            executable.name,
            exit_code,
            duration_ms,
        )
        raise StudioError(
            "PROCESS_FAILED",
            f"{executable.name} failed with exit code {exit_code}",
            {"record": record.model_dump(by_alias=True)},
        )
    logger.info(
        "Finished %s successfully in %s ms", executable.name, duration_ms
    )
    return record


def probe_output(executable: Path, arguments: Sequence[str], timeout: float = 5) -> str | None:
    try:
        record = run_process(executable, arguments, timeout_seconds=timeout)
    except (StudioError, OSError):
        return None
    text = (record.stdout or record.stderr).strip()
    if not text:
        return None
    return text.splitlines()[0][:300]
