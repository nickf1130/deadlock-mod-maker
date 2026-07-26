from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import deadlock_sound_studio.protocol.router as router_module
from deadlock_sound_studio.errors import StudioError
from deadlock_sound_studio.external.process import CancellationToken, run_process
from deadlock_sound_studio.projects import ProjectService
from deadlock_sound_studio.protocol.router import BackendRouter
from deadlock_sound_studio.protocol.worker import Request


def test_rpc_rejects_unknown_methods_and_invalid_parameters(paths):
    router = BackendRouter(paths, lambda _event: None)
    try:
        with pytest.raises(StudioError) as unknown:
            router.dispatch("python.eval", {})
        with pytest.raises(Exception):
            router.dispatch("projects.get", {"projectId": "one", "extra": True})
    finally:
        router.close()
    assert unknown.value.code == "METHOD_NOT_ALLOWED"


def test_project_reads_do_not_probe_external_tools(
    paths, monkeypatch: pytest.MonkeyPatch
):
    router = BackendRouter(paths, lambda _event: None)
    project = router.projects.create("Quick Read")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("project reads must not run diagnostics")

    monkeypatch.setattr(router_module, "run_diagnostics", fail_if_called)
    try:
        assert router.dispatch("projects.list", {})[0]["id"] == project.id
        assert (
            router.dispatch("projects.get", {"projectId": project.id})["id"]
            == project.id
        )
    finally:
        router.close()


def test_request_default_params_are_not_shared():
    first = Request(id="one", method="projects.list")
    second = Request(id="two", method="projects.list")
    first.params["changed"] = True
    assert second.params == {}


def test_worker_accepts_ndjson_and_reports_malformed_requests(tmp_path: Path):
    environment = os.environ.copy()
    environment["DSS_APP_ROOT"] = str(tmp_path / "worker-root")
    payload = (
        '{"id":"one","method":"projects.list","params":{}}\n'
        '{"method":"projects.list","params":{}}\n'
    )
    completed = subprocess.run(
        [sys.executable, "-m", "deadlock_sound_studio"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    responses = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    assert completed.returncode == 0
    assert responses[0] == {"id": "one", "ok": True, "result": []}
    assert responses[1]["id"] is None
    assert responses[1]["error"]["code"] == "INVALID_REQUEST"


def test_external_process_failure_has_a_stable_error():
    with pytest.raises(StudioError) as failed:
        run_process(
            Path(sys.executable),
            ["-c", "import sys; sys.exit(7)"],
            timeout_seconds=10,
        )
    assert failed.value.code == "PROCESS_FAILED"
    assert failed.value.details["record"]["exitCode"] == 7


def test_external_process_can_be_cancelled():
    cancellation = CancellationToken()
    timer = threading.Timer(0.2, cancellation.cancel)
    timer.start()
    try:
        with pytest.raises(StudioError) as cancelled:
            run_process(
                Path(sys.executable),
                ["-c", "import time; time.sleep(10)"],
                timeout_seconds=20,
                cancellation=cancellation,
            )
    finally:
        timer.cancel()
    assert cancelled.value.code == "CANCELLED"


def test_malformed_project_manifest_is_rejected(paths, database):
    service = ProjectService(paths, database)
    project = service.create("Malformed Later")
    manifest_path = paths.project(project.id) / "project.json"
    manifest_path.write_text('{"id": 123, "unknown": true}', encoding="utf-8")
    with pytest.raises(Exception):
        service.load(project.id)
